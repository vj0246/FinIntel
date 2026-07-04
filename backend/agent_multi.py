"""
agent_multi.py
--------------
Multi-agent research desk with human-in-the-loop (HITL).

Pipeline (LangGraph StateGraph):

    START → gather → researcher → risk_check → synthesize → END

After synthesize the graph ends naturally. The HITL pause is managed
explicitly via a _pending dict — more reliable than LangGraph interrupt()
across Python versions and platforms, and easier to explain on stage.

Flow:
  1. start_run()  — streams all agents, stores proposal in _pending, yields approval_request
  2. Human sees approval card (approve / reject / revise)
  3. resume_run() — reads _pending, routes to final outcome; revise re-runs synthesize

Three teaching points:
  - Multi-agent: each node is a focused LLM with its own role prompt
  - HITL: agent proposes, human signs off, then it acts
  - LangSmith: set env vars, every node + LLM call is traced automatically
"""

import asyncio
import json
import os
from typing import TypedDict, Optional

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END
import groq_pool

import market
import guardrails as gr

# Load backend/.env so LangSmith vars are present (GROQ keys are loaded by groq_pool).
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

MODEL = "llama-3.3-70b-versatile"
_llm = groq_pool.create_llm(MODEL, temperature=0.3)

# Stores proposals waiting for human sign-off  {thread_id: {recommendation, action, state}}
_pending: dict = {}


# --------------------------------------------------------------------------- #
# Shared state
# --------------------------------------------------------------------------- #
class DeskState(TypedDict):
    ticker: str
    data: Optional[dict]
    research: Optional[str]
    risk: Optional[str]
    recommendation: Optional[str]
    action: Optional[str]
    feedback: Optional[str]
    reflection: Optional[str]   # note from the self-correction pass (for the event stream)


def _ask(role: str, content: str) -> str:
    return _llm.invoke([HumanMessage(content=f"{role}\n\n{content}")]).content.strip()


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #
def gather(state: DeskState):
    b = market.bundle(state["ticker"].upper())
    return {"data": {"price": b["price"], "fundamentals": b["fundamentals"], "news": b["news"]}}


def researcher(state: DeskState):
    out = _ask(
        "You are an equity RESEARCHER. In 2-3 short bullet lines, list the key "
        "bullish and bearish signals. Be specific with numbers. No verdict yet.",
        json.dumps(state["data"], default=str),
    )
    return {"research": out}


def risk_check(state: DeskState):
    out = _ask(
        "You are a RISK officer. Given the data and the researcher's notes, name "
        "the single biggest downside risk in one or two sentences.",
        f"DATA:\n{json.dumps(state['data'], default=str)}\n\nRESEARCH:\n{state['research']}",
    )
    return {"risk": out}


def synthesize(state: DeskState):
    revise = f"\n\nReviewer feedback to address: {state['feedback']}" if state.get("feedback") else ""
    raw = _ask(
        "You are the SYNTHESISER. Combine research and risk into a decision. "
        "Reply ONLY as JSON: {\"verdict\":\"BUY|HOLD|SELL\", \"thesis\":\"2-3 sentences\", "
        "\"action\":\"one concrete next step e.g. Add to watchlist or Flag for review\"}." + revise,
        f"RESEARCH:\n{state['research']}\n\nRISK:\n{state['risk']}",
    )
    try:
        obj = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except Exception:
        obj = {"verdict": "HOLD", "thesis": raw[:300], "action": "Flag for analyst review"}
    rec = f"{obj.get('verdict', 'HOLD')} — {obj.get('thesis', '').strip()}"
    return {"recommendation": rec, "action": obj.get("action", "Flag for analyst review"), "feedback": None}


def reflect(state: DeskState):
    """Self-correction pass: a critic reviews the draft verdict against the
    research and risk notes; if it flags issues, ONE revision fixes them.
    Costs 1-2 extra LLM calls per run; disable with SELF_REFLECT=0."""
    if os.environ.get("SELF_REFLECT", "1") == "0":
        return {"reflection": "Self-check skipped (disabled)."}
    try:
        raw = _ask(
            "You are a strict REVIEWER. Check the draft verdict below:\n"
            "1. Is the verdict consistent with the research and the stated risk?\n"
            "2. Is the thesis grounded in those notes (no invented facts)?\n"
            "3. Is it compliant — no guaranteed-return promises or directive personal advice "
            "('you should buy'); an analytic BUY/HOLD/SELL opinion is fine?\n"
            "4. Is the proposed action concrete?\n"
            'Reply ONLY as JSON: {"verdict":"PASS" or "REVISE", "issues":"specific problems, or empty"}',
            f"RESEARCH:\n{state['research']}\n\nRISK:\n{state['risk']}\n\n"
            f"DRAFT:\n{state['recommendation']}\nProposed action: {state['action']}",
        )
        obj = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        if obj.get("verdict", "PASS").upper() != "REVISE" or not obj.get("issues"):
            return {"reflection": "Self-check passed — verdict is consistent, grounded and compliant."}
        # One corrective synthesis pass with the reviewer's issues as feedback
        fixed = synthesize({**state, "feedback": f"Reviewer issues to fix: {obj['issues']}"})
        return {**fixed, "reflection": f"Self-check flagged issues and revised the draft: {obj['issues']}"}
    except Exception:
        return {"reflection": "Self-check unavailable — keeping the draft."}


# --------------------------------------------------------------------------- #
# Graph — runs through synthesize then ends. HITL handled outside the graph.
# --------------------------------------------------------------------------- #
def _build():
    g = StateGraph(DeskState)
    g.add_node("gather", gather)
    g.add_node("researcher", researcher)
    g.add_node("risk_check", risk_check)
    g.add_node("synthesize", synthesize)
    g.add_node("reflect", reflect)
    g.add_edge(START, "gather")
    g.add_edge("gather", "researcher")
    g.add_edge("researcher", "risk_check")
    g.add_edge("risk_check", "synthesize")
    g.add_edge("synthesize", "reflect")
    g.add_edge("reflect", END)
    return g.compile()


GRAPH = _build()


# --------------------------------------------------------------------------- #
# Streaming helpers
# --------------------------------------------------------------------------- #
def _events_from_update(update: dict):
    for node, delta in update.items():
        if node == "gather":
            yield {"type": "agent", "name": "Researcher", "text": "Pulled price, fundamentals and news."}
        elif node == "researcher":
            yield {"type": "agent", "name": "Researcher", "text": delta.get("research", "")}
        elif node == "risk_check":
            yield {"type": "agent", "name": "Risk", "text": delta.get("risk", "")}
        elif node == "synthesize":
            yield {"type": "agent", "name": "Synthesiser",
                   "text": f"Draft: {delta.get('recommendation', '')}\nProposed action: {delta.get('action', '')}"}
        elif node == "reflect":
            text = delta.get("reflection", "")
            if delta.get("recommendation"):    # the self-check revised the draft
                text += f"\nRevised: {delta['recommendation']}\nProposed action: {delta.get('action', '')}"
            yield {"type": "agent", "name": "Reflection", "text": text}


# --------------------------------------------------------------------------- #
# Public API used by app_multi.py
# --------------------------------------------------------------------------- #
async def start_run(ticker: str, thread_id: str):
    """Run agents, store proposal, emit approval_request at the end."""
    collected = {"ticker": ticker, "data": None, "research": "", "risk": "", "recommendation": "", "action": ""}
    _start = asyncio.get_event_loop().time()
    _TIMEOUT = 90  # seconds — hard cap on full graph execution

    async for update in GRAPH.astream({"ticker": ticker}, stream_mode="updates"):
        # Timeout guard
        if asyncio.get_event_loop().time() - _start > _TIMEOUT:
            yield {"type": "error", "text": "Analysis timed out. Try again or pick a different stock."}
            return
        for ev in _events_from_update(update):
            yield ev
        for node in ("gather", "researcher", "risk_check", "synthesize", "reflect"):
            if node in update:
                collected.update({k: v for k, v in update[node].items() if v is not None})

    # Compliance screen on the recommendation (regex layer; the reflect node already
    # did the semantic pass). Disclaimer goes on the FINAL outcome, not the draft card.
    collected["recommendation"] = gr.enforce_compliance(
        collected.get("recommendation", ""), semantic=False, disclaimer=False)
    _pending[thread_id] = collected

    yield {
        "type": "approval_request",
        "recommendation": collected["recommendation"],
        "action": collected["action"],
        "thread_id": thread_id,
    }


async def resume_run(thread_id: str, decision: str):
    """Resume after human decision. Revise re-runs synthesize with feedback."""
    pending = _pending.pop(thread_id, {})
    rec = pending.get("recommendation", "Unknown")
    action = pending.get("action", "Unknown")

    if decision == "approve":
        # Track record: log the approved call at today's price so it can be scored later
        try:
            import verdict_log
            price = ((pending.get("data") or {}).get("price") or {}).get("end")
            verdict_log.log_verdict(pending.get("ticker", ""),
                                    verdict_log.extract_verdict(rec), price, source="desk")
        except Exception:
            pass
        yield {"type": "final",
               "text": gr.append_disclaimer(f"APPROVED AND EXECUTED\n\nAction taken: {action}\n\n{rec}")}

    elif decision == "reject":
        yield {"type": "final",
               "text": "REJECTED by reviewer. No action taken."}

    else:
        # revise — re-run synthesize with feedback, then pause again
        feedback = decision
        revised = {"recommendation": "", "action": ""}
        revise_state = {
            "ticker": pending.get("ticker", ""),
            "data": pending.get("data"),
            "research": pending.get("research", ""),
            "risk": pending.get("risk", ""),
            "feedback": feedback,
            "recommendation": None,
            "action": None,
            "reflection": None,
        }
        async for update in GRAPH.astream(revise_state, stream_mode="updates"):
            for ev in _events_from_update(update):
                yield ev
            for node in ("synthesize", "reflect"):   # reflect may revise the draft again
                if node in update and update[node].get("recommendation"):
                    revised["recommendation"] = update[node]["recommendation"]
                    revised["action"] = update[node].get("action", "")
        revised["recommendation"] = gr.enforce_compliance(
            revised["recommendation"], semantic=False, disclaimer=False)
        # store updated pending (keep prev data/research/risk for further revisions)
        _pending[thread_id] = {**pending, **revised}
        yield {
            "type": "approval_request",
            "recommendation": revised["recommendation"],
            "action": revised["action"],
            "thread_id": thread_id,
        }
