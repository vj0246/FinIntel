"""
agent_multi.py
--------------
Multi-agent research desk with LangGraph-NATIVE human-in-the-loop.

Pipeline (one checkpointed StateGraph):

    START → gather → researcher → risk_check → synthesize → reflect → gate
                                        ▲                              │ interrupt()
                                        └────────── revise_prep ◄──────┤ (revise)
                                                                       ▼
                                                                   finalize → END

The `gate` node calls LangGraph's `interrupt()` — the graph checkpoints and
pauses itself; the approval card the human sees IS the interrupt payload.
The /resume endpoint resumes the SAME graph with `Command(resume=decision)`:
approve/reject route to `finalize`, anything else is treated as reviewer
feedback and loops back through `synthesize`.

State lives in the graph's MemorySaver checkpointer keyed by thread_id —
no hand-rolled pending dicts.
"""

import asyncio
import json
import os
from typing import TypedDict, Optional

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command
import groq_pool

import market
import guardrails as gr
from graph_stream import astream_updates, interrupt_payload, has_pending_interrupt

# Load backend/.env so LangSmith vars are present (GROQ keys are loaded by groq_pool).
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

MODEL = "llama-3.3-70b-versatile"
_llm = groq_pool.create_llm(MODEL, temperature=0.3)


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
    decision: Optional[str]     # human decision captured by the interrupt gate
    outcome: Optional[str]      # final report text


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


def gate(state: DeskState):
    """LangGraph-native HITL: compliance-screen the draft, then interrupt().
    The graph checkpoints here; Command(resume=<decision>) continues it.
    (This node re-runs from the top on resume — the regex screen is cheap
    and idempotent, so that's fine.)"""
    rec = gr.enforce_compliance(state.get("recommendation") or "", semantic=False, disclaimer=False)
    decision = interrupt({"recommendation": rec, "action": state.get("action") or ""})
    return {"decision": str(decision or "").strip(), "recommendation": rec}


def route_decision(state: DeskState) -> str:
    return "finalize" if state.get("decision") in ("approve", "reject") else "revise_prep"


def revise_prep(state: DeskState):
    """Anything that isn't approve/reject is reviewer feedback for a re-synthesis."""
    return {"feedback": state.get("decision"), "decision": None}


def finalize(state: DeskState):
    rec, action = state.get("recommendation", ""), state.get("action", "")
    if state.get("decision") == "approve":
        # Track record: log the approved call at today's price so it can be scored later
        try:
            import verdict_log
            price = ((state.get("data") or {}).get("price") or {}).get("end")
            verdict_log.log_verdict(state.get("ticker", ""),
                                    verdict_log.extract_verdict(rec), price, source="desk")
        except Exception:
            pass
        return {"outcome": gr.append_disclaimer(
            f"APPROVED AND EXECUTED\n\nAction taken: {action}\n\n{rec}")}
    return {"outcome": "REJECTED by reviewer. No action taken."}


# --------------------------------------------------------------------------- #
# Graph — checkpointed; the interrupt IS the human gate
# --------------------------------------------------------------------------- #
def _build():
    g = StateGraph(DeskState)
    for name, fn in [("gather", gather), ("researcher", researcher), ("risk_check", risk_check),
                     ("synthesize", synthesize), ("reflect", reflect), ("gate", gate),
                     ("revise_prep", revise_prep), ("finalize", finalize)]:
        g.add_node(name, fn)
    g.add_edge(START, "gather")
    g.add_edge("gather", "researcher")
    g.add_edge("researcher", "risk_check")
    g.add_edge("risk_check", "synthesize")
    g.add_edge("synthesize", "reflect")
    g.add_edge("reflect", "gate")
    g.add_conditional_edges("gate", route_decision, {"finalize": "finalize", "revise_prep": "revise_prep"})
    g.add_edge("revise_prep", "synthesize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=MemorySaver())


GRAPH = _build()


# --------------------------------------------------------------------------- #
# Streaming helpers
# --------------------------------------------------------------------------- #
def _events_from_update(update: dict, thread_id: str):
    payload = interrupt_payload(update)
    if payload is not None:
        yield {"type": "approval_request", "recommendation": payload.get("recommendation", ""),
               "action": payload.get("action", ""), "thread_id": thread_id}
        return
    for node, delta in update.items():
        delta = delta or {}
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
        elif node == "finalize":
            yield {"type": "final", "text": delta.get("outcome", "")}


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


# --------------------------------------------------------------------------- #
# Public API used by app_multi.py
# --------------------------------------------------------------------------- #
async def start_run(ticker: str, thread_id: str):
    """Run the graph until its interrupt() gate emits the approval card."""
    _start = asyncio.get_event_loop().time()
    _TIMEOUT = 120
    try:
        async for update in astream_updates(GRAPH, {"ticker": ticker}, _config(thread_id),
                                            timeout=_TIMEOUT):
            if asyncio.get_event_loop().time() - _start > _TIMEOUT:
                yield {"type": "error", "text": "Analysis timed out. Try again or pick a different stock."}
                return
            for ev in _events_from_update(update, thread_id):
                yield ev
    except asyncio.TimeoutError:
        yield {"type": "error", "text": "Analysis timed out. Try again or pick a different stock."}
    except Exception as e:
        yield {"type": "error", "text": str(e)}


async def resume_run(thread_id: str, decision: str):
    """Resume the checkpointed graph with the human decision via Command(resume=...)."""
    cfg = _config(thread_id)
    if not await has_pending_interrupt(GRAPH, cfg):
        yield {"type": "error", "text": "Session expired. Run the analysis again."}
        return
    try:
        async for update in astream_updates(GRAPH, Command(resume=decision), cfg, timeout=120):
            for ev in _events_from_update(update, thread_id):
                yield ev
    except asyncio.TimeoutError:
        yield {"type": "error", "text": "Resume timed out. Try again."}
    except Exception as e:
        yield {"type": "error", "text": str(e)}
