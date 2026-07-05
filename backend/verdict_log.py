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


_NOTIONAL = 100_000          # every call becomes a ₹1,00,000 virtual position


def _nifty_close_on(date_str: str):
    """NIFTY 50 close on (or the first trading day after) a given date."""
    try:
        from quant import _nifty_closes
        closes = _nifty_closes()
        if not closes:
            return None
        d = date_str[:10]
        for ds in sorted(closes):
            if ds >= d:
                return closes[ds]
    except Exception:
        pass
    return None


def _nifty_now():
    try:
        from quant import _nifty_closes
        closes = _nifty_closes()
        if closes:
            return closes[max(closes)]
    except Exception:
        pass
    return None


def ledger() -> dict:
    """Paper-trading ledger: every logged BUY/SELL becomes a ₹1L virtual position
    (BUY = long, SELL = short signal; HOLD excluded), marked to market against the
    live price, with alpha vs NIFTY 50 over the same holding window."""
    entries = _load()
    now = datetime.now(timezone.utc)
    nifty_now = _nifty_now()
    positions, total_pnl, wins, closed_like = [], 0.0, 0, 0
    bench_pnl = 0.0
    bench_positions = 0

    for e in reversed(entries[-50:]):
        if e["verdict"] not in ("BUY", "SELL"):
            continue
        direction = 1 if e["verdict"] == "BUY" else -1
        row = {"ticker": e["ticker"], "verdict": e["verdict"], "source": e.get("source", "desk"),
               "date": e["date"][:10], "entry_price": e["price"], "notional": _NOTIONAL}
        try:
            cur = market.quote(e["ticker"]).get("price")
            if not cur:
                raise ValueError("no price")
            move_pct = (cur / e["price"] - 1) * 100
            pnl = round(_NOTIONAL * direction * move_pct / 100)
            row.update({"current_price": cur, "move_pct": round(move_pct, 2),
                        "pnl": pnl, "pnl_pct": round(direction * move_pct, 2),
                        "days_held": (now - datetime.fromisoformat(e["date"])).days})
            total_pnl += pnl
            wins += pnl > 0
            closed_like += 1
            # Benchmark: same ₹1L long NIFTY over the same window.
            n0 = _nifty_close_on(e["date"])
            if n0 and nifty_now:
                brow = _NOTIONAL * (nifty_now / n0 - 1)
                row["nifty_pnl"] = round(brow)
                row["alpha"] = round(pnl - brow)
                bench_pnl += brow
                bench_positions += 1
        except Exception:
            row["status"] = "no data"
        positions.append(row)

    return {
        "positions": positions,
        "notional_per_call": _NOTIONAL,
        "total_pnl": round(total_pnl),
        "win_rate_pct": round(wins / closed_like * 100, 1) if closed_like else None,
        "positions_marked": closed_like,
        "nifty_pnl": round(bench_pnl) if bench_positions else None,
        "alpha": round(total_pnl - bench_pnl) if bench_positions else None,
    }


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
