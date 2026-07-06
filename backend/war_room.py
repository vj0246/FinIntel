"""
war_room.py
-----------
Research War Room — an ORCHESTRATED multi-agent desk with an adversarial
debate round.

    Chief Analyst (orchestrator)
        │  reads the question, writes a plan, picks specialists + tickers
        ├── Quant Analyst        (deterministic maths -> LLM interpretation)
        ├── Fundamental Researcher
        ├── News & Sentiment Analyst      ← run in PARALLEL per ticker
        └── Risk Officer
    Debate:  Bull argues → Bear argues AND rebuts the Bull → Judge scores
    Verdict: BUY/HOLD/SELL + confidence -> human approval gate
    Approved verdicts land in the track record (verdict_log) and get graded.

Unlike agent_multi.py (a fixed linear pipeline), the Chief Analyst decides
per-question WHICH specialists to deploy and on WHICH tickers — dynamic
routing, capped and validated so it can't run away.
"""

import asyncio
import json
import os
import re
from typing import TypedDict, Optional

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command
import groq_pool

import market
import quant
import guardrails as gr
from graph_stream import astream_updates, interrupt_payload, has_pending_interrupt

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

MODEL = "openai/gpt-oss-120b"
_llm = groq_pool.create_llm(MODEL, temperature=0.3)

MAX_TICKERS = 2               # hard cap on fan-out
SPECIALISTS = ("quant", "fundamental", "news", "risk")
_TIMEOUT = 240                # whole war-room run, seconds


def _ask(role: str, content: str) -> str:
    return _llm.invoke([HumanMessage(content=f"{role}\n\n{content}")]).content.strip()


def _json(raw: str) -> dict:
    try:
        return json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
# Chief Analyst — dynamic plan
# --------------------------------------------------------------------------- #
def _plan(question: str, default_ticker: str) -> dict:
    raw = _ask(
        "You are the CHIEF ANALYST of an equity research desk. Read the question and "
        "write a research plan. Reply ONLY as JSON:\n"
        '{"tickers":["NSE symbols, max 2, no .NS suffix"],'
        '"specialists":["subset of: quant, fundamental, news, risk"],'
        '"focus":"one sentence: what the research must answer"}\n'
        "Pick ONLY the specialists the question actually needs (e.g. a pure valuation "
        "question needs fundamental, not news). Use the default ticker if the question "
        "names no stock.",
        f"DEFAULT TICKER: {default_ticker or 'none'}\nQUESTION: {question}",
    )
    obj = _json(raw)
    tickers = []
    for t in (obj.get("tickers") or [])[:MAX_TICKERS]:
        t = re.sub(r"\.(NS|BO)$", "", str(t).strip().upper())
        if re.match(r"^[A-Z0-9&\-]{1,20}$", t):
            tickers.append(t)
    if not tickers and default_ticker:
        tickers = [default_ticker.upper()]
    specs = [s for s in (obj.get("specialists") or []) if s in SPECIALISTS]
    if not specs:
        specs = list(SPECIALISTS)
    return {"tickers": tickers, "specialists": specs,
            "focus": obj.get("focus", question)[:300]}


# --------------------------------------------------------------------------- #
# Specialists — each grounded in data fetched for its ticker
# --------------------------------------------------------------------------- #
def _spec_quant(t: str) -> str:
    m = quant.metrics(t)
    return _ask(
        "You are the QUANT ANALYST. The metrics below were COMPUTED from real price "
        "history — interpret them, never recompute or invent. 3-4 short bullets: "
        "volatility/risk profile, risk-adjusted return (Sharpe), beta context, "
        "momentum (RSI + trend signal). Cite the figures.",
        json.dumps(m, default=str),
    ) + f"\n\n_Computed: vol {m['annualised_volatility_pct']}%, Sharpe {m['sharpe_ratio']}, " \
        f"beta {m['beta_vs_nifty50']}, RSI {m['rsi_14']}, max drawdown {m['max_drawdown_pct']}%_"


def _spec_fundamental(t: str) -> str:
    b = market.bundle(t)
    data = {"fundamentals": b.get("fundamentals"), "valuation": market.valuation(t),
            "quarterly_last4": (market.quarterly(t, n=4) or "n/a")}
    return _ask(
        "You are the FUNDAMENTAL RESEARCHER. From ONLY this data: 3-4 bullets on "
        "valuation, profitability, growth trajectory and balance-sheet quality. "
        "Cite figures; ₹ for money.",
        json.dumps(data, default=str),
    )


def _spec_news(t: str) -> str:
    items = market.news(t)
    if not items:
        return "No recent news available for this stock."
    heads = "\n".join(f"- {n['headline']}" for n in items if n.get("headline"))
    return _ask(
        "You are the NEWS & SENTIMENT ANALYST. Classify overall sentiment "
        "(Positive/Negative/Mixed) and explain in 2-3 bullets what the news flow "
        "means for the stock near-term. Start with the label.",
        f"Headlines for {t}:\n{heads}",
    )


def _spec_risk(t: str) -> str:
    b = market.bundle(t)
    data = {"fundamentals": b.get("fundamentals"), "week52": b.get("week52"),
            "change_6m_pct": b["price"]["change_pct"],
            "news": [n.get("headline") for n in b.get("news", []) if n.get("headline")]}
    return _ask(
        "You are the RISK OFFICER. List the 3 biggest downside risks as short bullets, "
        "each tied to the data. Rank by severity.",
        json.dumps(data, default=str),
    )


_SPEC_FN = {"quant": _spec_quant, "fundamental": _spec_fundamental,
            "news": _spec_news, "risk": _spec_risk}
_SPEC_LABEL = {"quant": "Quant Analyst", "fundamental": "Fundamental Researcher",
               "news": "News & Sentiment", "risk": "Risk Officer"}


def _run_spec(spec: str, ticker: str) -> dict:
    try:
        text = _SPEC_FN[spec](ticker)
        text = gr.enforce_compliance(text, semantic=False, disclaimer=False)
        return {"specialist": spec, "label": _SPEC_LABEL[spec], "ticker": ticker, "text": text}
    except Exception as e:
        return {"specialist": spec, "label": _SPEC_LABEL[spec], "ticker": ticker,
                "text": f"No data available ({e})."}


# --------------------------------------------------------------------------- #
# Debate — Bull vs Bear, then the Judge
# --------------------------------------------------------------------------- #
def _findings_block(findings: list[dict]) -> str:
    return "\n\n".join(f"[{f['label']} — {f['ticker']}]\n{f['text']}" for f in findings)


def _bull(question: str, findings: str) -> str:
    return _ask(
        "You are the BULL advocate in a research debate. Using ONLY the specialist "
        "findings, make the STRONGEST honest case FOR the stock(s) in 3-4 punchy "
        "bullets. Cite figures. No fabrication — if the findings are weak, say what "
        "the best available case is.",
        f"QUESTION: {question}\n\nFINDINGS:\n{findings}",
    )


def _bear(question: str, findings: str, bull_case: str) -> str:
    return _ask(
        "You are the BEAR advocate in a research debate. Using ONLY the specialist "
        "findings: (1) make the strongest honest case AGAINST in 3-4 bullets, "
        "(2) then directly REBUT the Bull's two strongest points. Cite figures.",
        f"QUESTION: {question}\n\nFINDINGS:\n{findings}\n\nBULL'S CASE:\n{bull_case}",
    )


def _judge(question: str, findings: str, bull_case: str, bear_case: str,
           feedback: str = "") -> dict:
    fb = f"\n\nReviewer feedback to address: {feedback}" if feedback else ""
    raw = _ask(
        "You are the JUDGE of this research debate. Score both cases strictly on "
        "grounding and strength, then rule. Reply ONLY as JSON:\n"
        '{"verdict":"BUY|HOLD|SELL","confidence_pct":55-95,'
        '"bull_score":1-10,"bear_score":1-10,'
        '"reasoning":"2-3 sentences: who argued better and the decisive evidence",'
        '"action":"one concrete next step"}' + fb,
        f"QUESTION: {question}\n\nFINDINGS:\n{findings}\n\n"
        f"BULL:\n{bull_case}\n\nBEAR:\n{bear_case}",
    )
    obj = _json(raw)
    verdict = obj.get("verdict", "HOLD")
    if verdict not in ("BUY", "HOLD", "SELL"):
        verdict = "HOLD"
    try:
        conf = max(50, min(95, int(obj.get("confidence_pct", 60))))
    except Exception:
        conf = 60
    return {"verdict": verdict, "confidence_pct": conf,
            "bull_score": obj.get("bull_score"), "bear_score": obj.get("bear_score"),
            "reasoning": gr.enforce_compliance(str(obj.get("reasoning", raw[:300])),
                                               semantic=False, disclaimer=False),
            "action": gr.enforce_compliance(str(obj.get("action", "Flag for review")),
                                            semantic=False, disclaimer=False)}


# --------------------------------------------------------------------------- #
# Debate graph — LangGraph-native HITL. The specialist fan-out streams live
# BEFORE the graph (parallel UX); bull → bear → judge → interrupt gate →
# finalize all run inside one checkpointed StateGraph. Revise loops the judge.
# --------------------------------------------------------------------------- #
class WarState(TypedDict):
    question: str
    tickers: list
    findings: str
    bull: Optional[str]
    bear: Optional[str]
    verdict: Optional[dict]
    feedback: Optional[str]
    decision: Optional[str]
    outcome: Optional[str]


def _node_bull(state: WarState):
    bull = gr.enforce_compliance(_bull(state["question"], state["findings"]),
                                 semantic=False, disclaimer=False)
    return {"bull": bull}


def _node_bear(state: WarState):
    bear = gr.enforce_compliance(_bear(state["question"], state["findings"], state["bull"]),
                                 semantic=False, disclaimer=False)
    return {"bear": bear}


def _node_judge(state: WarState):
    v = _judge(state["question"], state["findings"], state["bull"], state["bear"],
               state.get("feedback") or "")
    return {"verdict": v, "feedback": None}


def _gate(state: WarState):
    v = state["verdict"]
    decision = interrupt({
        "recommendation": f"{v['verdict']} ({v['confidence_pct']}% confidence) — {v['reasoning']}",
        "action": v["action"], "verdict": v,
    })
    return {"decision": str(decision or "").strip()}


def _route(state: WarState) -> str:
    return "finalize" if state.get("decision") in ("approve", "reject") else "rejudge_prep"


def _rejudge_prep(state: WarState):
    return {"feedback": state.get("decision"), "decision": None}


def _finalize(state: WarState):
    v = state["verdict"]
    if state.get("decision") == "approve":
        try:
            import verdict_log
            for t in state["tickers"]:
                verdict_log.log_verdict(t, v["verdict"],
                                        market.quote(t).get("price"), source="war_room")
        except Exception:
            pass
        report = (f"# War-room verdict — approved\n\n"
                  f"**{v['verdict']}** · confidence {v['confidence_pct']}% · "
                  f"bull {v.get('bull_score')}/10 vs bear {v.get('bear_score')}/10\n\n"
                  f"{v['reasoning']}\n\n**Next step:** {v['action']}\n\n"
                  f"**Bull case**\n{state['bull']}\n\n**Bear case**\n{state['bear']}")
        return {"outcome": gr.enforce_compliance(report)}
    return {"outcome": gr.append_disclaimer("Verdict REJECTED by reviewer. No call recorded.")}


def _build():
    g = StateGraph(WarState)
    for name, fn in [("bull_advocate", _node_bull), ("bear_advocate", _node_bear),
                     ("judge", _node_judge), ("gate", _gate),
                     ("rejudge_prep", _rejudge_prep), ("finalize", _finalize)]:
        g.add_node(name, fn)
    g.add_edge(START, "bull_advocate")
    g.add_edge("bull_advocate", "bear_advocate")
    g.add_edge("bear_advocate", "judge")
    g.add_edge("judge", "gate")
    g.add_conditional_edges("gate", _route, {"finalize": "finalize", "rejudge_prep": "rejudge_prep"})
    g.add_edge("rejudge_prep", "judge")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=MemorySaver())


GRAPH = _build()


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _events_from_update(update: dict, thread_id: str):
    payload = interrupt_payload(update)
    if payload is not None:
        yield {"type": "verdict", **payload.get("verdict", {})}
        yield {"type": "approval_request", "recommendation": payload.get("recommendation", ""),
               "action": payload.get("action", ""), "thread_id": thread_id}
        return
    for node, delta in update.items():
        delta = delta or {}
        if node == "bull_advocate":
            yield {"type": "debate", "side": "Bull", "text": delta.get("bull", "")}
        elif node == "bear_advocate":
            yield {"type": "debate", "side": "Bear", "text": delta.get("bear", "")}
        elif node == "finalize":
            yield {"type": "final", "text": delta.get("outcome", "")}


# --------------------------------------------------------------------------- #
# Public streaming API
# --------------------------------------------------------------------------- #
async def start(question: str, default_ticker: str, thread_id: str):
    _t0 = asyncio.get_event_loop().time()

    plan = await asyncio.to_thread(_plan, question, default_ticker)
    if not plan["tickers"]:
        yield {"type": "error", "text": "Couldn't identify a stock — pick a ticker or name one in the question."}
        return
    yield {"type": "plan", "tickers": plan["tickers"], "specialists": plan["specialists"],
           "focus": plan["focus"],
           "text": (f"Deploying {len(plan['specialists'])} specialist(s) on "
                    f"{', '.join(plan['tickers'])} — {plan['focus']}")}

    # Fan-out: every (specialist, ticker) pair in parallel
    jobs = [(s, t) for t in plan["tickers"] for s in plan["specialists"]]
    tasks = [asyncio.create_task(asyncio.to_thread(_run_spec, s, t)) for s, t in jobs]
    findings = []
    for coro in asyncio.as_completed(tasks):
        f = await coro
        findings.append(f)
        yield {"type": "specialist", **f}
        if asyncio.get_event_loop().time() - _t0 > _TIMEOUT:
            for tk in tasks:
                tk.cancel()
            yield {"type": "error", "text": "War room timed out. Try a narrower question."}
            return

    yield {"type": "phase", "text": "Specialists done — opening the debate."}
    init: WarState = {"question": question, "tickers": plan["tickers"],
                      "findings": _findings_block(findings), "bull": None, "bear": None,
                      "verdict": None, "feedback": None, "decision": None, "outcome": None}
    try:
        async for update in astream_updates(GRAPH, init, _config(thread_id), timeout=_TIMEOUT):
            for ev in _events_from_update(update, thread_id):
                yield ev
    except asyncio.TimeoutError:
        yield {"type": "error", "text": "War room timed out. Try a narrower question."}
    except Exception as e:
        yield {"type": "error", "text": str(e)}


async def resume(thread_id: str, decision: str):
    cfg = _config(thread_id)
    if not await has_pending_interrupt(GRAPH, cfg):
        yield {"type": "error", "text": "Session expired. Run the war room again."}
        return
    try:
        async for update in astream_updates(GRAPH, Command(resume=decision), cfg, timeout=_TIMEOUT):
            for ev in _events_from_update(update, thread_id):
                yield ev
    except asyncio.TimeoutError:
        yield {"type": "error", "text": "Resume timed out. Try again."}
    except Exception as e:
        yield {"type": "error", "text": str(e)}
