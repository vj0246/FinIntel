"""
backtest.py
-----------
What-if / backtest agent. EVERY number is computed in Python from real price
history — the LLM only narrates the result. All money in ₹.

Supported inputs (all validated server-side):
  tickers        1-3 NSE symbols, compared side by side
  mode           lumpsum | sip | both
  lumpsum        one-time amount ₹ (default 1,00,000)
  sip_amount     monthly amount ₹ (default 10,000)
  sip_day        day of month for the SIP purchase, 1-28 (default 1)
  stepup_pct     annual SIP increase % (default 0)
  years          lookback preset 1-10 (default 3) — or explicit start/end dates
  brokerage_pct  % cost per buy trade (default 0)
  dividends      include dividend cash (held as cash, not reinvested)
  benchmark      run the same strategy on NIFTY 50 (^NSEI)

Metrics per run: invested, final value, dividend cash, absolute return %,
CAGR (lumpsum) / XIRR (SIP, bisection), max drawdown of the position value,
best/worst single day, number of trades.
"""

import asyncio
import datetime
import json

from langchain_core.messages import HumanMessage

import groq_pool
import guardrails as gr

MODEL = "openai/gpt-oss-120b"
_llm = None
_HIST_CACHE: dict = {}
_HIST_TTL = 6 * 3600
_MAX_POINTS = 150            # chart series downsample cap


def _get_llm():
    global _llm
    if _llm is None:
        _llm = groq_pool.create_llm(MODEL, temperature=0.3)
    return _llm


# --------------------------------------------------------------------------- #
# Price history (long-window, cached) — independent of market.py's 6mo bundle
# --------------------------------------------------------------------------- #
def _yf_symbol(t: str) -> str:
    t = t.strip().upper()
    if t.startswith("^") or t.endswith("=X") or t.endswith("=F"):
        return t
    return t if (t.endswith(".NS") or t.endswith(".BO")) else t + ".NS"


def _history(symbol: str, start: str, end: str):
    """(closes, dividends): closes = [(date_str, close)], dividends = [(date_str, per-share ₹)]."""
    import time as _t
    key = (symbol, start, end)
    now = _t.time()
    if key in _HIST_CACHE and now - _HIST_CACHE[key][0] < _HIST_TTL:
        return _HIST_CACHE[key][1]
    import yfinance as yf
    try:
        from curl_cffi import requests as _creq
        tk = yf.Ticker(_yf_symbol(symbol), session=_creq.Session(impersonate="chrome"))
    except Exception:
        tk = yf.Ticker(_yf_symbol(symbol))
    hist = tk.history(start=start, end=end, interval="1d", auto_adjust=False)
    hist = hist.dropna(subset=["Close"])
    if hist.empty:
        raise ValueError(f"no price history for {symbol} in that window")
    closes = [(str(i.date()), float(r["Close"])) for i, r in hist.iterrows()]
    divs = []
    if "Dividends" in hist.columns:
        divs = [(str(i.date()), float(v)) for i, v in hist["Dividends"].items() if v and v > 0]
    _HIST_CACHE[key] = (now, (closes, divs))
    return closes, divs


# --------------------------------------------------------------------------- #
# Deterministic math
# --------------------------------------------------------------------------- #
def _xirr(cashflows: list) -> float | None:
    """Annualised IRR of dated cashflows [(date_str, amount)] via bisection.
    Negative = money in, positive = money out (final value)."""
    if len(cashflows) < 2:
        return None
    d0 = datetime.date.fromisoformat(cashflows[0][0])

    def npv(rate):
        total = 0.0
        for ds, amt in cashflows:
            t = (datetime.date.fromisoformat(ds) - d0).days / 365.25
            total += amt / (1 + rate) ** t
        return total

    lo, hi = -0.95, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7:
            break
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return round(((lo + hi) / 2) * 100, 2)


def _drawdown(values: list) -> float:
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1)
    return round(worst * 100, 2)


def _sample(series: list) -> list:
    if len(series) <= _MAX_POINTS:
        return series
    step = len(series) / _MAX_POINTS
    out = [series[int(i * step)] for i in range(_MAX_POINTS)]
    if out[-1] is not series[-1]:
        out.append(series[-1])
    return out


def _div_cash(divs, holdings_by_date):
    """Dividend cash: per-share amount × units held on the ex-date."""
    cash = 0.0
    for ds, per_share in divs:
        units = 0.0
        for d, u in holdings_by_date:
            if d <= ds:
                units = u
            else:
                break
        cash += per_share * units
    return cash


def run_lumpsum(closes, divs, amount, brokerage_pct, include_divs):
    d0, p0 = closes[0]
    units = amount * (1 - brokerage_pct / 100) / p0
    series = [{"date": d, "value": round(units * p), "invested": round(amount)} for d, p in closes]
    values = [s["value"] for s in series]
    rets = [(closes[i][1] / closes[i - 1][1] - 1) * 100 for i in range(1, len(closes))]
    dcash = _div_cash(divs, [(d0, units)]) if include_divs else 0.0
    final = values[-1] + dcash
    yrs = max((datetime.date.fromisoformat(closes[-1][0]) - datetime.date.fromisoformat(d0)).days, 1) / 365.25
    cagr = round(((final / amount) ** (1 / yrs) - 1) * 100, 2) if final > 0 else None
    return {
        "strategy": "lumpsum", "invested": round(amount), "units": round(units, 2),
        "buy_price": round(p0, 2), "buy_date": d0, "trades": 1,
        "dividend_cash": round(dcash), "final_value": round(final),
        "abs_return_pct": round((final / amount - 1) * 100, 2),
        "cagr_pct": cagr, "max_drawdown_pct": _drawdown(values),
        "best_day_pct": round(max(rets), 2) if rets else None,
        "worst_day_pct": round(min(rets), 2) if rets else None,
        "series": _sample(series),
    }


def run_sip(closes, divs, monthly, sip_day, stepup_pct, brokerage_pct, include_divs):
    by_date = {d: p for d, p in closes}
    dates = [d for d, _ in closes]
    start = datetime.date.fromisoformat(dates[0])
    end = datetime.date.fromisoformat(dates[-1])

    # Build the buy schedule: first trading day on/after (y, m, sip_day).
    buys, cashflows, holdings_by_date = [], [], []
    units = invested = 0.0
    y, m = start.year, start.month
    if start.day > sip_day:
        m += 1
        if m > 12:
            m, y = 1, y + 1
    amount = monthly
    first_year = y
    idx = 0
    while True:
        try:
            target = datetime.date(y, m, sip_day)
        except ValueError:
            target = datetime.date(y, m, 28)
        if target > end:
            break
        ts = target.isoformat()
        while idx < len(dates) and dates[idx] < ts:
            idx += 1
        if idx >= len(dates):
            break
        d = dates[idx]
        p = by_date[d]
        amt = amount
        u = amt * (1 - brokerage_pct / 100) / p
        units += u
        invested += amt
        buys.append({"date": d, "price": round(p, 2), "amount": round(amt)})
        cashflows.append((d, -amt))
        holdings_by_date.append((d, units))
        m += 1
        if m > 12:
            m, y = 1, y + 1
            if stepup_pct:
                amount = amount * (1 + stepup_pct / 100)
    if not buys:
        raise ValueError("the window is too short for even one SIP purchase")

    # Position value over time (0 units before the first buy).
    series, values = [], []
    h_idx, cur_units = -1, 0.0
    for d, p in closes:
        while h_idx + 1 < len(holdings_by_date) and holdings_by_date[h_idx + 1][0] <= d:
            h_idx += 1
            cur_units = holdings_by_date[h_idx][1]
        inv = sum(b["amount"] for b in buys if b["date"] <= d)
        v = round(cur_units * p)
        series.append({"date": d, "value": v, "invested": round(inv)})
        if cur_units > 0:
            values.append(v)

    dcash = _div_cash(divs, holdings_by_date) if include_divs else 0.0
    final = series[-1]["value"] + dcash
    cashflows.append((dates[-1], final))
    return {
        "strategy": "sip", "invested": round(invested), "units": round(units, 2),
        "trades": len(buys), "avg_buy_price": round(invested / units, 2) if units else None,
        "first_sip": buys[0]["date"], "last_sip": buys[-1]["date"],
        "monthly_start": round(monthly), "stepup_pct": stepup_pct,
        "dividend_cash": round(dcash), "final_value": round(final),
        "abs_return_pct": round((final / invested - 1) * 100, 2) if invested else None,
        "xirr_pct": _xirr(cashflows),
        "max_drawdown_pct": _drawdown(values) if values else None,
        "series": _sample(series),
    }


# --------------------------------------------------------------------------- #
# SSE flow
# --------------------------------------------------------------------------- #
async def run(params: dict, thread_id: str):
    tickers = params["tickers"]
    start, end = params["start"], params["end"]
    modes = ["lumpsum", "sip"] if params["mode"] == "both" else [params["mode"]]
    yield {"type": "params", **{k: v for k, v in params.items()}}

    results = []            # (label, mode, metrics-without-series)
    for t in tickers + (["NIFTY 50"] if params["benchmark"] else []):
        sym = "^NSEI" if t == "NIFTY 50" else t
        yield {"type": "phase", "text": f"Fetching {t} history {start} → {end}…"}
        try:
            closes, divs = await asyncio.to_thread(_history, sym, start, end)
        except Exception as e:
            yield {"type": "warn", "text": f"{t}: {e}"}
            continue
        for mode in modes:
            try:
                if mode == "lumpsum":
                    r = await asyncio.to_thread(run_lumpsum, closes, divs, params["lumpsum"],
                                                params["brokerage_pct"], params["dividends"])
                else:
                    r = await asyncio.to_thread(run_sip, closes, divs, params["sip_amount"],
                                                params["sip_day"], params["stepup_pct"],
                                                params["brokerage_pct"], params["dividends"])
                r["ticker"] = t
                r["is_benchmark"] = t == "NIFTY 50"
                yield {"type": "result", **r}
                results.append({k: v for k, v in r.items() if k != "series"})
            except Exception as e:
                yield {"type": "warn", "text": f"{t} {mode}: {e}"}

    if not results:
        yield {"type": "error", "text": "No backtest could be run — check the tickers and window."}
        return

    yield {"type": "phase", "text": "Reading the results…"}
    try:
        raw = await asyncio.wait_for(asyncio.to_thread(lambda: _get_llm().invoke([HumanMessage(content=(
            "Narrate this backtest for an Indian investor in 2 short markdown paragraphs, "
            "from ONLY the computed results below — cite the actual ₹ values and percentages. "
            "Compare strategies/tickers/benchmark where present (who compounded better, what "
            "the drawdown felt like, what the SIP smoothed). Past performance ONLY — say "
            "explicitly that this describes the past, not a prediction. No advice verbs.\n\n"
            f"WINDOW: {start} to {end}\nRESULTS:\n{json.dumps(results, default=str)}"
        ))]).content), timeout=60)
        text = gr.enforce_compliance(raw)
    except Exception:
        text = gr.append_disclaimer("The computed results are shown above.")
    yield {"type": "narrative", "text": text}


def validate_params(args: dict) -> dict:
    """Clamp every user input to a sane range; raise ValueError on junk."""
    tickers = [t.strip().upper() for t in (args.get("tickers") or "").replace(" ", ",").split(",") if t.strip()]
    tickers = list(dict.fromkeys(tickers))[:3]
    if not tickers:
        raise ValueError("Give at least one NSE ticker.")
    import re as _re
    for t in tickers:
        if not _re.match(r"^[A-Z0-9&\-\.]{1,20}$", t):
            raise ValueError(f"'{t}' doesn't look like an NSE ticker.")
    mode = args.get("mode", "sip")
    if mode not in ("lumpsum", "sip", "both"):
        mode = "sip"
    today = datetime.date.today()
    if args.get("start") and args.get("end"):
        start = datetime.date.fromisoformat(str(args["start"])[:10])
        end = min(datetime.date.fromisoformat(str(args["end"])[:10]), today)
    else:
        years = max(1, min(int(float(args.get("years") or 3)), 10))
        end = today
        start = today.replace(year=today.year - years)
    if (end - start).days < 90:
        raise ValueError("Window must be at least 3 months.")
    return {
        "tickers": tickers, "mode": mode,
        "start": start.isoformat(), "end": end.isoformat(),
        "lumpsum": max(1000, min(float(args.get("lumpsum") or 100000), 1e9)),
        "sip_amount": max(500, min(float(args.get("sip_amount") or 10000), 1e8)),
        "sip_day": max(1, min(int(float(args.get("sip_day") or 1)), 28)),
        "stepup_pct": max(0, min(float(args.get("stepup_pct") or 0), 100)),
        "brokerage_pct": max(0, min(float(args.get("brokerage_pct") or 0), 5)),
        "dividends": str(args.get("dividends", "0")) in ("1", "true", "True"),
        "benchmark": str(args.get("benchmark", "1")) in ("1", "true", "True"),
    }
