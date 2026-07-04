"""
verdict_log.py
--------------
Track record: every BUY/HOLD/SELL verdict the desk issues is logged with the
price at call time. On request, each call is re-checked against the CURRENT
price and scored — the agent grades its own past calls.

Scoring (simple, honest, stated in the UI):
  BUY   correct if price moved > +2% since the call
  SELL  correct if price moved < -2% since the call
  HOLD  correct if price stayed within ±5%
  Calls younger than 2 days are 'too fresh' and not scored.

Storage: a JSON file next to the code. On Render's free tier the filesystem is
ephemeral, so the log resets on redeploy — fine for a demo, swap for a DB later.
"""

import json
import os
import re
import threading
from datetime import datetime, timezone

import market

_PATH = os.path.join(os.path.dirname(__file__), "verdict_log.json")
_LOCK = threading.Lock()
_MAX_ENTRIES = 200

_VERDICT_RE = re.compile(r"\b(BUY|SELL|HOLD)\b")


def _load() -> list:
    try:
        with open(_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(entries: list):
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump(entries[-_MAX_ENTRIES:], f, indent=1, default=str)


def extract_verdict(text: str) -> str | None:
    m = _VERDICT_RE.search(text or "")
    return m.group(1) if m else None


def log_verdict(ticker: str, verdict: str, price, source: str = "desk"):
    """Append one call. Never raises — logging must not break the agent."""
    try:
        if not ticker or verdict not in ("BUY", "SELL", "HOLD") or not price:
            return
        with _LOCK:
            entries = _load()
            entries.append({
                "ticker": ticker.upper(), "verdict": verdict,
                "price": round(float(price), 2), "source": source,
                "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            _save(entries)
    except Exception:
        pass


def _score(verdict: str, change_pct: float) -> bool:
    if verdict == "BUY":
        return change_pct > 2
    if verdict == "SELL":
        return change_pct < -2
    return abs(change_pct) <= 5          # HOLD


def track_record() -> dict:
    """Re-check every logged call against the current price and score it."""
    entries = _load()
    now = datetime.now(timezone.utc)
    calls, correct, scored = [], 0, 0

    for e in reversed(entries[-50:]):     # newest first, keep the API light
        row = dict(e)
        try:
            cur = market.quote(e["ticker"]).get("price")
            if cur:
                chg = round((cur / e["price"] - 1) * 100, 2)
                age_days = (now - datetime.fromisoformat(e["date"])).days
                row.update({"current_price": cur, "change_pct": chg})
                if age_days < 2:
                    row["status"] = "too fresh"
                else:
                    ok = _score(e["verdict"], chg)
                    row["status"] = "correct" if ok else "wrong"
                    scored += 1
                    correct += ok
            else:
                row["status"] = "no data"
        except Exception:
            row["status"] = "no data"
        calls.append(row)

    return {
        "calls": calls,
        "scored": scored,
        "correct": correct,
        "hit_rate_pct": round(correct / scored * 100, 1) if scored else None,
    }
