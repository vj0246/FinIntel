"""
app.py
------
FastAPI web layer. One real endpoint:

    GET /api/analyze?ticker=RELIANCE  ->  Server-Sent Events stream

We turn the agent's async generator into an SSE stream. Each event the agent
yields becomes one `data:` line the browser receives instantly - that's how
the frontend shows the agent thinking in real time.
"""

import json
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agent import run_agent

app = FastAPI(title="Autonomous Equity Research Agent")

# Allow the React dev server (different port) to call us during the talk.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def sse(event: dict) -> str:
    """Format one dict as a Server-Sent Events frame."""
    return f"data: {json.dumps(event, default=str)}\n\n"


@app.get("/api/analyze")
async def analyze(ticker: str):
    """Stream the agent's reasoning for `ticker` as SSE."""

    async def event_stream():
        try:
            async for event in run_agent(ticker):
                yield sse(event)
        except Exception as e:
            yield sse({"type": "error", "text": str(e)})
        yield sse({"type": "done"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/health")
async def health():
    return {"ok": True, "has_key": bool(os.environ.get("GROQ_API_KEY"))}
