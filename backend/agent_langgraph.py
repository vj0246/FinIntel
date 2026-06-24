"""
agent_langgraph.py
------------------
Same agent as agent.py — but built as a LangGraph state graph instead of a
hand-written while loop. Drop-in: exposes the same async run_agent(ticker)
yielding the same event dicts, so app.py streams it with zero changes.

Raw loop (agent.py):   YOU write the loop.
LangGraph (this file): you declare NODES and EDGES; the graph runs the loop.

    START → agent ──(needs tool?)──► tools ──┐
              ▲                               │
              └───────────────────────────────┘
              └──(no tool?)──► END

Same idea, less plumbing, plus retries/state/checkpoints for free later.
"""

import json
import os

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition

from tools import _load  # reuse the same mocked-data loader

MODEL = "llama-3.3-70b-versatile"

# Same LLM used inside the generative tool.
_summarizer = ChatGroq(model=MODEL, temperature=0.4, api_key=os.environ.get("GROQ_API_KEY", ""))


# --------------------------------------------------------------------------- #
# Tools — identical behaviour to tools.py, now as LangChain @tool functions.
# The docstring IS the description the model sees; the type hints ARE the schema.
# --------------------------------------------------------------------------- #
@tool
def get_price_history(ticker: str) -> dict:
    """Get 30-day price action for an NSE stock (RELIANCE, TCS, INFY)."""
    return _load(ticker)["price_history"]


@tool
def get_news(ticker: str) -> list:
    """Get the latest news headlines for an NSE stock."""
    return _load(ticker)["news"]


@tool
def get_fundamentals(ticker: str) -> dict:
    """Get valuation and financial-health metrics for an NSE stock."""
    return _load(ticker)["fundamentals"]


@tool
def generate_summary(ticker: str, findings: str) -> str:
    """Write the final investment thesis from gathered findings (the generative tool)."""
    prompt = (
        f"You are an equity analyst. Using only these findings about {ticker}, "
        f"write a 3-4 sentence investment thesis in plain English. Be balanced, "
        f"mention one risk.\n\nFINDINGS:\n{findings}"
    )
    return _summarizer.invoke([HumanMessage(content=prompt)]).content


TOOLS = [get_price_history, get_news, get_fundamentals, generate_summary]

SYSTEM_PROMPT = """You are an autonomous equity research agent for Indian (NSE) stocks.
Decide BUY / HOLD / SELL for a long-term investor.
1. Gather evidence: call get_price_history, get_fundamentals and get_news.
2. Reason about momentum, valuation, news sentiment.
3. Call generate_summary once, passing a 'findings' note you write yourself.
4. Reply with a one-word verdict (BUY/HOLD/SELL) on its own first line, then the thesis.
Think step by step. Keep moving toward a verdict."""


# --------------------------------------------------------------------------- #
# The graph. Two nodes, one decision. This replaces the whole while loop.
# --------------------------------------------------------------------------- #
def _build_graph():
    llm = ChatGroq(model=MODEL, temperature=0.3,
                   api_key=os.environ.get("GROQ_API_KEY", "")).bind_tools(TOOLS)

    def agent_node(state: MessagesState):
        """The 'think' node: ask the model what to do next."""
        return {"messages": [llm.invoke(state["messages"])]}

    g = StateGraph(MessagesState)
    g.add_node("agent", agent_node)
    g.add_node("tools", ToolNode(TOOLS))      # prebuilt: runs whatever tools the model asked for
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", tools_condition)  # tool calls? → "tools", else → END
    g.add_edge("tools", "agent")              # after tools, think again. That's the loop.
    return g.compile()


GRAPH = _build_graph()


# --------------------------------------------------------------------------- #
# Adapter: turn LangGraph's stream into the SAME events app.py already expects.
# --------------------------------------------------------------------------- #
async def run_agent(ticker: str):
    init = {"messages": [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Analyse {ticker.upper()} and give me a verdict."),
    ]}

    # stream_mode="updates" yields {node_name: {messages: [...]}} after each node runs.
    async for update in GRAPH.astream(init, stream_mode="updates"):
        for node, payload in update.items():
            for msg in payload["messages"]:
                if isinstance(msg, AIMessage):
                    if msg.content:
                        yield {"type": "plan", "text": msg.content}
                    for tc in msg.tool_calls or []:
                        yield {"type": "tool_call", "name": tc["name"], "args": tc["args"]}
                    # an AIMessage with no tool calls = final answer
                    if not msg.tool_calls and msg.content:
                        yield {"type": "final", "text": msg.content}
                elif isinstance(msg, ToolMessage):
                    try:
                        result = json.loads(msg.content)
                    except Exception:
                        result = msg.content
                    yield {"type": "tool_result", "name": msg.name, "result": result}


# To use this instead of the raw loop, in app.py change the import to:
#   from agent_langgraph import run_agent
