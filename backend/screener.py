"""
screener.py
-----------
Fundamentals from Screener.in — the source Indian retail investors actually
cross-check against. Unlike NSE (standalone-only, datacenter-IP-blocked) and
yfinance (raw statements we have to recompute, and a famously wrong dividend
yield), Screener publishes the *consolidated* headline ratios ready-made:
Stock P/E, Book Value, Dividend Yield, ROCE, ROE, Market Cap.

Why this fixes "the numbers look fake":
  - P/E here is CONSOLIDATED (e.g. Reliance ~22.9), matching MoneyControl /
    Tickertape / Google, instead of NSE's standalone 18.66.
  - Dividend yield is Screener's clean trailing figure, not our rolling-window
    sum that double-counted interim+final+special payouts.

No API key, no login — the company page is public. Best-effort: every failure
returns {} and the caller falls back to NSE/yfinance. A circuit-breaker avoids
hammering it when it's unreachable.
"""

import re
import html
import time

BASE = "https://www.screener.in"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

_SESSION = None
_CACHE: dict = {}
_TTL = 600
_DOWN_UNTIL = 0.0
_COOLDOWN = 300

# Screener label -> our normalised key. Only the headline ratios we trust it for.
_WANT = {
    "Stock P/E": "pe",
    "Dividend Yield": "dividend_yield_pct",
    "ROE": "roe_pct",
    "ROCE": "roce_pct",
    "Book Value": "book_value",
    "Market Cap": "market_cap_cr",       # Screener reports market cap in ₹ crore
    "Current Price": "price",
    "High / Low": "_high_low",
}


def _session():
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    from curl_cffi import requests as creq
    s = creq.Session(impersonate="chrome")
    s.headers.update(HEADERS)
    _SESSION = s
    return s


def _num(s):
    """First number in a Screener value string ('₹ 7,57,881 Cr.' -> 757881.0)."""
    if not s:
        return None
    s = s.replace(",", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _parse(txt: str) -> dict:
    """Pull the top 'company ratios' list off a Screener company page."""
    items = re.findall(
        r'<li[^>]*>\s*<span class="name">(.*?)</span>.*?'
        r'<span class="(?:nowrap )?value">(.*?)</span>',
        txt, re.S)
    raw = {}
    for name, val in items:
        name = re.sub(r"<[^>]+>", "", name).strip()
        val = html.unescape(re.sub(r"<[^>]+>", "", val))
        val = re.sub(r"\s+", " ", val).strip()
        if name and name not in raw:
            raw[name] = val

    out = {}
    for label, key in _WANT.items():
        if label not in raw:
            continue
        if key == "_high_low":                      # "₹ 3,489 / 2,055"
            parts = re.findall(r"-?\d[\d,]*(?:\.\d+)?", raw[label])
            if len(parts) >= 2:
                out["year_high"] = _num(parts[0])
                out["year_low"] = _num(parts[1])
            continue
        v = _num(raw[label])
        if v is not None:
            out[key] = v

    # P/B isn't published directly, but price / book value gives it (and matches
    # what we computed from the balance sheet to two decimals).
    if out.get("price") and out.get("book_value"):
        out["pb"] = round(out["price"] / out["book_value"], 2)
    if out.get("market_cap_cr"):
        out["market_cap"] = round(out["market_cap_cr"] * 1e7)
    return out


def symbol_data(ticker: str) -> dict:
    """Consolidated headline ratios for one NSE symbol, or {} if unreachable.

    Tries the consolidated page first (correct for most companies), then the
    standalone page (banks/finance names that have no consolidated view)."""
    global _SESSION, _DOWN_UNTIL
    key = (ticker or "").strip().upper().replace(".NS", "").replace(".BO", "")
    if not key:
        return {}
    now = time.time()
    if now < _DOWN_UNTIL:
        return {}
    if key in _CACHE and now - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]

    out = {}
    try:
        s = _session()
        for path in (f"/company/{key}/consolidated/", f"/company/{key}/"):
            r = s.get(BASE + path, timeout=10)
            if r.status_code == 200 and "Stock P/E" in r.text:
                parsed = _parse(r.text)
                if parsed.get("pe") or parsed.get("market_cap_cr"):
                    out = parsed
                    break
    except Exception:
        _SESSION = None
        _DOWN_UNTIL = now + _COOLDOWN
        return {}

    _CACHE[key] = (now, out)
    return out
