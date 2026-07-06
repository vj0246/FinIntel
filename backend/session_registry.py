"""
session_registry.py
--------------------
Bounded eviction for the demo's per-thread in-memory state.

Every interactive flow (chat, desk, war room, portfolio, task agent) keys its
state by a fresh UUID minted in the browser on each session. Left unbounded,
a long-running process accumulates one dict entry (or LangGraph MemorySaver
checkpoint) per thread FOREVER — existing per-thread caps (e.g. chat history
kept to the last 8 messages) only bound each thread's own size, not the
NUMBER of threads. On a small always-on host this is a slow memory leak that
becomes a real DoS risk under sustained traffic.

Usage: each store calls `register_evictor(fn)` once at import time and
`touch(thread_id)` whenever a thread is created/used. A background sweep
(and an inline check on every touch) evicts threads that are stale (past
_TTL) or, if the live count still exceeds _MAX_THREADS, the oldest ones —
calling every registered evictor for each evicted id.
"""

import threading
import time

_MAX_THREADS = 400
_TTL = 6 * 3600          # 6 hours of inactivity

_touched: dict = {}      # thread_id -> last-touch unix time
_evictors: list = []     # callables(thread_id) -> None, best-effort
_LOCK = threading.RLock()


def register_evictor(fn):
    """A store calls this once at import time with its own cleanup callback."""
    _evictors.append(fn)


def _sweep_locked():
    """Must hold _LOCK. Evict stale/excess threads across every registered store."""
    now = time.time()
    stale = [t for t, ts in _touched.items() if now - ts > _TTL]
    stale_set = set(stale)
    if len(_touched) - len(stale_set) > _MAX_THREADS:
        alive = sorted((ts, t) for t, ts in _touched.items() if t not in stale_set)
        overflow = len(alive) - _MAX_THREADS
        if overflow > 0:
            stale.extend(t for _, t in alive[:overflow])
    for t in stale:
        _touched.pop(t, None)
        for fn in _evictors:
            try:
                fn(t)
            except Exception:
                pass


def touch(thread_id: str):
    """Call whenever a thread is created/used, from any registered store."""
    if not thread_id:
        return
    with _LOCK:
        _touched[thread_id] = time.time()
        if len(_touched) > _MAX_THREADS:
            _sweep_locked()


def _cleanup_loop():
    while True:
        time.sleep(1800)
        with _LOCK:
            _sweep_locked()


threading.Thread(target=_cleanup_loop, daemon=True).start()
