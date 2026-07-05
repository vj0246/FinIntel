"""
brief.py
--------
Morning Brief agent: one glance before the market opens.

  - Global cues: US close, Asia, USD/INR, Brent, Gold + Indian indices
  - Each watchlist stock: live quote, day move, fresh headlines, RSI flag,
    earnings-within-14-days flag (all fetched in parallel)
  - An LLM turns the real numbers into a "what matters today" brief,
    through the full compliance pipeline. All money in ₹.

The watchlist itself lives in the user's browser (localStorage) — the API is
stateless: GET /api/brief?tickers=A,B,C.
"""

import asyncio
import datetime
import json
import time

from langchain_core.messages import HumanMessage

import groq_pool
import market
import guardrails as gr

MODEL = "openai/gpt-oss-120b"
_llm = None

_GLOBAL = [("S&P 500", "^GSPC"), ("NASDAQ", "^IXIC"), ("Nikkei 225", "^N225"),
           ("Hang Seng", "^HSI"), ("USD/INR", "INR=X"), ("Brent crude", "BZ=F"),
           ("Gold", "GC=F")]
_GLOBAL_CACHE: dict = {}
_MAX_WATCH = 8
_CONCURRENCY = 3


def _get_llm():
    global _llm
    if _llm is None:
        _llm = groq_pool.create_llm(MODEL, temperature=0.3)
    return _llm


def _global_cues() -> list:
    """World markets snapshot (cached 10 min)."""
    now = time.time()
    if _GLOBAL_CACHE and now - _GLOBAL_CACHE.get("t", 0) < 600:
        return _GLOBAL_CACHE["data"]
    import yfinance as yf
    try:
        from curl_cffi import requests as _creq
        sess = _creq.Session(impersonate="chrome")
    except Exception:
        sess = None
    out = []
    for name, sym in _GLOBAL:
        try:
            tk = yf.Ticker(sym, session=sess) if sess else yf.Ticker(sym)
            fi = tk.fast_info
            last = getattr(fi, "last_price", None)
            prev = getattr(fi, "previous_close", None)
            if last and last == last:
                out.append({"name": name, "level": round(float(last), 2),
                            "change_pct": round((last / prev - 1) * 100, 2) if prev else None})
        except Exception:
            continue
    if out:
        _GLOBAL_CACHE["t"], _GLOBAL_CACHE["data"] = now, out
    return out


def _stock_card(ticker: str) -> dict:
    """Everything a trader wants to know about one stock before the open."""
    b = market.bundle(ticker)
    q = market.quote(ticker)
    card = {"ticker": b["ticker"], "name": b.get("name", b["ticker"]),
            "price": q.get("price"), "day_change_pct": q.get("change_pct"),
            "market_state": q.get("market_state"),
            "headlines": [n["headline"] for n in b.get("news", [])[:3] if n.get("headline")],
            "source": b.get("source", "sample")}
    try:
        import quant
        m = quant.metrics(ticker)
        card["rsi_14"] = m.get("rsi_14")
        if m.get("rsi_14") is not None:
            card["rsi_flag"] = ("oversold" if m["rsi_14"] < 30
                                else "overbought" if m["rsi_14"] > 70 else None)
        card["trend"] = m.get("trend_signal")
    except Exception:
        pass
    try:
        e = market.next_earnings(ticker)
        d = e.get("next_earnings_date")
        if d:
            days = (datetime.date.fromisoformat(d[:10]) - datetime.date.today()).days
            if 0 <= days <= 14:
                card["earnings_in_days"] = days
                card["earnings_date"] = d[:10]
    except Exception:
        pass
    return {k: v for k, v in card.items() if v is not None}


async def run(tickers: list, thread_id: str):
    tickers = [t.strip().upper() for t in tickers if t.strip()][:_MAX_WATCH]
    today = datetime.datetime.now().strftime("%A, %d %B %Y")
    yield {"type": "phase", "text": f"Assembling your brief for {today}…"}

    # Markets first — indices + global cues in parallel.
    idx_task = asyncio.to_thread(market.indices)
    glob_task = asyncio.to_thread(_global_cues)
    indices, global_cues = await asyncio.gather(idx_task, glob_task)
    yield {"type": "markets", "india": indices, "global": global_cues, "date": today}

    # Watchlist cards in parallel, streamed as each lands.
    cards = []
    if tickers:
        yield {"type": "phase", "text": f"Checking your {len(tickers)} watchlist stocks…"}
        sem = asyncio.Semaphore(_CONCURRENCY)

        async def fetch(t):
            async with sem:
                return await asyncio.to_thread(_stock_card, t)

        for coro in asyncio.as_completed([fetch(t) for t in tickers]):
            try:
                card = await coro
                cards.append(card)
                yield {"type": "stock", **card}
            except Exception as e:
                yield {"type": "stock", "ticker": "?", "error": str(e)[:200]}

    # The brief itself — grounded ONLY in what was just fetched.
    yield {"type": "phase", "text": "Writing the brief…"}
    try:
        raw = await asyncio.wait_for(asyncio.to_thread(lambda: _get_llm().invoke([HumanMessage(content=(
            f"Write a MORNING MARKET BRIEF for an Indian equity investor ({today}). "
            "Use ONLY the data below — never invent numbers, names or events. Markdown, "
            "3 short sections: '## Global cues' (2-3 sentences from the world data), "
            "'## Indian market' (indices + VIX read), and — only if watchlist data exists — "
            "'## Your watchlist' (one bullet per stock: the move, the headline that matters, "
            "any earnings/RSI flag). All money in ₹ for Indian stocks. Analytical, terse, "
            "no directive advice, no disclaimers.\n\n"
            f"INDIAN INDICES:\n{json.dumps(indices, default=str)}\n\n"
            f"GLOBAL:\n{json.dumps(global_cues, default=str)}\n\n"
            f"WATCHLIST:\n{json.dumps(cards, default=str) if cards else '(empty)'}"
        ))]).content), timeout=75)
        yield {"type": "brief", "text": gr.enforce_compliance(raw)}
    except Exception as e:
        yield {"type": "error", "text": f"Couldn't write the brief: {e}"}
