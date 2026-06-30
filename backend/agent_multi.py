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
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END

import market
import guardrails as gr

# Load backend/.env so GROQ_API_KEY (and optional LangSmith vars) are present before
# the Groq client is built below. In prod (Render) the vars are set in the real
# environment and the missing .env is a harmless no-op.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

MODEL = "llama-3.3-70b-versatile"
_llm = ChatGroq(model=MODEL, temperature=0.3, api_key=os.environ.get("GROQ_API_KEY", ""))

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


# --------------------------------------------------------------------------- #
# Graph — runs through synthesize then ends. HITL handled outside the graph.
# --------------------------------------------------------------------------- #
def _build():
    g = StateGraph(DeskState)
    g.add_node("gather", gather)
    g.add_node("researcher", researcher)
    g.add_node("risk_check", risk_check)
    g.add_node("synthesize", synthesize)
    g.add_edge(START, "gather")
    g.add_edge("gather", "researcher")
    g.add_edge("researcher", "risk_check")
    g.add_edge("risk_check", "synthesize")
    g.add_edge("synthesize", END)
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
        for node in ("gather", "researcher", "risk_check", "synthesize"):
            if node in update:
                collected.update({k: v for k, v in update[node].items() if v is not None})

    # Sanitise the synthesised recommendation
    collected["recommendation"] = gr.sanitise_output(collected.get("recommendation", ""))
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
        yield {"type": "final",
               "text": f"APPROVED AND EXECUTED\n\nAction taken: {action}\n\n{rec}"}

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
        }
        async for update in GRAPH.astream(revise_state, stream_mode="updates"):
            for ev in _events_from_update(update):
                yield ev
            if "synthesize" in update:
                revised["recommendation"] = update["synthesize"].get("recommendation", "")
                revised["action"] = update["synthesize"].get("action", "")
        # store updated pending (keep prev data/research/risk for further revisions)
        _pending[thread_id] = {**pending, **revised}
        yield {
            "type": "approval_request",
            "recommendation": revised["recommendation"],
            "action": revised["action"],
            "thread_id": thread_id,
        }
