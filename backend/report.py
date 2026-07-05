"""
report.py
---------
One-click DEEP RESEARCH REPORT: every engine on the desk, orchestrated into a
single institutional-style note the user can print to PDF.

Section order (each streamed as soon as it's ready):
  cover -> snapshot -> quant -> quarterly/annual tables -> shareholding ->
  ecosystem -> bull vs bear -> desk verdict -> executive summary

Numbers are 100% from live data modules (market/quant/screener); the LLM only
narrates. The verdict is logged to the track record (source="report") so the
report is accountable like every other call. All money ₹; summary runs the
full compliance pipeline.
"""

import asyncio
import datetime
import json

from langchain_core.messages import HumanMessage

import groq_pool
import market
import guardrails as gr
import verdict_log

MODEL = "openai/gpt-oss-120b"
_llm = None
_TIMEOUT = 240


def _get_llm():
    global _llm
    if _llm is None:
        _llm = groq_pool.create_llm(MODEL, temperature=0.3)
    return _llm


def _ask(prompt: str) -> str:
    return _get_llm().invoke([HumanMessage(content=prompt)]).content


async def run(ticker: str, thread_id: str):
    start = asyncio.get_event_loop().time()

    def timed_out():
        return asyncio.get_event_loop().time() - start > _TIMEOUT

    yield {"type": "phase", "text": "Pulling live data…"}
    try:
        b = await asyncio.to_thread(market.bundle, ticker)
    except Exception as e:
        yield {"type": "error", "text": str(e)}
        return
    f = b.get("fundamentals", {})
    today = datetime.date.today().isoformat()
    yield {"type": "cover", "ticker": b["ticker"], "name": b.get("name", b["ticker"]),
           "date": today, "price": (b.get("quote") or {}).get("price"),
           "sector": f.get("sector"), "industry": f.get("industry"),
           "source": b.get("source", "sample")}

    # Snapshot — straight from fundamentals (deterministic).
    snap = {k: f.get(k) for k in ("pe", "pb", "sector_pe", "market_cap_cr", "roe_pct",
                                  "roce_pct", "net_margin_pct", "dividend_yield_pct",
                                  "debt_to_equity", "eps_ttm", "revenue_ttm_cr") if f.get(k) is not None}
    snap["week52"] = b.get("week52", {})
    snap["change_6m_pct"] = (b.get("price") or {}).get("change_pct")
    yield {"type": "snapshot", "data": snap}

    # Quant + statements + shareholding + ecosystem map, all in parallel.
    yield {"type": "phase", "text": "Quant metrics, statements, shareholding, ecosystem — in parallel…"}

    def _quant():
        import quant
        try:
            return quant.metrics(ticker)
        except Exception:
            return {}

    def _eco():
        import ecosystem
        try:
            return ecosystem.build_map(ticker)[1]
        except Exception:
            return {}

    quant_m, qtr, ann, shp, eco = await asyncio.gather(
        asyncio.to_thread(_quant),
        asyncio.to_thread(market.quarterly, ticker, 4),
        asyncio.to_thread(market.annual, ticker, 4),
        asyncio.to_thread(market.shareholding, ticker),
        asyncio.to_thread(_eco),
    )
    if quant_m:
        yield {"type": "quant", "data": quant_m}
    if qtr or ann:
        yield {"type": "financials", "quarterly": qtr, "annual": ann}
    if shp:
        yield {"type": "shareholding", "data": shp}
    if eco:
        yield {"type": "ecosystem", "data": eco}

    evidence = {"fundamentals": f, "snapshot": snap, "quant": quant_m,
                "quarterly": qtr[:4], "annual": ann[:4], "shareholding": shp[:3],
                "ecosystem": {k: eco.get(k) for k in ("competitors", "moat", "key_risks")},
                "news": [n.get("headline") for n in b.get("news", [])[:6]]}

    # Bull vs bear — LLM narration over the real evidence.
    if timed_out():
        yield {"type": "error", "text": "Report timed out while assembling data."}
        return
    yield {"type": "phase", "text": "Arguing the bull and bear cases…"}
    try:
        bb = await asyncio.wait_for(asyncio.to_thread(_ask,
            "From ONLY this data, write '### Bull case' (3 bullets) then '### Bear case' "
            "(3 bullets) — every bullet cites an actual figure. ₹ for money. No advice.\n\n"
            + json.dumps(evidence, default=str)), timeout=60)
        yield {"type": "bullbear", "text": gr.enforce_compliance(bb, disclaimer=False)}
    except Exception:
        bb = ""

    # Desk verdict — reuse the multi-agent desk pipeline.
    yield {"type": "phase", "text": "Desk verdict…"}
    verdict, action, rec = None, None, ""
    try:
        from agent_multi import researcher, risk_check, synthesize
        def _desk():
            state = {"data": {"price": b["price"], "fundamentals": f, "news": b["news"]}}
            state.update(researcher(state)); state.update(risk_check(state)); state.update(synthesize(state))
            return state
        state = await asyncio.wait_for(asyncio.to_thread(_desk), timeout=90)
        rec = state.get("recommendation", "")
        action = state.get("action")
        verdict = verdict_log.extract_verdict(rec)
        yield {"type": "verdict", "verdict": verdict, "action": action,
               "text": gr.enforce_compliance(rec, disclaimer=False)}
        price = (b.get("quote") or {}).get("price")
        if verdict and price:
            verdict_log.log_verdict(b["ticker"], verdict, price, source="report")
    except Exception:
        pass

    # Executive summary — last, so it can reference everything above.
    yield {"type": "phase", "text": "Executive summary…"}
    try:
        summ = await asyncio.wait_for(asyncio.to_thread(_ask,
            "Write the EXECUTIVE SUMMARY (2 tight paragraphs, markdown) of an equity research "
            "note, from ONLY this data — cite real figures, ₹ for money, analytical tone, no "
            "directive advice, no disclaimers.\n\nDATA:\n" + json.dumps(evidence, default=str)
            + f"\n\nBULL/BEAR:\n{bb[:2000]}\n\nDESK RECOMMENDATION:\n{rec[:1500]}"), timeout=60)
        yield {"type": "summary", "text": gr.enforce_compliance(summ)}
    except Exception:
        yield {"type": "summary", "text": gr.append_disclaimer("Summary unavailable — see the sections above.")}
