"""
nse.py
------
Best-effort fundamentals straight from NSE India (authoritative for Indian
stocks: P/E, sector P/E, market cap, 52-week range, delivery %, volatility).

NSE serves these only to browser-like clients and **blocks many datacenter IPs**
(so it usually works from an Indian machine but not from a US cloud host). Every
call therefore fails gracefully and the caller falls back to yfinance. A small
circuit-breaker stops us from repeatedly waiting on timeouts when NSE is blocked.
"""

import time

BASE = "https://www.nseindia.com"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

_SESSION = None
_CACHE: dict = {}
_TTL = 300
_DOWN_UNTIL = 0.0          # circuit-breaker: skip NSE until this time after a failure
_COOLDOWN = 300


def _f(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _session():
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    from curl_cffi import requests as creq
    s = creq.Session(impersonate="chrome")
    s.headers.update(HEADERS)
    s.get(BASE, timeout=5)        # warm up cookies (raises on failure -> caller backs off)
    _SESSION = s
    return s


def symbol_data(ticker: str) -> dict:
    """Authoritative fundamentals for one NSE symbol, or {} if NSE is unreachable."""
    global _SESSION, _DOWN_UNTIL
    key = (ticker or "").strip().upper().replace(".NS", "").replace(".BO", "")
    if not key:
        return {}
    now = time.time()
    if now < _DOWN_UNTIL:                       # NSE recently failed — don't hang on it
        return {}
    if key in _CACHE and now - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]

    out = {}
    try:
        s = _session()
        url = (f"{BASE}/api/NextApi/apiClient/GetQuoteApi?functionName=getSymbolData"
               f"&marketType=N&series=EQ&symbol={key}")
        r = s.get(url, timeout=6)
        eq = (r.json() or {}).get("equityResponse", [])
        if eq:
            sym = eq[0]
            sec = sym.get("secInfo") or {}
            ti = sym.get("tradeInfo") or {}
            pi = sym.get("priceInfo") or {}
            mc = _f(ti.get("totalMarketCap"))     # in rupees
            out = {
                "pe": _f(sec.get("pdSymbolPe")),
                "sector_pe": _f(sec.get("pdSectorPe")),
                "sector": sec.get("sector") or None,
                "industry": sec.get("basicIndustry") or None,
                "market_cap": mc,
                "market_cap_cr": round(mc / 1e7) if mc else None,
                "year_high": _f(pi.get("yearHigh")),
                "year_low": _f(pi.get("yearLow")),
                "annual_volatility_pct": _f(pi.get("cmAnnualVolatility")),
                "delivery_pct": _f(ti.get("deliveryToTradedQuantity")),
            }
            out = {k: v for k, v in out.items() if v is not None}
    except Exception:
        _SESSION = None                          # drop a stale session
        _DOWN_UNTIL = now + _COOLDOWN             # back off so we don't keep timing out
        return {}

    _CACHE[key] = (now, out)
    return out
