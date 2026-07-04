"""
quant.py
--------
Deterministic quantitative analysis. All numbers are COMPUTED in Python from
real price history — the LLM only interprets them, it never does arithmetic.

Metrics (6-month daily closes from market.bundle):
  annualised volatility, Sharpe ratio (vs 6.5% Indian risk-free), max drawdown,
  beta vs NIFTY 50, RSI(14), SMA 20/50 positioning and crossover signal.
"""

import math
from datetime import datetime, timedelta

import market

_RISK_FREE = 0.065          # Indian 10Y G-Sec, close enough for a demo
_TRADING_DAYS = 252

_nifty_cache: dict = {}     # date-keyed closes for the index, fetched once per process


def _returns(closes: list[float]) -> list[float]:
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1]]


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs):
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _max_drawdown(closes: list[float]) -> float:
    peak, worst = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        worst = min(worst, c / peak - 1)
    return round(worst * 100, 2)


def _rsi(closes: list[float], period: int = 14):
    if len(closes) <= period:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = _mean(gains[:period])
    avg_l = _mean(losses[:period])
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_g / avg_l), 1)


def _nifty_closes() -> dict:
    """{date_str: close} for NIFTY 50 over ~6 months; {} if unavailable."""
    if _nifty_cache:
        return _nifty_cache
    try:
        import yfinance as yf
        hist = yf.Ticker("^NSEI").history(period="6mo", interval="1d")
        hist = hist.dropna(subset=["Close"])
        for idx, row in hist.iterrows():
            _nifty_cache[str(idx.date())] = float(row["Close"])
    except Exception:
        pass
    return _nifty_cache


def _beta(chart: list[dict]):
    """Beta vs NIFTY 50 from date-aligned daily returns; None if index data missing."""
    idx = _nifty_closes()
    if not idx:
        return None
    pairs = [(c["close"], idx[c["date"]]) for c in chart if c.get("date") in idx]
    if len(pairs) < 30:
        return None
    stock_r = _returns([p[0] for p in pairs])
    index_r = _returns([p[1] for p in pairs])
    n = min(len(stock_r), len(index_r))
    stock_r, index_r = stock_r[:n], index_r[:n]
    mi = _mean(index_r)
    var_i = sum((r - mi) ** 2 for r in index_r) / (n - 1)
    if var_i == 0:
        return None
    ms = _mean(stock_r)
    cov = sum((s - ms) * (i - mi) for s, i in zip(stock_r, index_r)) / (n - 1)
    return round(cov / var_i, 2)


def metrics(ticker: str) -> dict:
    """Full quant snapshot for one stock. Raises if there's no usable history."""
    b = market.bundle(ticker)
    chart = [c for c in b["chart"]
             if isinstance(c.get("close"), (int, float)) and c["close"] == c["close"]]
    closes = [c["close"] for c in chart]
    if len(closes) < 30:
        raise ValueError("not enough price history for quantitative analysis")

    rets = _returns(closes)
    vol = _std(rets) * math.sqrt(_TRADING_DAYS)
    ann_ret = _mean(rets) * _TRADING_DAYS
    sharpe = round((ann_ret - _RISK_FREE) / vol, 2) if vol else None

    sma = lambda n: round(_mean(closes[-n:]), 2)
    sma20, sma50 = sma(20), sma(50)
    last = closes[-1]
    if sma20 > sma50 and last > sma20:
        trend = "bullish (price above rising 20d, 20d above 50d)"
    elif sma20 < sma50 and last < sma20:
        trend = "bearish (price below 20d, 20d below 50d)"
    else:
        trend = "mixed / transitioning"

    return {
        "ticker": b["ticker"], "last_close": last,
        "period_return_pct": round((closes[-1] / closes[0] - 1) * 100, 2),
        "annualised_volatility_pct": round(vol * 100, 1),
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": _max_drawdown(closes),
        "beta_vs_nifty50": _beta(chart),
        "rsi_14": _rsi(closes),
        "sma_20": sma20, "sma_50": sma50,
        "trend_signal": trend,
        "risk_free_rate_pct": _RISK_FREE * 100,
        "sample_days": len(closes),
        "source": b.get("source", "sample"),
    }
