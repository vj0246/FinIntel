"""
discover.py
-----------
Natural-language stock SCREENER agent.

"Find IT stocks with ROE above 20 and PE under 25 where promoters are buying"
  -> LLM parses the query into a validated filter plan (whitelisted metrics +
     operators only — the LLM can't inject arbitrary logic)
  -> Python sweeps a curated NSE universe and applies the filters
     DETERMINISTICALLY (the LLM never decides pass/fail)
  -> technical metrics are computed only for fundamental survivors (2-phase,
     saves ~1 network fetch per rejected stock)
  -> the LLM writes a one-line thesis per top hit, compliance-screened.

Metric matrix per stock (fundamental phase = ONE cached Screener page fetch):
  valuation  pe, pb, dividend_yield_pct, market_cap_cr
  quality    roe_pct, roce_pct, opm_pct
  growth     rev_yoy_pct, profit_yoy_pct, rev_cagr_3y_pct, profit_cagr_3y_pct
  ownership  promoter_pct, promoter_change_pct, fii_pct, fii_change_pct, dii_pct
  technical  ret_6m_pct, rsi_14, volatility_pct, beta, sharpe, max_drawdown_pct,
             dist_52w_high_pct, dist_52w_low_pct   (phase 2, yfinance)
"""

import asyncio
import json
import time

from langchain_core.messages import HumanMessage

import groq_pool
import market
import screener
import guardrails as gr

MODEL = "openai/gpt-oss-120b"
_llm = None

# Curated universe: NIFTY 50 + prominent next-50/mid names, tagged by sector.
UNIVERSE = [
    # (ticker, sector)
    ("RELIANCE", "Energy"), ("ONGC", "Energy"), ("BPCL", "Energy"), ("IOC", "Energy"),
    ("GAIL", "Energy"), ("ADANIGREEN", "Energy"), ("TATAPOWER", "Energy"), ("NTPC", "Energy"),
    ("POWERGRID", "Energy"), ("COALINDIA", "Energy"), ("ADANIPORTS", "Infrastructure"),
    ("LT", "Infrastructure"), ("ULTRACEMCO", "Cement"), ("SHREECEM", "Cement"),
    ("AMBUJACEM", "Cement"), ("GRASIM", "Cement"),
    ("TCS", "IT"), ("INFY", "IT"), ("WIPRO", "IT"), ("HCLTECH", "IT"),
    ("TECHM", "IT"), ("LTIM", "IT"), ("PERSISTENT", "IT"), ("COFORGE", "IT"),
    ("HDFCBANK", "Banking"), ("ICICIBANK", "Banking"), ("SBIN", "Banking"),
    ("KOTAKBANK", "Banking"), ("AXISBANK", "Banking"), ("INDUSINDBK", "Banking"),
    ("BANKBARODA", "Banking"), ("PNB", "Banking"), ("CANBK", "Banking"),
    ("BAJFINANCE", "NBFC"), ("BAJAJFINSV", "NBFC"), ("SHRIRAMFIN", "NBFC"),
    ("CHOLAFIN", "NBFC"), ("MUTHOOTFIN", "NBFC"),
    ("SBILIFE", "Insurance"), ("HDFCLIFE", "Insurance"), ("ICICIPRULI", "Insurance"),
    ("MARUTI", "Auto"), ("M&M", "Auto"), ("TATAMOTORS", "Auto"), ("BAJAJ-AUTO", "Auto"),
    ("EICHERMOT", "Auto"), ("HEROMOTOCO", "Auto"), ("TVSMOTOR", "Auto"),
    ("ASHOKLEY", "Auto"), ("MOTHERSON", "Auto Components"), ("BOSCHLTD", "Auto Components"),
    ("HINDUNILVR", "FMCG"), ("ITC", "FMCG"), ("NESTLEIND", "FMCG"), ("BRITANNIA", "FMCG"),
    ("DABUR", "FMCG"), ("MARICO", "FMCG"), ("GODREJCP", "FMCG"), ("TATACONSUM", "FMCG"),
    ("VBL", "FMCG"), ("COLPAL", "FMCG"),
    ("SUNPHARMA", "Pharma"), ("DRREDDY", "Pharma"), ("CIPLA", "Pharma"),
    ("DIVISLAB", "Pharma"), ("LUPIN", "Pharma"), ("AUROPHARMA", "Pharma"),
    ("APOLLOHOSP", "Healthcare"), ("MAXHEALTH", "Healthcare"),
    ("TATASTEEL", "Metals"), ("JSWSTEEL", "Metals"), ("HINDALCO", "Metals"),
    ("VEDL", "Metals"), ("JINDALSTEL", "Metals"), ("NMDC", "Metals"),
    ("BHARTIARTL", "Telecom"), ("IDEA", "Telecom"),
    ("TITAN", "Consumer"), ("ASIANPAINT", "Consumer"), ("PIDILITIND", "Consumer"),
    ("DMART", "Retail"), ("TRENT", "Retail"), ("ZOMATO", "New-age"),
    ("PAYTM", "New-age"), ("NYKAA", "New-age"), ("POLICYBZR", "New-age"),
    ("HAL", "Defence"), ("BEL", "Defence"), ("BHEL", "Capital Goods"),
    ("SIEMENS", "Capital Goods"), ("ABB", "Capital Goods"), ("HAVELLS", "Capital Goods"),
    ("DLF", "Realty"), ("GODREJPROP", "Realty"), ("OBEROIRLTY", "Realty"),
    ("IRCTC", "Services"), ("INDIGO", "Aviation"), ("UPL", "Chemicals"),
    ("SRF", "Chemicals"), ("PIIND", "Chemicals"), ("DEEPAKNTR", "Chemicals"),
]

# Whitelisted metrics the LLM may filter/sort on -> (phase, human label)
FUND_METRICS = {
    "pe", "pb", "dividend_yield_pct", "market_cap_cr",
    "roe_pct", "roce_pct", "opm_pct",
    "rev_yoy_pct", "profit_yoy_pct", "rev_cagr_3y_pct", "profit_cagr_3y_pct",
    "promoter_pct", "promoter_change_pct", "fii_pct", "fii_change_pct", "dii_pct",
}
TECH_METRICS = {
    "ret_6m_pct", "rsi_14", "volatility_pct", "beta", "sharpe",
    "max_drawdown_pct", "dist_52w_high_pct", "dist_52w_low_pct",
}
ALL_METRICS = FUND_METRICS | TECH_METRICS
_OPS = {">", ">=", "<", "<=", "="}

_ROW_CACHE: dict = {}        # ticker -> (t, fundamental row)
_ROW_TTL = 6 * 3600
_CONCURRENCY = 6
_MAX_RESULTS = 12


def _get_llm():
    global _llm
    if _llm is None:
        _llm = groq_pool.create_llm(MODEL, temperature=0)
    return _llm


# --------------------------------------------------------------------------- #
# Per-stock metric rows
# --------------------------------------------------------------------------- #
def _cagr(new, old, years):
    try:
        if new and old and old > 0 and new > 0:
            return round(((new / old) ** (1 / years) - 1) * 100, 1)
    except Exception:
        pass
    return None


def fundamental_row(ticker: str, sector: str) -> dict:
    """Everything one Screener page gives us. Cached; {}-ish row on failure."""
    now = time.time()
    if ticker in _ROW_CACHE and now - _ROW_CACHE[ticker][0] < _ROW_TTL:
        return _ROW_CACHE[ticker][1]
    row = {"ticker": ticker, "sector": sector}
    try:
        sd = screener.symbol_data(ticker)
        row.update({"price": sd.get("price"), "pe": sd.get("pe"), "pb": sd.get("pb"),
                    "market_cap_cr": sd.get("market_cap_cr"), "roe_pct": sd.get("roe_pct"),
                    "roce_pct": sd.get("roce_pct"),
                    "dividend_yield_pct": sd.get("dividend_yield_pct"),
                    "year_high": sd.get("year_high"), "year_low": sd.get("year_low")})
        q = screener.quarterly_results(ticker, n=5)
        if len(q) >= 5:
            def yoy(k):
                a, b = q[0].get(k), q[4].get(k)
                return round((a / b - 1) * 100, 1) if (a and b and b > 0) else None
            row["rev_yoy_pct"] = yoy("revenue_cr")
            row["profit_yoy_pct"] = yoy("net_income_cr")
        a = screener.annual_results(ticker, n=5)
        # skip the TTM column for CAGR: use latest full year vs 3 years before
        yrs = [r for r in a if r.get("revenue_cr")]
        if len(yrs) >= 4:
            row["rev_cagr_3y_pct"] = _cagr(yrs[0]["revenue_cr"], yrs[3]["revenue_cr"], 3)
            row["profit_cagr_3y_pct"] = _cagr(yrs[0].get("net_income_cr"), yrs[3].get("net_income_cr"), 3)
        if yrs and yrs[0].get("opm_pct") is not None:
            row["opm_pct"] = yrs[0]["opm_pct"]
        sh = screener.shareholding(ticker, n=2)
        if sh:
            cur = sh[0]
            row.update({"promoter_pct": cur.get("promoters_pct"), "fii_pct": cur.get("fiis_pct"),
                        "dii_pct": cur.get("diis_pct")})
            if len(sh) >= 2:
                prev = sh[1]
                def delta(k):
                    a, b = cur.get(k), prev.get(k)
                    return round(a - b, 2) if (a is not None and b is not None) else None
                row["promoter_change_pct"] = delta("promoters_pct")
                row["fii_change_pct"] = delta("fiis_pct")
        if row.get("price") and row.get("year_high"):
            row["dist_52w_high_pct"] = round((row["price"] / row["year_high"] - 1) * 100, 1)
        if row.get("price") and row.get("year_low"):
            row["dist_52w_low_pct"] = round((row["price"] / row["year_low"] - 1) * 100, 1)
    except Exception:
        pass
    _ROW_CACHE[ticker] = (now, row)
    return row


def technical_row(ticker: str) -> dict:
    """Quant metrics from real price history — only fetched for survivors."""
    import quant
    try:
        m = quant.metrics(ticker)
        return {"ret_6m_pct": m.get("period_return_pct"), "rsi_14": m.get("rsi_14"),
                "volatility_pct": m.get("annualised_volatility_pct"),
                "beta": m.get("beta_vs_nifty50"), "sharpe": m.get("sharpe_ratio"),
                "max_drawdown_pct": m.get("max_drawdown_pct")}
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
# LLM -> validated filter plan
# --------------------------------------------------------------------------- #
def parse_query(query: str) -> dict:
    """{"filters":[{metric,op,value}], "sectors":[], "sort_by","sort_dir","limit"}
    Every metric/op is validated against the whitelist; anything else is dropped."""
    sectors = sorted({s for _, s in UNIVERSE})
    raw = _get_llm().invoke([HumanMessage(content=(
        "Convert this stock-screening request into JSON filters.\n"
        f"REQUEST: {query}\n\n"
        f"Allowed metrics: {sorted(ALL_METRICS)}\n"
        f"Allowed sectors: {sectors}\n"
        'Reply ONLY compact JSON: {"filters":[{"metric":"...","op":">|>=|<|<=|=","value":<number>}],'
        '"sectors":["..."],"sort_by":"<metric>","sort_dir":"desc|asc","limit":<int 1-12>}\n'
        "Notes: percentages are plain numbers (ROE above 20 -> value 20). "
        "'cheap' -> pe < 25; 'promoters buying' -> promoter_change_pct > 0; "
        "'FIIs buying' -> fii_change_pct > 0; 'near 52w low' -> dist_52w_low_pct < 15; "
        "'high growth' -> rev_yoy_pct > 15; 'low debt' has no metric here — ignore it. "
        "'oversold' -> rsi_14 < 35; 'not overheated' -> rsi_14 < 65. "
        "If no sort is implied, sort_by the most distinctive filter metric."
    ))]).content
    try:
        obj = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except Exception:
        obj = {}
    filters = []
    for f in obj.get("filters", []):
        try:
            m, op, v = f["metric"], f["op"], float(f["value"])
            if m in ALL_METRICS and op in _OPS:
                filters.append({"metric": m, "op": op, "value": v})
        except Exception:
            continue
    plan = {
        "filters": filters[:8],
        "sectors": [s for s in obj.get("sectors", []) if s in sectors][:6],
        "sort_by": obj.get("sort_by") if obj.get("sort_by") in ALL_METRICS else None,
        "sort_dir": "asc" if obj.get("sort_dir") == "asc" else "desc",
        "limit": max(1, min(int(obj.get("limit") or 8), _MAX_RESULTS)),
    }
    plan["needs_technicals"] = any(f["metric"] in TECH_METRICS for f in plan["filters"]) or \
        (plan["sort_by"] in TECH_METRICS if plan["sort_by"] else False)
    return plan


def _passes(row: dict, f: dict) -> bool:
    v = row.get(f["metric"])
    if v is None:
        return False                    # missing data never passes — honest screening
    t = f["value"]
    return {"<": v < t, "<=": v <= t, ">": v > t, ">=": v >= t, "=": abs(v - t) < 1e-9}[f["op"]]


# --------------------------------------------------------------------------- #
# SSE flow
# --------------------------------------------------------------------------- #
async def run(query: str, thread_id: str):
    yield {"type": "phase", "text": "Parsing your screen into filters…"}
    try:
        plan = await asyncio.to_thread(parse_query, query)
    except Exception as e:
        yield {"type": "error", "text": f"Couldn't parse the screen: {e}"}
        return
    if not plan["filters"] and not plan["sectors"]:
        yield {"type": "error",
               "text": "I couldn't turn that into concrete filters. Try e.g. "
                       "'IT stocks with ROE above 20 and PE below 30'."}
        return
    yield {"type": "plan", **plan}

    universe = [(t, s) for t, s in UNIVERSE if not plan["sectors"] or s in plan["sectors"]]
    fund_filters = [f for f in plan["filters"] if f["metric"] in FUND_METRICS]
    tech_filters = [f for f in plan["filters"] if f["metric"] in TECH_METRICS]

    # Phase 1 — fundamentals sweep (one cached Screener page per stock).
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def fetch_fund(t, s):
        async with sem:
            return await asyncio.to_thread(fundamental_row, t, s)

    survivors, scanned = [], 0
    tasks = [asyncio.ensure_future(fetch_fund(t, s)) for t, s in universe]
    for coro in asyncio.as_completed(tasks):
        row = await coro
        scanned += 1
        if all(_passes(row, f) for f in fund_filters):
            survivors.append(row)
        if scanned % 5 == 0 or scanned == len(universe):
            yield {"type": "progress", "scanned": scanned, "total": len(universe),
                   "hits": len(survivors)}

    # Phase 2 — technicals only for fundamental survivors.
    if plan["needs_technicals"] and survivors:
        yield {"type": "phase",
               "text": f"Computing technicals for {len(survivors)} fundamental survivors…"}
        async def fetch_tech(row):
            async with sem:
                row.update(await asyncio.to_thread(technical_row, row["ticker"]))
                return row
        survivors = list(await asyncio.gather(*[fetch_tech(r) for r in survivors]))
        survivors = [r for r in survivors if all(_passes(r, f) for f in tech_filters)]

    if not survivors:
        yield {"type": "results", "rows": [], "note": "No stock in the scanned universe passed every filter. Loosen a threshold and retry."}
        return

    key = plan["sort_by"] or (plan["filters"][0]["metric"] if plan["filters"] else "market_cap_cr")
    survivors.sort(key=lambda r: (r.get(key) is None,
                                  -(r.get(key) or 0) if plan["sort_dir"] == "desc" else (r.get(key) or 0)))
    top = survivors[:plan["limit"]]
    yield {"type": "results", "rows": top, "note": f"{len(survivors)} of {len(universe)} scanned stocks passed; showing top {len(top)} by {key}."}

    # Agent commentary — one line per pick, grounded ONLY in the row data.
    yield {"type": "phase", "text": "Writing the analyst take…"}
    try:
        raw = await asyncio.wait_for(asyncio.to_thread(lambda: _get_llm().invoke([HumanMessage(content=(
            "For each stock below, write ONE grounded sentence on why it passed this screen "
            f"('{query}') — cite 2-3 actual figures from its row. Money in ₹. Markdown list "
            "'- **TICKER** — sentence'. No advice verbs (buy/sell), no invented numbers.\n\n"
            f"ROWS:\n{json.dumps(top, default=str)}"
        ))]).content), timeout=60)
        yield {"type": "commentary", "text": gr.enforce_compliance(raw)}
    except Exception:
        pass
