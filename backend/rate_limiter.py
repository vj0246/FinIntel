"""
rate_limiter.py
---------------
In-process sliding-window rate limiter for FastAPI.

No external dependencies (Redis, memcached etc.) — suitable for a single-process
deployment on Render / Railway / Fly.io.  Tracks request counts per client IP
in a thread-safe dict with periodic cleanup of expired entries.

Usage in app_multi.py:
    from rate_limiter import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware)
"""

import time
import threading
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


# --------------------------------------------------------------------------- #
# Sliding-window counter
# --------------------------------------------------------------------------- #
class SlidingWindowLimiter:
    """Thread-safe sliding-window rate limiter.

    Each `check(key)` call records a timestamp.  The window is `window_seconds`
    wide.  If more than `max_requests` timestamps fall inside the window, the
    request is denied.
    """

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window = window_seconds
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, float]:
        """Returns (allowed, retry_after_seconds).

        If allowed is False, retry_after gives the caller how many seconds to
        wait before the oldest request in the window expires.
        """
        now = time.time()
        cutoff = now - self.window

        with self._lock:
            bucket = self._buckets[key]
            # Prune expired timestamps
            bucket[:] = [t for t in bucket if t > cutoff]

            if len(bucket) >= self.max_requests:
                # Earliest timestamp in the window — when it expires, a slot opens
                retry_after = bucket[0] - cutoff
                return False, max(retry_after, 1.0)

            bucket.append(now)
            return True, 0.0

    def cleanup(self):
        """Remove keys with no recent activity (call periodically)."""
        now = time.time()
        with self._lock:
            stale = [k for k, v in self._buckets.items()
                     if not v or v[-1] < now - self.window * 2]
            for k in stale:
                del self._buckets[k]


# --------------------------------------------------------------------------- #
# Per-tier limiters — deliberately LIGHT: the goal is stopping abuse/hammering,
# never blocking a real user. Every action stays comfortably runnable several
# times a minute.
# --------------------------------------------------------------------------- #
# Global: 150 req/min per IP (autocomplete keystrokes + parallel UI fetches add up)
_global = SlidingWindowLimiter(max_requests=150, window_seconds=60)

# LLM-calling endpoints: 12 req/min per IP
_expensive = SlidingWindowLimiter(max_requests=12, window_seconds=60)

# Heavy multi-agent orchestrations (many LLM calls each): 6 req/min per IP
_heavy = SlidingWindowLimiter(max_requests=6, window_seconds=60)

# Lightweight endpoints: 120 req/min per IP
_lightweight = SlidingWindowLimiter(max_requests=120, window_seconds=60)

# Upload: 8 req/min per IP (chat documents + portfolio CSVs)
_upload = SlidingWindowLimiter(max_requests=8, window_seconds=60)

# Endpoint path → tier limiter
_EXPENSIVE_PATHS = {"/api/analyze", "/api/resume", "/api/chat",
                    "/api/task/start", "/api/task/step",
                    "/api/portfolio/resume", "/api/war/resume",
                    "/api/ecosystem", "/api/portfolio/stress"}
_HEAVY_PATHS = {"/api/report", "/api/war/start", "/api/discover", "/api/brief",
                "/api/portfolio/analyze", "/api/backtest"}
_LIGHTWEIGHT_PATHS = {"/api/symbols", "/api/health", "/api/cache/status",
                      "/api/track-record", "/api/ledger"}
_UPLOAD_PATHS = {"/api/upload", "/api/portfolio"}


def _tier_for(path: str) -> SlidingWindowLimiter | None:
    if path in _EXPENSIVE_PATHS:
        return _expensive
    if path in _HEAVY_PATHS:
        return _heavy
    if path in _LIGHTWEIGHT_PATHS:
        return _lightweight
    if path in _UPLOAD_PATHS:
        return _upload
    return None


# --------------------------------------------------------------------------- #
# Periodic cleanup (runs every 5 minutes in a daemon thread)
# --------------------------------------------------------------------------- #
def _cleanup_loop():
    while True:
        time.sleep(300)
        for limiter in (_global, _expensive, _heavy, _lightweight, _upload):
            limiter.cleanup()


_cleaner = threading.Thread(target=_cleanup_loop, daemon=True)
_cleaner.start()


# --------------------------------------------------------------------------- #
# FastAPI / Starlette middleware
# --------------------------------------------------------------------------- #
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Applies global + per-tier rate limiting based on client IP."""

    async def dispatch(self, request: Request, call_next):
        # Determine client IP (respect X-Forwarded-For behind a proxy)
        forwarded = request.headers.get("x-forwarded-for")
        client_ip = forwarded.split(",")[0].strip() if forwarded else (
            request.client.host if request.client else "unknown"
        )
        path = request.url.path

        # 1) Global rate check
        allowed, retry_after = _global.check(client_ip)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"error": "Too many requests. Please slow down.",
                         "retry_after": round(retry_after, 1)},
                headers={"Retry-After": str(int(retry_after) + 1)},
            )

        # 2) Tier-specific rate check
        tier = _tier_for(path)
        if tier is not None:
            allowed, retry_after = tier.check(client_ip)
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"error": "Rate limit exceeded for this endpoint. Please wait.",
                             "retry_after": round(retry_after, 1)},
                    headers={"Retry-After": str(int(retry_after) + 1)},
                )

        return await call_next(request)
