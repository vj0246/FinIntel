"""
app_multi.py
------------
FastAPI for the multi-agent + human-in-the-loop demo.
Production-grade: guardrails, rate limiting, request tracing, smart caching.

Two SSE endpoints because HITL is two-phase:
  GET /api/analyze?ticker=RELIANCE&thread=<uuid>
      → streams agent steps, stops at an {approval_request}
  GET /api/resume?thread=<uuid>&decision=approve|reject|<feedback text>
      → resumes the SAME run (matched by thread id) and streams the outcome

Run:  uvicorn app_multi:app --reload --port 8000
"""

import json
import os
import uuid

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

from agent_multi import start_run, resume_run
from chat_agent import run_chat
from agent_task import start_task, step_task
import companies
import docstore
import guardrails as gr
from rate_limiter import RateLimitMiddleware

app = FastAPI(title="Multi-Agent Equity Desk (HITL)")

# Rate limiting — applied BEFORE CORS so blocked requests still get proper headers
app.add_middleware(RateLimitMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# --------------------------------------------------------------------------- #
# Request ID middleware — attaches a unique ID to every request/response
# --------------------------------------------------------------------------- #
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


def _cache_headers() -> dict:
    """Return Cache-Control headers based on market hours."""
    try:
        from market import _market_open
        if _market_open():
            return {"Cache-Control": "public, max-age=60"}
        return {"Cache-Control": "public, max-age=3600"}
    except Exception:
        return {"Cache-Control": "public, max-age=60"}


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/api/analyze")
async def analyze(ticker: str, thread: str):
    t = gr.validate_ticker(ticker)
    tid = gr.validate_uuid(thread)

    async def stream():
        try:
            async for ev in start_run(t, tid):
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "text": str(e)})
        yield sse({"type": "done"})
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/resume")
async def resume(thread: str, decision: str):
    tid = gr.validate_uuid(thread)
    d = gr.validate_text(decision, max_len=500, field_name="Decision")

    async def stream():
        try:
            async for ev in resume_run(tid, d):
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "text": str(e)})
        yield sse({"type": "done"})
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/task/start")
async def task_start(ticker: str, task: str, thread: str):
    t = gr.validate_ticker(ticker)
    tsk = gr.validate_text(task, max_len=1000, field_name="Task")
    tid = gr.validate_uuid(thread)

    async def stream():
        try:
            async for ev in start_task(t, tsk, tid):
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "text": str(e)})
        yield sse({"type": "done"})
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/task/step")
async def task_step(thread: str, decision: str):
    tid = gr.validate_uuid(thread)
    d = gr.validate_text(decision, max_len=500, field_name="Decision")

    async def stream():
        try:
            async for ev in step_task(tid, d):
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "text": str(e)})
        yield sse({"type": "done"})
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/chat")
async def chat(ticker: str, q: str, thread: str):
    t = gr.validate_ticker(ticker)
    question = gr.validate_text(q, max_len=2000, field_name="Question")
    tid = gr.validate_uuid(thread)

    # Prompt injection check
    if gr.check_prompt_injection(question):
        async def blocked():
            yield sse({"type": "answer", "text": "I can only help with financial and stock-related questions. Please rephrase your query."})
            yield sse({"type": "done"})
        return StreamingResponse(blocked(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    async def stream():
        try:
            async for ev in run_chat(t, question, tid):
                # Belt-and-braces: chat_agent already ran the compliance pipeline on the
                # final answer; re-screen here so error/fallback answers are covered too,
                # and the mandatory disclaimer survives any truncation.
                if ev.get("type") == "answer" and ev.get("text"):
                    ev["text"] = gr.append_disclaimer(gr.sanitise_output(ev["text"]))
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "text": str(e)})
        yield sse({"type": "done"})
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/portfolio")
async def portfolio_upload(thread: str = Form(...), file: UploadFile = File(None),
                           text: str = Form(None)):
    """Load holdings for a thread — broker CSV upload or pasted lines."""
    import portfolio
    tid = gr.validate_uuid(thread)
    if file is not None and file.filename:
        raw = await file.read()
        if len(raw) > 1024 * 1024:
            raise HTTPException(status_code=400, detail="File too large (max 1 MB).")
        content = raw.decode("utf-8", errors="replace")
    elif text:
        content = gr.validate_text(text, max_len=8000, field_name="Holdings")
    else:
        raise HTTPException(status_code=422, detail="Provide a CSV file or pasted holdings.")

    holdings, warnings = portfolio.parse_holdings(content)
    if not holdings:
        raise HTTPException(status_code=422,
                            detail="No valid holdings found. Format: TICKER, qty, avg cost — one per line.")
    portfolio.set_holdings(tid, holdings)
    return {"ok": True, "holdings": holdings, "warnings": warnings}


@app.get("/api/portfolio/analyze")
async def portfolio_analyze(thread: str):
    import portfolio
    tid = gr.validate_uuid(thread)

    async def stream():
        try:
            async for ev in portfolio.analyze(tid):
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "text": str(e)})
        yield sse({"type": "done"})
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/portfolio/resume")
async def portfolio_resume(thread: str, decision: str):
    import portfolio
    tid = gr.validate_uuid(thread)
    d = gr.validate_text(decision, max_len=500, field_name="Decision")

    async def stream():
        try:
            async for ev in portfolio.resume(tid, d):
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "text": str(e)})
        yield sse({"type": "done"})
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/war/start")
async def war_start(q: str, thread: str, ticker: str = ""):
    """Research War Room: orchestrated specialists + bull/bear debate + judge."""
    import war_room
    question = gr.validate_text(q, max_len=1000, field_name="Question")
    tid = gr.validate_uuid(thread)
    t = gr.validate_ticker(ticker) if ticker else ""
    if gr.check_prompt_injection(question):
        raise HTTPException(status_code=422, detail="Ask a research question about a stock.")

    async def stream():
        try:
            async for ev in war_room.start(question, t, tid):
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "text": str(e)})
        yield sse({"type": "done"})
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/war/resume")
async def war_resume(thread: str, decision: str):
    import war_room
    tid = gr.validate_uuid(thread)
    d = gr.validate_text(decision, max_len=500, field_name="Decision")

    async def stream():
        try:
            async for ev in war_room.resume(tid, d):
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "text": str(e)})
        yield sse({"type": "done"})
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/ecosystem")
async def ecosystem_api(ticker: str, thread: str):
    """Company Ecosystem map: competitors, customers, suppliers, partners, segments."""
    import ecosystem
    t = gr.validate_ticker(ticker)
    gr.validate_uuid(thread)

    async def stream():
        try:
            async for ev in ecosystem.analyze(t, thread):
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "text": str(e)})
        yield sse({"type": "done"})
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/track-record")
async def track_record_api():
    """The desk's own scorecard: every logged verdict re-checked at current prices."""
    import verdict_log
    import asyncio as _aio
    return await _aio.to_thread(verdict_log.track_record)


@app.get("/api/ledger")
async def ledger_api():
    """Paper-trading ledger: every BUY/SELL call as a ₹1L virtual position, with alpha vs NIFTY."""
    import verdict_log
    import asyncio as _aio
    return await _aio.to_thread(verdict_log.ledger)


@app.get("/api/discover")
async def discover_api(q: str, thread: str):
    """Natural-language stock screener over the curated NSE universe."""
    import discover
    query = gr.validate_text(q, max_len=500, field_name="Screen")
    gr.validate_uuid(thread)
    if gr.check_prompt_injection(query):
        raise HTTPException(status_code=422, detail="Describe a stock screen, e.g. 'IT stocks with ROE above 20'.")

    async def stream():
        try:
            async for ev in discover.run(query, thread):
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "text": str(e)})
        yield sse({"type": "done"})
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/brief")
async def brief_api(thread: str, tickers: str = ""):
    """Morning brief: global cues + Indian indices + the user's watchlist."""
    import brief
    gr.validate_uuid(thread)
    tick_list = [t for t in tickers.split(",") if t.strip()][:8]
    for t in tick_list:
        gr.validate_ticker(t)

    async def stream():
        try:
            async for ev in brief.run(tick_list, thread):
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "text": str(e)})
        yield sse({"type": "done"})
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/report")
async def report_api(ticker: str, thread: str):
    """One-click deep research report orchestrating every engine on the desk."""
    import report
    t = gr.validate_ticker(ticker)
    gr.validate_uuid(thread)

    async def stream():
        try:
            async for ev in report.run(t, thread):
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "text": str(e)})
        yield sse({"type": "done"})
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/backtest")
async def backtest_api(request: Request, thread: str):
    """What-if backtest: lumpsum / SIP / both, dividends, brokerage, NIFTY benchmark."""
    import backtest
    gr.validate_uuid(thread)
    try:
        params = backtest.validate_params(dict(request.query_params))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    async def stream():
        try:
            async for ev in backtest.run(params, thread):
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "text": str(e)})
        yield sse({"type": "done"})
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/symbols")
async def symbols(q: str = ""):
    """Autocomplete for the search bar: company names + NSE tickers."""
    results = companies.search(q, limit=8)
    return JSONResponse(
        content={"results": results},
        headers={"Cache-Control": "public, max-age=3600"},  # static data
    )


@app.post("/api/upload")
async def upload(thread: str = Form(...), file: UploadFile = File(...)):
    """Attach a PDF / Word / text document to a chat thread for Q&A."""
    tid = gr.validate_uuid(thread)
    gr.validate_file_extension(file.filename)

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 15 MB).")
    try:
        text = docstore.extract_text(file.filename, raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    meta = docstore.add_document(tid, file.filename, text)
    return {"ok": True, **meta}


@app.delete("/api/upload")
async def upload_clear(thread: str):
    tid = gr.validate_uuid(thread)
    docstore.clear(tid)
    return {"ok": True}


@app.get("/api/health")
async def health():
    import groq_pool
    return {"ok": True, "has_key": bool(os.environ.get("GROQ_API_KEY")),
            "groq_keys": groq_pool.key_count(),
            "langsmith": bool(os.environ.get("LANGCHAIN_API_KEY"))}


@app.get("/api/cache/status")
async def cache_status():
    """Debug endpoint: cache stats, TTL mode, and market status."""
    import market
    try:
        is_open = market._market_open()
    except Exception:
        is_open = None

    bundle_ttl = market._get_ttl()
    quote_ttl = market._get_quote_ttl()
    cached_tickers = list(market._CACHE.keys())

    return {
        "market_open": is_open,
        "bundle_ttl_seconds": bundle_ttl,
        "quote_ttl_seconds": quote_ttl,
        "cached_tickers": cached_tickers,
        "cached_count": len(cached_tickers),
    }
