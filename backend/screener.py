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
_PAGE_CACHE: dict = {}      # raw HTML per symbol, shared by ratios + quarterly parsing
_TTL_MARKET = 600        # 10 min during market hours
_TTL_OFFHOURS = 86400    # 24 hours outside market hours
_DOWN_UNTIL = 0.0
_COOLDOWN = 300

def _get_ttl() -> int:
    try:
        from market import _market_open
        return _TTL_MARKET if _market_open() else _TTL_OFFHOURS
    except Exception:
        return _TTL_MARKET

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

# Screener "Quarterly Results" row label -> our key. Values are already in ₹ crore
# (EPS in ₹). Banks/NBFCs use "Revenue"/"Financing Profit" where most names show
# "Sales"/"Operating Profit", so each key lists the labels to try in order.
_Q_ROWS = {
    "revenue_cr": ("Sales", "Revenue"),
    "net_income_cr": ("Net Profit",),
    "operating_income_cr": ("Operating Profit", "Financing Profit"),
    "eps": ("EPS in Rs", "EPS"),
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


def _key(ticker: str) -> str:
    return (ticker or "").strip().upper().replace(".NS", "").replace(".BO", "")


def _get_page(key: str) -> str:
    """Fetch a Screener company page as raw HTML (consolidated preferred, then
    standalone for banks/finance names), cached and shared by the ratio and
    quarterly parsers. Returns '' on failure or while the circuit-breaker is open."""
    global _SESSION, _DOWN_UNTIL
    if not key:
        return ""
    now = time.time()
    if now < _DOWN_UNTIL:
        return ""
    if key in _PAGE_CACHE and now - _PAGE_CACHE[key][0] < _get_ttl():
        return _PAGE_CACHE[key][1]
    text = ""
    try:
        s = _session()
        for path in (f"/company/{key}/consolidated/", f"/company/{key}/"):
            r = s.get(BASE + path, timeout=10)
            if r.status_code == 200 and "Stock P/E" in r.text:
                text = r.text
                break
    except Exception:
        _SESSION = None
        _DOWN_UNTIL = now + _COOLDOWN
        return ""
    _PAGE_CACHE[key] = (now, text)
    return text


def symbol_data(ticker: str) -> dict:
    """Consolidated headline ratios for one NSE symbol, or {} if unreachable.

    Tries the consolidated page first (correct for most companies), then the
    standalone page (banks/finance names that have no consolidated view)."""
    key = _key(ticker)
    if not key:
        return {}
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < _get_ttl():
        return _CACHE[key][1]
    text = _get_page(key)
    if not text:                         # circuit open / fetch failed — retry later
        return {}
    parsed = _parse(text)
    out = parsed if (parsed.get("pe") or parsed.get("market_cap_cr")) else {}
    _CACHE[key] = (now, out)
    return out


def _parse_quarters(txt: str, n: int) -> list:
    """Parse Screener's 'Quarterly Results' table into recent-first rows
    (revenue / net profit / operating income in ₹ crore, plus EPS)."""
    m = re.search(r'id="quarters".*?</section>', txt, re.S)
    if not m:
        return []
    block = m.group(0)
    thead = re.search(r"<thead.*?</thead>", block, re.S)
    if not thead:
        return []
    cols = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<th[^>]*>(.*?)</th>", thead.group(0), re.S)]
    cols = [c for c in cols if c]        # drop the empty row-label header cell
    if not cols:
        return []

    rows = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", block, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if not cells:
            continue
        label = html.unescape(re.sub(r"<[^>]+>", "", cells[0])).replace("\xa0", " ").strip()
        rows[label] = [_num(re.sub(r"<[^>]+>", "", c)) for c in cells[1:]]

    def series(names):
        for nm in names:
            for label, vals in rows.items():
                if label.lower().startswith(nm.lower()):
                    return vals
        return []

    keyed = {k: series(names) for k, names in _Q_ROWS.items()}
    out = []
    for i, q in enumerate(cols):
        rec = {"quarter": q}
        for k, vals in keyed.items():
            v = vals[i] if i < len(vals) else None
            rec[k] = (round(v) if k != "eps" else v) if v is not None else None
        out.append(rec)
    out.reverse()                        # most recent quarter first
    return out[:max(1, n)]


def quarterly_results(ticker: str, n: int = 8) -> list:
    """Recent quarterly results (revenue, net profit, operating income in ₹ crore,
    plus EPS) from Screener's Quarterly Results table — up to ~12 quarters, far more
    history than yfinance's ~4. Most recent first. Returns [] if unreachable so the
    caller can fall back to yfinance."""
    text = _get_page(_key(ticker))
    return _parse_quarters(text, n) if text else []


# --------------------------------------------------------------------------- #
# Annual results + shareholding pattern (same page, different sections)
# --------------------------------------------------------------------------- #
def _section(txt: str, sec_id: str) -> str:
    m = re.search(rf'id="{sec_id}".*?</section>', txt, re.S)
    return m.group(0) if m else ""


def _table(block: str):
    """(columns, {row_label: [values]}) parsed from a Screener data table."""
    thead = re.search(r"<thead.*?</thead>", block, re.S)
    if not thead:
        return [], {}
    cols = [re.sub(r"<[^>]+>", "", c).strip()
            for c in re.findall(r"<th[^>]*>(.*?)</th>", thead.group(0), re.S)]
    cols = [c for c in cols if c]
    rows = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", block, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if not cells:
            continue
        label = html.unescape(re.sub(r"<[^>]+>", "", cells[0])).replace("\xa0", " ").strip()
        rows[label] = [_num(re.sub(r"<[^>]+>", "", c)) for c in cells[1:]]
    return cols, rows


# Screener annual "Profit & Loss" row label -> our key (₹ crore; EPS/OPM as given).
_A_ROWS = {
    "revenue_cr": ("Sales", "Revenue"),
    "net_income_cr": ("Net Profit",),
    "operating_income_cr": ("Operating Profit", "Financing Profit"),
    "opm_pct": ("OPM %", "Financing Margin %"),
    "eps": ("EPS in Rs", "EPS"),
}


def annual_results(ticker: str, n: int = 5) -> list:
    """Yearly P&L (revenue, net profit, operating profit in ₹ crore, OPM %, EPS)
    from Screener's Profit & Loss table — ~10 years + TTM. Most recent first."""
    text = _get_page(_key(ticker))
    if not text:
        return []
    cols, rows = _table(_section(text, "profit-loss"))
    if not cols:
        return []

    def series(names):
        for nm in names:
            for label, vals in rows.items():
                if label.lower().startswith(nm.lower()):
                    return vals
        return []

    keyed = {k: series(names) for k, names in _A_ROWS.items()}
    out = []
    for i, y in enumerate(cols):
        rec = {"year": y}
        for k, vals in keyed.items():
            v = vals[i] if i < len(vals) else None
            rec[k] = (round(v) if k in ("revenue_cr", "net_income_cr", "operating_income_cr")
                      else v) if v is not None else None
        out.append(rec)
    out.reverse()                        # most recent (TTM) first
    return out[:max(1, n)]


# Shareholding row label -> our key (values are % of equity).
_SH_ROWS = {
    "promoters_pct": ("Promoters",),
    "fiis_pct": ("FIIs",),
    "diis_pct": ("DIIs",),
    "government_pct": ("Government",),
    "public_pct": ("Public",),
}


def shareholding(ticker: str, n: int = 5) -> list:
    """Quarterly shareholding pattern (promoters / FIIs / DIIs / government /
    public, % of equity) from Screener. Most recent quarter first."""
    text = _get_page(_key(ticker))
    if not text:
        return []
    cols, rows = _table(_section(text, "shareholding"))
    if not cols:
        return []

    def series(names):
        for nm in names:
            for label, vals in rows.items():
                if label.replace("+", "").strip().lower().startswith(nm.lower()):
                    return vals
        return []

    keyed = {k: series(names) for k, names in _SH_ROWS.items()}
    out = []
    for i, q in enumerate(cols):
        rec = {"quarter": q}
        any_val = False
        for k, vals in keyed.items():
            v = vals[i] if i < len(vals) else None
            rec[k] = v
            any_val = any_val or v is not None
        if any_val:
            out.append(rec)
    out.reverse()                        # most recent first
    return out[:max(1, n)]
