"""
portfolio.py
------------
Portfolio Risk Auditor — multi-agent audit of a trader's REAL holdings.

Flow:
  1. POST /api/portfolio            — upload broker CSV (Zerodha/Groww) or pasted
                                      lines; parsed holdings stored per thread
  2. GET  /api/portfolio/analyze    — SSE stream:
         fan-out: every holding analysed IN PARALLEL (price, fundamentals,
                  news) with a live event per completed holding
         deterministic portfolio maths: weights, sector concentration,
                  weighted P/E, 52-week positioning, loss positions
         Risk officer (LLM): portfolio-level findings from the real metrics
         Synthesiser (LLM): concrete rebalance proposals -> approval card
  3. GET  /api/portfolio/resume     — human decision: approve / reject / revise
                                      (revise re-runs the synthesiser with feedback)

All LLM output is grounded in the computed metrics — never invented — and every
final answer goes through the compliance guardrail + mandatory disclaimer.
"""

import asyncio
import csv
import io
import json
import os
import re

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
import groq_pool

import market
import guardrails as gr

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

MODEL = "openai/gpt-oss-120b"
_llm = groq_pool.create_llm(MODEL, temperature=0.3)

_sessions: dict = {}       # thread_id -> {"holdings": [...], "rows": [...], "metrics": {}, "pending": {}}

MAX_HOLDINGS = 15          # keeps the parallel fan-out inside provider rate limits
_CONCURRENCY = 3           # simultaneous market-data fetches


# --------------------------------------------------------------------------- #
# Holdings parsing — broker CSV (Zerodha / Groww) or pasted plain lines
# --------------------------------------------------------------------------- #
_TICKER_COLS = ("instrument", "symbol", "ticker", "tradingsymbol", "stock", "scrip", "stock name")
_QTY_COLS    = ("qty", "qty.", "quantity", "shares", "units", "net qty", "quantity available")
_COST_COLS   = ("avg. cost", "avg cost", "avg price", "avg. price", "buy price",
                "average price", "avg_cost", "buy average", "average buy price")


def _clean_ticker(raw: str) -> str | None:
    """Normalise a broker symbol to a plain NSE ticker; None if unusable."""
    t = (raw or "").strip().upper()
    t = re.sub(r"\.(NS|BO)$", "", t)
    t = re.sub(r"-(EQ|BE|BZ|SM)$", "", t)         # NSE series suffixes
    if not t or not re.match(r"^[A-Z0-9&\-]{1,20}$", t):
        return None
    return t


def _num(v) -> float | None:
    try:
        n = float(str(v).replace(",", "").replace("₹", "").strip())
        return n if n == n else None
    except Exception:
        return None


def parse_holdings(text: str) -> tuple[list[dict], list[str]]:
    """Parse holdings from CSV-with-header or plain 'TICKER, qty, avg_cost' lines.

    Returns (holdings, warnings). Each holding: {ticker, qty, avg_cost|None}.
    """
    text = (text or "").strip()
    if not text:
        return [], ["No holdings provided."]

    holdings, warnings = [], []

    # Try broker CSV first: a header row naming a symbol column
    try:
        sample = text.splitlines()[0].lower()
        if any(c in sample for c in _TICKER_COLS):
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                low = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                tick = next((low[c] for c in _TICKER_COLS if low.get(c)), None)
                qty = next((_num(low[c]) for c in _QTY_COLS if low.get(c)), None)
                cost = next((_num(low[c]) for c in _COST_COLS if low.get(c)), None)
                t = _clean_ticker(tick) if tick else None
                if t and qty:
                    holdings.append({"ticker": t, "qty": qty, "avg_cost": cost})
                elif tick:
                    warnings.append(f"Skipped row '{tick}' (missing quantity or bad symbol).")
            if holdings:
                return holdings[:MAX_HOLDINGS], warnings
    except Exception:
        pass  # fall through to plain-line parsing

    # Plain lines: "RELIANCE, 10, 2450"  /  "TCS 5 3900"  /  "INFY 12"
    for line in text.splitlines():
        line = line.strip()
        if not line or line.lower().startswith(("instrument", "symbol", "ticker")):
            continue
        parts = [p for p in re.split(r"[,\t;]+|\s{1,}", line) if p.strip()]
        t = _clean_ticker(parts[0]) if parts else None
        qty = _num(parts[1]) if len(parts) > 1 else None
        cost = _num(parts[2]) if len(parts) > 2 else None
        if t and qty:
            holdings.append({"ticker": t, "qty": qty, "avg_cost": cost})
        else:
            warnings.append(f"Couldn't parse line: '{line[:60]}' (need: TICKER, qty[, avg cost]).")

    if len(holdings) > MAX_HOLDINGS:
        warnings.append(f"Portfolio capped at {MAX_HOLDINGS} holdings for analysis.")
    return holdings[:MAX_HOLDINGS], warnings


def set_holdings(thread_id: str, holdings: list[dict]):
    _sessions[thread_id] = {"holdings": holdings, "rows": [], "metrics": {}, "pending": None}


# --------------------------------------------------------------------------- #
# Per-holding fetch (runs in a worker thread; market.py caches bundles)
# --------------------------------------------------------------------------- #
def _fetch_holding(h: dict) -> dict:
    t = h["ticker"]
    try:
        b = market.bundle(t)
        try:
            q = market.quote(t)
            ltp = q.get("price")
        except Exception:
            ltp = None
        ltp = ltp or b["price"]["end"]
        f = b.get("fundamentals") or {}
        w52 = b.get("week52") or {}
        value = round(ltp * h["qty"], 2) if ltp else None
        pnl_pct = (round((ltp / h["avg_cost"] - 1) * 100, 2)
                   if ltp and h.get("avg_cost") else None)
        hi, lo = w52.get("high"), w52.get("low")
        pos52 = (round((ltp - lo) / (hi - lo) * 100, 1)
                 if ltp and hi and lo and hi > lo else None)
        return {
            "ticker": t, "name": b.get("name", t), "qty": h["qty"],
            "avg_cost": h.get("avg_cost"), "ltp": ltp, "value": value,
            "pnl_pct": pnl_pct, "day_change_pct": b["quote"].get("change_pct"),
            "sector": f.get("sector"), "pe": f.get("pe"),
            "dividend_yield_pct": f.get("dividend_yield_pct"),
            "debt_to_equity": f.get("debt_to_equity"),
            "pos_52w_pct": pos52,      # 0 = at 52w low, 100 = at 52w high
            "headlines": [n.get("headline") for n in (b.get("news") or [])[:2] if n.get("headline")],
            "source": b.get("source", "sample"),
        }
    except Exception as e:
        return {"ticker": t, "qty": h["qty"], "avg_cost": h.get("avg_cost"), "error": str(e)}


# --------------------------------------------------------------------------- #
# Deterministic portfolio maths — real numbers the LLMs must stay inside
# --------------------------------------------------------------------------- #
def _portfolio_metrics(rows: list[dict]) -> dict:
    ok = [r for r in rows if not r.get("error") and r.get("value")]
    total = sum(r["value"] for r in ok)
    if not ok or not total:
        return {"error": "No holdings could be valued."}

    for r in ok:
        r["weight_pct"] = round(r["value"] / total * 100, 1)

    sectors: dict = {}
    for r in ok:
        s = r.get("sector") or "Unknown"
        sectors[s] = round(sectors.get(s, 0) + r["weight_pct"], 1)

    pe_rows = [r for r in ok if isinstance(r.get("pe"), (int, float))]
    weighted_pe = (round(sum(r["pe"] * r["value"] for r in pe_rows) /
                         sum(r["value"] for r in pe_rows), 1) if pe_rows else None)

    top = max(ok, key=lambda r: r["weight_pct"])
    top_sector = max(sectors.items(), key=lambda kv: kv[1])

    flags = []
    if top["weight_pct"] > 25:
        flags.append(f"CONCENTRATION: {top['ticker']} alone is {top['weight_pct']}% of the "
                     "portfolio (above the common 25% single-stock guideline).")
    if top_sector[1] > 40 and len(sectors) > 1:
        flags.append(f"SECTOR CONCENTRATION: {top_sector[0]} is {top_sector[1]}% of the portfolio.")
    if weighted_pe and weighted_pe > 35:
        flags.append(f"VALUATION: portfolio-weighted P/E is {weighted_pe} — expensive as a book.")
    for r in ok:
        if r.get("pnl_pct") is not None and r["pnl_pct"] <= -20:
            flags.append(f"DRAWDOWN: {r['ticker']} is {r['pnl_pct']}% below your average cost.")
        if r.get("pos_52w_pct") is not None and r["pos_52w_pct"] <= 10:
            flags.append(f"WEAK MOMENTUM: {r['ticker']} trades within 10% of its 52-week low.")
        if isinstance(r.get("debt_to_equity"), (int, float)) and r["debt_to_equity"] > 2:
            flags.append(f"LEVERAGE: {r['ticker']} has debt/equity of {r['debt_to_equity']}.")
    errors = [r["ticker"] for r in rows if r.get("error")]
    if errors:
        flags.append(f"DATA: no live data for {', '.join(errors)} — excluded from totals.")

    pnl_rows = [r for r in ok if r.get("pnl_pct") is not None and r.get("avg_cost")]
    invested = sum(r["avg_cost"] * r["qty"] for r in pnl_rows)
    total_pnl_pct = (round((sum(r["value"] for r in pnl_rows) / invested - 1) * 100, 2)
                     if invested else None)

    return {
        "total_value": round(total, 2),
        "total_pnl_pct": total_pnl_pct,
        "holdings_count": len(ok),
        "weighted_pe": weighted_pe,
        "top_position": {"ticker": top["ticker"], "weight_pct": top["weight_pct"]},
        "sectors": sectors,
        "flags": flags,
    }


# --------------------------------------------------------------------------- #
# LLM roles
# --------------------------------------------------------------------------- #
def _ask(role: str, content: str) -> str:
    return _llm.invoke([HumanMessage(content=f"{role}\n\n{content}")]).content.strip()


def _risk_officer(rows: list[dict], metrics: dict) -> str:
    return _ask(
        "You are a portfolio RISK OFFICER. Using ONLY the metrics and flags below "
        "(never invent numbers), write the 3-5 most important portfolio-level findings "
        "as short bullets. Rank by severity. Cite the actual figures. All money is ₹.",
        json.dumps({"metrics": metrics,
                    "holdings": [{k: r.get(k) for k in
                                  ("ticker", "weight_pct", "pnl_pct", "pe", "sector",
                                   "pos_52w_pct", "headlines")} for r in rows]},
                   default=str),
    )


def _synthesise(metrics: dict, risk: str, feedback: str = "") -> dict:
    fb = f"\n\nReviewer feedback to address: {feedback}" if feedback else ""
    raw = _ask(
        "You are the SYNTHESISER of a portfolio audit. Combine the metrics and the risk "
        "findings into a rebalance proposal. Reply ONLY as JSON: "
        '{"summary":"2-3 sentence portfolio health verdict", '
        '"actions":[{"action":"one concrete, specific step (e.g. Trim X from 34% towards 25%)", '
        '"reason":"one sentence tied to the data"}]} '
        "Give 2-4 actions, most important first. Frame everything as analysis for the "
        "user to consider — never directive commands." + fb,
        f"METRICS:\n{json.dumps(metrics, default=str)}\n\nRISK FINDINGS:\n{risk}",
    )
    try:
        obj = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        actions = [a for a in obj.get("actions", []) if a.get("action")][:4]
        return {"summary": obj.get("summary", "").strip(), "actions": actions}
    except Exception:
        return {"summary": raw[:300], "actions": [{"action": "Flag portfolio for manual review",
                                                   "reason": "Synthesis output was not parseable."}]}


def _screen_proposal(p: dict) -> dict:
    """Regex compliance layer on every proposal string (semantic pass runs on the final)."""
    p["summary"] = gr.enforce_compliance(p["summary"], semantic=False, disclaimer=False)
    for a in p["actions"]:
        a["action"] = gr.enforce_compliance(a["action"], semantic=False, disclaimer=False)
        a["reason"] = gr.enforce_compliance(a.get("reason", ""), semantic=False, disclaimer=False)
    return p


# --------------------------------------------------------------------------- #
# Public streaming API
# --------------------------------------------------------------------------- #
async def analyze(thread_id: str):
    sess = _sessions.get(thread_id)
    if not sess or not sess["holdings"]:
        yield {"type": "error", "text": "No holdings found. Upload or paste your portfolio first."}
        return

    n = len(sess["holdings"])
    yield {"type": "intro",
           "text": f"Auditing {n} holding{'s' if n > 1 else ''} — fetching live data in parallel…"}

    _start = asyncio.get_event_loop().time()
    _TIMEOUT = 150   # whole audit hard cap

    sem = asyncio.Semaphore(_CONCURRENCY)

    async def fetch(h):
        async with sem:
            return await asyncio.to_thread(_fetch_holding, h)

    rows = []
    tasks = [asyncio.create_task(fetch(h)) for h in sess["holdings"]]
    for coro in asyncio.as_completed(tasks):
        r = await coro
        rows.append(r)
        yield {"type": "holding", **r}
        if asyncio.get_event_loop().time() - _start > _TIMEOUT:
            for t in tasks:
                t.cancel()
            yield {"type": "error", "text": "Audit timed out while fetching market data. Try again."}
            return

    metrics = _portfolio_metrics(rows)
    if metrics.get("error"):
        yield {"type": "error", "text": metrics["error"]}
        return
    sess["rows"], sess["metrics"] = rows, metrics
    yield {"type": "portfolio", "metrics": metrics}

    risk = await asyncio.to_thread(_risk_officer, rows, metrics)
    risk = gr.enforce_compliance(risk, semantic=False, disclaimer=False)
    yield {"type": "agent", "name": "Risk", "text": risk}

    proposal = await asyncio.to_thread(_synthesise, metrics, risk)
    proposal = _screen_proposal(proposal)
    sess["pending"] = {"risk": risk, **proposal}
    yield {"type": "approval_request", "summary": proposal["summary"],
           "actions": proposal["actions"], "thread_id": thread_id}


def _final_report(sess: dict, decision_note: str) -> str:
    m, p = sess["metrics"], sess["pending"]
    lines = [f"# Portfolio audit — {decision_note}", ""]
    if m.get("total_value"):
        pnl = f" · P&L {m['total_pnl_pct']:+.2f}%" if m.get("total_pnl_pct") is not None else ""
        lines.append(f"**Value:** ₹{m['total_value']:,.0f} across {m['holdings_count']} holdings{pnl}"
                     + (f" · weighted P/E {m['weighted_pe']}" if m.get("weighted_pe") else ""))
    lines += ["", "**Verdict:** " + p["summary"], "", "**Risk findings**", p["risk"], "",
              "**Agreed actions**"]
    lines += [f"{i+1}. {a['action']} — {a.get('reason', '')}" for i, a in enumerate(p["actions"])]
    # Full pipeline: semantic screen + PII + mandatory disclaimer
    return gr.enforce_compliance("\n".join(lines))


async def resume(thread_id: str, decision: str):
    sess = _sessions.get(thread_id)
    if not sess or not sess.get("pending"):
        yield {"type": "error", "text": "Session expired. Run the audit again."}
        return

    if decision == "approve":
        yield {"type": "final", "text": _final_report(sess, "actions approved")}
        sess["pending"] = None

    elif decision == "reject":
        yield {"type": "final",
               "text": gr.append_disclaimer("Audit REJECTED by reviewer — no actions recorded. "
                                            "The findings above remain available for reference.")}
        sess["pending"] = None

    else:   # revise with feedback -> new proposal -> pause again
        proposal = await asyncio.to_thread(
            _synthesise, sess["metrics"], sess["pending"]["risk"], decision)
        proposal = _screen_proposal(proposal)
        sess["pending"] = {"risk": sess["pending"]["risk"], **proposal}
        yield {"type": "approval_request", "summary": proposal["summary"],
               "actions": proposal["actions"], "thread_id": thread_id}
