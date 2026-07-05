"""
llm_cache.py
------------
Tiny thread-safe in-memory TTL cache for expensive results that are stable over
hours: LLM outputs that are deterministic-ish per input (ecosystem maps,
competitor lists, compliance verdicts on identical text) and slow computed data
(per-stock beta). Cuts both latency and Groq token burn on repeat requests.

Not persistent by design — Render's free tier restarts wipe it, and every
cached item can be recomputed from source.
"""

import hashlib
import threading
import time

_STORE: dict = {}
_LOCK = threading.Lock()
_MAX = 600


def key(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8", "ignore")).hexdigest()[:32]


def get(k: str):
    with _LOCK:
        hit = _STORE.get(k)
        if not hit:
            return None
        expires, value = hit
        if time.time() > expires:
            _STORE.pop(k, None)
            return None
        return value


def put(k: str, value, ttl: float):
    with _LOCK:
        if len(_STORE) >= _MAX:
            now = time.time()
            for kk in [kk for kk, (e, _) in _STORE.items() if e < now]:
                _STORE.pop(kk, None)
            while len(_STORE) >= _MAX:          # still full -> drop oldest inserts
                _STORE.pop(next(iter(_STORE)), None)
        _STORE[k] = (time.time() + ttl, value)


def stats() -> dict:
    with _LOCK:
        return {"entries": len(_STORE)}
