"""
agent_task.py
-------------
A task-driven analyst agent with STEP-BY-STEP human-in-the-loop.

You give it a stock + a task. Then, for every move:

    agent proposes ONE next step  ->  you Approve / Redirect / Stop  ->  it runs it
                                          ↑                                  │
                                          └──────────── repeat ◄─────────────┘
                                                  until you finalise

Nothing happens without your approval. The agent only ever proposes the *next*
step; you stay in control the whole way. Answers are grounded in fetched data,
not invented — if data can't be fetched, it says so and keeps going.

HITL is LangGraph-native: each step pauses at an interrupt() gate inside a
checkpointed StateGraph and resumes with Command(resume=<decision>).
"""

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

# Groq-hosted model with automatic key rotation.
# Set GROQ_API_KEY=key1,key2,key3 for failover across multiple keys.
MODEL = "openai/gpt-oss-120b"
_llm = groq_pool.create_llm(MODEL, temperature=0.3)

# Tools the agent may propose. Keep names human-readable for the approval card.
# Raw-data tools fetch numbers; analysis tools interpret them (grounded, never invented).
TOOLS = {
    # quick facts
    "quote": "Get the latest share price (and the recent % move)",
    "fifty_two_week": "Get the 52-week high and low",
    "performance": "Summarise recent performance (change %, high, low)",
    "price_trend": "Look at the 6-month price trend (shows a chart)",
    # fundamentals & financials
    "fundamentals": "Pull raw valuation / financial-health metrics",
    "valuation": "A compact valuation snapshot (PE, PB, market cap, yield)",
    "fundamental_analysis": "Interpret the fundamentals: strengths, weaknesses, quality verdict",
    "quarterly_results": "Recent quarterly revenue, net profit, operating income & EPS",
    "balance_sheet": "Balance sheet: shareholders' equity, assets, liabilities, debt, cash",
    "key_stats": "Extended stats: beta, 50/200-day averages, growth, margins",
    "dividends": "Review the dividend history",
    "dividend_analysis": "Assess dividend quality: yield, growth, consistency",
    "stock_splits": "Review historical stock splits / corporate actions",
    # price / technicals
    "technical_analysis": "Read the trend & momentum vs moving averages and ranges (shows a chart)",
    "explain_move": "Explain the likely reason for the recent rise / downfall",
    # news & sentiment
    "news_sentiment": "Pull recent news and judge the market sentiment",
    "news_headlines": "List the recent news headlines (no analysis)",
    "news_summary": "Summarise what the recent news means for the stock",
    # research views
    "analyst_ratings": "Brokerage price targets and buy/hold/sell consensus",
    "risk_assessment": "List the key downside risks right now",
    "bull_bear_case": "Lay out the bull case vs the bear case",
    "verdict": "A grounded BUY / HOLD / SELL stance with reasons",
    # terminate
    "finish": "Stop gathering and write the final report for the task",
}

MAX_STEPS = 6   # hard cap so the approval loop ALWAYS terminates
MAX_REDIRECTS = 3  # prevent infinite redirect loops


def _llm_json(prompt: str) -> dict:
    raw = _llm.invoke([HumanMessage(content=prompt)]).content
    try:
        return json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
# Propose the next step
# --------------------------------------------------------------------------- #
def _propose(sess: dict, redirect: str = "") -> dict:
    done_tools = [c["tool"] for c in sess["context"]]
    tool_list = "\n".join(f"- {k}: {v}" for k, v in TOOLS.items() if k != "finish")
    ctx = "\n\n".join(f"[{c['tool']}] {c['result']}" for c in sess["context"]) or "nothing yet"

    # Redirect: the user has overridden the plan, so DON'T run the "is the task
    # already answered? -> finish" logic (that short-circuit used to silently swallow
    # the redirect). Pick the single tool that carries out their instruction, even if
    # a similar tool already ran. Only finish if they explicitly asked to stop.
    if redirect:
        prompt = (
            f"You are an equity analyst agent working on this TASK for {sess['ticker']} (NSE):\n"
            f"\"{sess['task']}\"\n\n"
            f"Tools available:\n{tool_list}\n\n"
            f"Steps already done: {done_tools or 'none'}\n"
            f"Findings so far:\n{ctx}\n\n"
            f"The user has REDIRECTED you with this instruction:\n\"{redirect}\"\n\n"
            "Honour it: choose the SINGLE tool that best carries out the user's instruction "
            "as the very next step — even if a similar tool already ran. Map their words to a "
            "tool, e.g. 'check fundamentals'->fundamental_analysis, 'look at the chart/"
            "technicals'->technical_analysis, 'what about the risks'->risk_assessment, "
            "'compare the results/quarters'->quarterly_results, 'is it worth buying'->verdict, "
            "'latest news'->news_sentiment. Choose 'finish' ONLY if the user explicitly asked "
            "you to stop or finalise.\n"
            'Reply ONLY as JSON: {"tool": "<tool name>", "summary": "one short sentence on what '
            'you will do next, acknowledging the redirect"}'
        )
        obj = _llm_json(prompt)
        tool = obj.get("tool", "")
        if tool not in TOOLS:
            tool = "finish"
        return {"tool": tool,
                "summary": obj.get("summary", f"Following your redirect: {redirect}.")}

    # Hard cap: once enough steps are gathered, always wrap up (loop can't run forever).
    if len(done_tools) >= MAX_STEPS:
        return {"tool": "finish",
                "summary": "I've gathered enough across several steps — approve to get the final report."}

    prompt = (
        f"You are an equity analyst agent working on this TASK for {sess['ticker']} (NSE):\n"
        f"\"{sess['task']}\"\n\n"
        f"Tools available:\n{tool_list}\n\n"
        f"Steps already done: {done_tools or 'none'}\n"
        f"Findings so far:\n{ctx}\n\n"
        "FIRST decide: do the findings so far ALREADY answer the task?\n"
        "- A simple/factual question is fully answered by ONE matching tool — once that "
        "tool has run, set done=true. (price->quote, 52-week->fifty_two_week, "
        "valuation/'is it cheap'->valuation or fundamental_analysis, dividends->dividends, "
        "splits->stock_splits, 'why did it move/fall'->explain_move, results->quarterly_results.)\n"
        "- Only keep going (done=false) for broad tasks that genuinely need several angles "
        "(full analysis, risk review, a buy/hold/sell verdict).\n"
        "If done=false, pick the SINGLE most useful NEXT tool — never one already done.\n"
        'Reply ONLY as JSON: {"done": true or false, "tool": "<tool name>", '
        '"summary": "one short sentence on what you will do and why"}'
    )
    obj = _llm_json(prompt)

    # Explicit completion signal -> finish.
    if obj.get("done") is True:
        return {"tool": "finish",
                "summary": obj.get("summary", "I have enough to answer — approve to get the report.")}

    tool = obj.get("tool", "finish")
    if tool not in TOOLS:
        tool = "finish"
    # Repeat-guard: re-proposing an already-finished tool means it's spinning (redirects
    # take the dedicated branch above, so here a repeat is always unintended).
    if tool != "finish" and tool in done_tools:
        return {"tool": "finish",
                "summary": "I've already covered that — approve to get the final report."}
    return {"tool": tool, "summary": obj.get("summary", "Proceed to the next step.")}


# --------------------------------------------------------------------------- #
# Execute one approved step (grounded in real data)
# --------------------------------------------------------------------------- #
def _interpret(instruction: str, data) -> str:
    """LLM analysis grounded ONLY in the real numbers we pass it."""
    return _llm.invoke([HumanMessage(content=(
        "You are an equity analyst for Indian (NSE) stocks. Use ONLY the data below — "
        "never invent numbers, dates or facts. All money is in Indian Rupees (₹); never "
        "use '$'. Be concise, specific, and cite the actual figures.\n\n"
        f"DATA:\n{json.dumps(data, default=str)}\n\nTASK: {instruction}"
    ))]).content


def _chart_payload(b: dict) -> dict:
    return {"ticker": b["ticker"], "series": b["chart"],
            "change_pct": b["price"]["change_pct"], "source": b.get("source", "sample")}


# --- readable formatting: turn metric dicts / quarter lists into markdown tables ---
_LABELS = {
    "pe": "P/E", "pb": "P/B", "sector_pe": "Sector P/E", "sector": "Sector",
    "industry": "Industry", "annual_volatility_pct": "Annual volatility",
    "delivery_pct": "Delivery %", "market_cap_cr": "Market cap", "market_cap": "Market cap (₹)",
    "roe_pct": "ROE", "roce_pct": "ROCE", "net_margin_pct": "Net margin", "operating_margin_pct": "Operating margin",
    "gross_margin_pct": "Gross margin", "debt_to_equity": "Debt / equity",
    "dividend_yield_pct": "Dividend yield", "eps_ttm": "EPS (TTM)", "revenue_ttm_cr": "Revenue (TTM)",
    "shareholders_equity_cr": "Shareholders' equity", "total_assets_cr": "Total assets",
    "total_liabilities_cr": "Total liabilities", "total_debt_cr": "Total debt", "cash_cr": "Cash",
    "retained_earnings_cr": "Retained earnings", "working_capital_cr": "Working capital",
    "book_value_per_share": "Book value / share", "as_of": "As of", "beta": "Beta",
    "ma50": "50-day avg", "ma200": "200-day avg", "revenue_growth_pct": "Revenue growth (YoY)",
    "earnings_growth_pct": "Earnings growth (YoY)", "current_ratio": "Current ratio",
    "high": "High", "low": "Low", "period_change_pct": "Period change", "last_close": "Last close",
}


def _fmt_val(k, v):
    if not isinstance(v, (int, float)):
        return str(v)
    if k.endswith("_cr"):
        return f"₹{v:,.0f} cr"
    if k == "market_cap":
        return f"₹{v:,.0f}"
    if k.endswith("_pct"):
        return f"{v:,.2f}%"
    if k in ("ma50", "ma200", "eps_ttm", "book_value_per_share", "last_close", "high", "low"):
        return f"₹{v:,.2f}"
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def _md_metrics(d: dict) -> str:
    if not d:
        return "_No data available._"
    rows = "\n".join(f"| {_LABELS.get(k, k.replace('_', ' '))} | {_fmt_val(k, v)} |" for k, v in d.items())
    return f"| Metric | Value |\n|---|---|\n{rows}"


def _c(v):
    return f"{v:,.0f}" if isinstance(v, (int, float)) else "—"


def _md_quarters(rows: list) -> str:
    if not rows:
        return "_No quarterly data available._"
    head = ("| Quarter | Revenue (₹ cr) | Net profit (₹ cr) | Op. income (₹ cr) | EPS (₹) |\n"
            "|---|--:|--:|--:|--:|")
    body = "\n".join(
        f"| {r.get('quarter','')} | {_c(r.get('revenue_cr'))} | {_c(r.get('net_income_cr'))} "
        f"| {_c(r.get('operating_income_cr'))} | {r.get('eps') if r.get('eps') is not None else '—'} |"
        for r in rows)
    return head + "\n" + body


def _execute(tool: str, ticker: str):
    """Returns (result_text, chart_payload_or_None). Never invents data."""
    try:
        if tool == "quote":
            q = market.quote(ticker)
            chg = q.get("change_pct")
            chg_txt = f"{chg:+.2f}% today" if chg is not None else "change n/a"
            state = q.get("market_state")
            STATE = {"REGULAR": "market open", "CLOSED": "market closed",
                     "PRE": "pre-market", "POST": "post-market"}
            live = q.get("source") == "live"
            tag = (f" [{STATE.get(state, state)}]" if state else "") if live else ""
            asof = f" as of {q['as_of']}" if q.get("as_of") else ""
            return (f"Latest price: ₹{q['price']} ({chg_txt}){tag}. "
                    f"Source: {q.get('source', 'sample')} data{asof}."), None

        if tool == "fundamental_analysis":
            f = market.fundamentals(ticker)
            if not f:
                return "Fundamentals not available for this stock.", None
            return _interpret(
                "Assess financial health and valuation. Call out the key strengths and "
                "weaknesses across PE, PB, ROE, margins, debt/equity and dividend yield, "
                "then give a one-line verdict on business quality.", f), None

        if tool == "technical_analysis":
            b = market.bundle(ticker)
            closes = [p["close"] for p in b["chart"]
                      if isinstance(p.get("close"), (int, float)) and p["close"] == p["close"]]
            if len(closes) < 5:
                return "Not enough price history for a technical read.", None
            sma = lambda n: round(sum(closes[-n:]) / min(n, len(closes)), 2)
            data = {"last": closes[-1], "sma20": sma(20), "sma50": sma(50),
                    "high_6m": max(closes), "low_6m": min(closes),
                    "week52": b.get("week52", {}), "change_6m_pct": b["price"]["change_pct"]}
            return _interpret(
                "Give a short technical read: trend (up / down / sideways), momentum, and "
                "where price sits versus its 20- and 50-day averages and its 6-month / "
                "52-week range. Do NOT predict future prices.", data), _chart_payload(b)

        if tool == "explain_move":
            b = market.bundle(ticker)
            p = b["price"]
            direction = "rise" if (p.get("change_pct") or 0) >= 0 else "decline"
            data = {"change_6m_pct": p["change_pct"], "start": p["start"], "end": p["end"],
                    "high": p["high"], "low": p["low"],
                    "news": [n.get("headline") for n in b["news"] if n.get("headline")]}
            return _interpret(
                f"Explain the most likely reasons behind the recent {direction} "
                f"({p['change_pct']}% over 6 months), connecting the price move to the news. "
                "Be explicit that this is interpretation, not certainty.", data), _chart_payload(b)

        if tool == "risk_assessment":
            b = market.bundle(ticker)
            data = {"fundamentals": b["fundamentals"], "valuation": market.valuation(ticker),
                    "change_6m_pct": b["price"]["change_pct"], "week52": b["week52"],
                    "news": [n.get("headline") for n in b["news"] if n.get("headline")]}
            return _interpret(
                "List the key DOWNSIDE risks for this stock right now (valuation, leverage, "
                "growth, news, momentum) as 3-5 short bullet points, each tied to the data.", data), None

        if tool == "bull_bear_case":
            b = market.bundle(ticker)
            data = {"fundamentals": b["fundamentals"], "price": b["price"],
                    "week52": b["week52"], "analyst": b.get("analyst", {}),
                    "news": [n.get("headline") for n in b["news"] if n.get("headline")]}
            return _interpret(
                "Give a balanced BULL case and BEAR case (2-3 grounded points each), then say "
                "which looks stronger and why.", data), None

        if tool == "verdict":
            b = market.bundle(ticker)
            data = {"fundamentals": b["fundamentals"], "valuation": market.valuation(ticker),
                    "price": b["price"], "week52": b["week52"], "analyst": b.get("analyst", {}),
                    "news": [n.get("headline") for n in b["news"] if n.get("headline")]}
            return _interpret(
                "Give a clear BUY / HOLD / SELL stance with 2-3 supporting reasons grounded in "
                "the data, plus the single biggest risk. Be concise; do NOT add any "
                "'informational only / not investment advice' disclaimer.", data), None

        if tool == "dividend_analysis":
            d = market.dividends(ticker)
            if not d:
                return "No dividend history on record.", None
            data = {"dividends": d, "dividend_yield_pct": market.fundamentals(ticker).get("dividend_yield_pct")}
            return _interpret(
                "Assess the dividend: is the payout growing, how consistent is it, and is the "
                "yield attractive? Keep it to a few sentences.", data), None

        if tool == "news_summary":
            heads = [n["headline"] for n in market.news(ticker) if n.get("headline")]
            if not heads:
                return "No recent news available.", None
            return "Summary:\n" + _interpret(
                "Summarise in 3-4 sentences what these headlines collectively mean for the "
                "stock and its near-term outlook.", {"headlines": heads}), None

        if tool == "analyst_ratings":
            a = market.analyst_ratings(ticker)
            if not a:
                return "Analyst price targets / consensus aren't available for this stock (live-only data).", None
            return "**Analyst consensus**\n\n" + _md_metrics(a), None

        if tool == "quarterly_results":
            q = market.quarterly(ticker)
            if not q:
                return "Quarterly results aren't available for this stock (live-only data).", None
            return "**Recent quarterly results**\n\n" + _md_quarters(q), None

        if tool == "balance_sheet":
            bs = market.balance_sheet(ticker)
            if not bs:
                return "Balance-sheet data isn't available for this stock (live-only data).", None
            return "**Balance sheet**\n\n" + _md_metrics(bs), None

        if tool == "key_stats":
            s = market.stats(ticker)
            if not s:
                return "Extended stats (beta, moving averages, growth) aren't available for this stock (live-only data).", None
            return "**Key stats**\n\n" + _md_metrics(s), None

        if tool == "news_sentiment":
            items = market.news(ticker)
            if not items:
                return "No recent news available for this stock.", None
            heads = "\n".join(f"- {n['headline']}" for n in items if n.get("headline"))
            mood = _llm.invoke([HumanMessage(content=(
                f"Headlines for {ticker}:\n{heads}\n\nClassify overall sentiment as "
                "Positive, Negative or Mixed and give one sentence why. Start with the label."
            ))]).content
            return f"{mood}\n\nHeadlines:\n{heads}", None

        if tool == "news_headlines":
            items = market.news(ticker)
            heads = "\n".join(f"- {n['headline']}" for n in items if n.get("headline"))
            return ("Recent headlines:\n" + heads) if heads else "No recent news available.", None

        if tool == "fundamentals":
            f = market.fundamentals(ticker)
            return ("**Fundamentals**\n\n" + _md_metrics(f)) if f else "Fundamentals aren't available for this stock.", None

        if tool == "valuation":
            v = market.valuation(ticker)
            return ("**Valuation**\n\n" + _md_metrics(v)) if v else "Valuation metrics aren't available for this stock.", None

        if tool == "performance":
            return "**Performance**\n\n" + _md_metrics(market.performance(ticker)), None

        if tool == "fifty_two_week":
            return "**52-week range**\n\n" + _md_metrics(market.week52(ticker)), None

        if tool == "dividends":
            d = market.dividends(ticker)
            if not d:
                return "No dividend history on record.", None
            body = "\n".join(f"| {x.get('year','')} | ₹{x.get('amount')} |" for x in d)
            return "**Dividend history**\n\n| Year | Dividend / share |\n|---|--:|\n" + body, None

        if tool == "price_trend":
            b = market.bundle(ticker)
            p = b["price"]
            txt = (f"6-month move: {p['change_pct']}% (from {p['start']} to {p['end']}, "
                   f"high {p['high']}, low {p['low']}).")
            chart = {"ticker": b["ticker"], "series": b["chart"], "change_pct": p["change_pct"],
                     "source": b.get("source", "sample")}
            return txt, chart

        if tool == "stock_splits":
            s = market.splits(ticker)
            if not s:
                return "No stock splits on record.", None
            body = "\n".join(f"| {x.get('date','')} | {x.get('ratio')}:1 |" for x in s)
            return "**Stock splits**\n\n| Date | Ratio |\n|---|---|\n" + body, None

    except Exception as e:
        return f"Could not fetch live data for this step ({e}). Continuing with what we have.", None

    return "Nothing to execute.", None


def _report(sess: dict) -> str:
    ctx = "\n\n".join(f"[{c['tool']}] {c['result']}" for c in sess["context"]) or "no data gathered"
    out = _llm.invoke([HumanMessage(content=(
        f"Task: {sess['task']}\nStock: {sess['ticker']} (NSE)\n\n"
        f"Everything gathered:\n{ctx}\n\n"
        "Directly ANSWER the task using ONLY the findings above; do not invent numbers. "
        "If it was a simple factual question, answer in 1-2 sentences — do not pad it. "
        "If it was a broad analysis, give a short structured summary with a clear takeaway. "
        "If some data was missing, say so briefly. Be concise; do NOT add any "
        "'informational only / not investment advice' disclaimer."
    ))]).content
    out = _reflect_report(sess, ctx, out)
    # Compliance guardrail: forbidden phrases -> semantic screen -> PII -> disclaimer
    return gr.enforce_compliance(out)


def _reflect_report(sess: dict, ctx: str, draft: str) -> str:
    """Self-correction: a critic checks the report against the gathered findings;
    one revision pass if it flags issues. Disable with SELF_REFLECT=0."""
    if os.environ.get("SELF_REFLECT", "1") == "0" or not draft:
        return draft
    try:
        raw = _llm.invoke([HumanMessage(content=(
            "You are a strict REVIEWER of an equity analyst's draft report.\n"
            "Check the draft against the findings:\n"
            "1. GROUNDING — every number/fact appears in the findings; nothing invented.\n"
            "2. COMPLETENESS — the task is actually answered.\n"
            "3. CORRECTNESS — units are right (₹, crore), no misread figures.\n"
            "4. COMPLIANCE — no guaranteed-return promises or directive personal advice; "
            "an analytic BUY/HOLD/SELL opinion is fine.\n"
            'Reply ONLY as JSON: {"verdict":"PASS" or "REVISE", "issues":"specific problems, or empty"}\n\n'
            f"TASK: {sess['task']}\nSTOCK: {sess['ticker']} (NSE)\n\n"
            f"FINDINGS:\n{ctx[:8000]}\n\nDRAFT REPORT:\n{draft}"
        ))]).content
        obj = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        if obj.get("verdict", "PASS").upper() != "REVISE" or not obj.get("issues"):
            return draft
        revised = _llm.invoke([HumanMessage(content=(
            "Revise the draft report to fix ONLY these reviewer issues, using ONLY the "
            f"findings — never invent numbers:\n{obj['issues']}\n\n"
            "Keep it concise and keep the same format. Reply with ONLY the corrected report.\n\n"
            f"TASK: {sess['task']}\n\nFINDINGS:\n{ctx[:8000]}\n\nDRAFT REPORT:\n{draft}"
        ))]).content
        return revised.strip() if revised and revised.strip() else draft
    except Exception:
        return draft   # reflection must never break the report path


# --------------------------------------------------------------------------- #
# Step-loop graph — LangGraph-native HITL. Every proposed step pauses at the
# interrupt() gate; the human's Command(resume=...) decides: approve runs the
# tool, "redirect:<instruction>" re-proposes, "stop" writes the report.
#
#   START → propose → gate ──approve──→ execute ──→ propose (loop)
#                       │──redirect───→ propose (loop)
#                       └──stop/finish→ report → END
# --------------------------------------------------------------------------- #
class TaskState(TypedDict):
    ticker: str
    task: str
    context: list
    proposal: Optional[dict]
    decision: Optional[str]
    redirects: int
    last_result: Optional[str]
    last_chart: Optional[dict]
    outcome: Optional[str]


def _node_propose(state: TaskState):
    redirects = state.get("redirects", 0)
    redirect = ""
    d = state.get("decision") or ""
    if d.startswith("redirect:"):
        redirect = d[len("redirect:"):].strip()
        redirects += 1
        if redirects > MAX_REDIRECTS:
            return {"proposal": {"tool": "finish",
                                 "summary": "Redirect limit reached — approve to get the final report."},
                    "decision": None, "redirects": redirects}
    prop = _propose(state, redirect=redirect)
    return {"proposal": prop, "decision": None, "redirects": redirects,
            "last_result": None, "last_chart": None}


def _node_gate(state: TaskState):
    prop = state["proposal"]
    decision = interrupt({"tool": prop["tool"], "summary": prop["summary"]})
    return {"decision": str(decision or "").strip()}


def _route(state: TaskState) -> str:
    d = state.get("decision") or ""
    if d == "stop":
        return "report"
    if d.startswith("redirect:"):
        return "propose"
    # approve
    if (state.get("proposal") or {}).get("tool") == "finish":
        return "report"
    return "execute"


def _node_execute(state: TaskState):
    prop = state["proposal"]
    result, chart = _execute(prop["tool"], state["ticker"])
    # Regex compliance screen on each step; the disclaimer goes on the final report only
    result = gr.enforce_compliance(result, semantic=False, disclaimer=False)
    if prop["tool"] == "verdict":
        # Track record: log the stance at today's price so it can be scored later
        try:
            import verdict_log
            verdict_log.log_verdict(state["ticker"], verdict_log.extract_verdict(result),
                                    market.quote(state["ticker"]).get("price"), source="task")
        except Exception:
            pass
    return {"context": state["context"] + [{"tool": prop["tool"], "result": result}],
            "last_result": result, "last_chart": chart, "decision": None}


def _node_report(state: TaskState):
    return {"outcome": _report(state)}


def _build():
    g = StateGraph(TaskState)
    for name, fn in [("propose", _node_propose), ("gate", _node_gate),
                     ("execute", _node_execute), ("report", _node_report)]:
        g.add_node(name, fn)
    g.add_edge(START, "propose")
    g.add_edge("propose", "gate")
    g.add_conditional_edges("gate", _route,
                            {"execute": "execute", "propose": "propose", "report": "report"})
    g.add_edge("execute", "propose")
    g.add_edge("report", END)
    return g.compile(checkpointer=MemorySaver())


GRAPH = _build()


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": f"task-{thread_id}"}}


def _events_from_update(update: dict, thread_id: str):
    payload = interrupt_payload(update)
    if payload is not None:
        yield {"type": "propose", "tool": payload.get("tool", ""),
               "summary": payload.get("summary", ""), "thread_id": thread_id}
        return
    for node, delta in update.items():
        delta = delta or {}
        if node == "execute":
            if delta.get("last_chart"):
                yield {"type": "chart", **delta["last_chart"]}
            if delta.get("last_result"):
                tool = (delta.get("context") or [{}])[-1].get("tool", "")
                yield {"type": "step_result", "tool": tool, "text": delta["last_result"]}
        elif node == "report":
            yield {"type": "final", "text": delta.get("outcome", "")}


# --------------------------------------------------------------------------- #
# Public streaming API
# --------------------------------------------------------------------------- #
async def start_task(ticker: str, task: str, thread_id: str):
    tk = ticker.upper()
    # preflight: make sure we can get data at all before proposing steps
    try:
        b = market.bundle(tk)
        source = b.get("source", "sample")
    except Exception as e:
        yield {"type": "final", "text": f"Couldn't start: {e}"}
        return

    src_note = "live market data" if source == "live" else "sample data (live feed unavailable)"
    yield {"type": "intro", "text": f"Working on: \"{task}\" for {tk}. Using {src_note}. I'll propose each step for your approval."}
    init: TaskState = {"ticker": tk, "task": task, "context": [], "proposal": None,
                       "decision": None, "redirects": 0, "last_result": None,
                       "last_chart": None, "outcome": None}
    try:
        async for update in astream_updates(GRAPH, init, _config(thread_id), timeout=120):
            for ev in _events_from_update(update, thread_id):
                yield ev
    except Exception as e:
        yield {"type": "error", "text": str(e)}


async def step_task(thread_id: str, decision: str):
    cfg = _config(thread_id)
    if not await has_pending_interrupt(GRAPH, cfg):
        yield {"type": "error", "text": "Session expired. Start a new task."}
        return
    try:
        async for update in astream_updates(GRAPH, Command(resume=decision), cfg, timeout=180):
            for ev in _events_from_update(update, thread_id):
                yield ev
    except Exception as e:
        yield {"type": "error", "text": str(e)}