"""
agent.py
--------
The heart of the demo: an async agent loop.

The loop is the whole idea behind 'agentic' AI:

    while not done:
        ask the model what to do
        if it wants a tool -> run it, feed the result back
        else -> it's finished, return the answer

No framework. ~40 lines of real Python. Every iteration is one decision
by the model. We `yield` an event at each step so the web layer can stream
the agent's thinking to the browser live.
"""

import json
import os

from groq import AsyncGroq

import tools

MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """You are an autonomous equity research agent for Indian (NSE) stocks.

Your job: decide whether a stock is a BUY, HOLD or SELL for a long-term investor.

How to work:
1. Gather evidence FIRST. Call get_price_history, get_fundamentals and get_news.
2. Reason about what you found - momentum, valuation, news sentiment.
3. Then call generate_summary exactly once, passing a 'findings' note you write
   yourself that condenses the evidence.
4. Finally reply to the user with: a one-word verdict (BUY / HOLD / SELL) on its
   own first line, then the thesis returned by generate_summary.

Only use the tools provided. Think step by step. Keep moving toward a verdict."""


async def run_agent(ticker: str):
    """
    Async generator. Yields dict events:
      {"type": "plan",        "text": ...}   model's reasoning before a tool
      {"type": "tool_call",   "name", "args"}
      {"type": "tool_result", "name", "result"}
      {"type": "final",       "text": ...}   the verdict + thesis
      {"type": "error",       "text": ...}
    """
    client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY", ""))

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Analyse {ticker.upper()} and give me a verdict."},
    ]
    schemas = tools.tool_schemas()

    for _ in range(8):  # safety cap so a confused model can't loop forever
        resp = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=schemas,
            tool_choice="auto",
            temperature=0.3,
        )
        msg = resp.choices[0].message

        # No tool calls -> the agent is done and has written its verdict.
        if not msg.tool_calls:
            yield {"type": "final", "text": msg.content or ""}
            return

        # Surface any reasoning the model wrote alongside its tool calls.
        if msg.content:
            yield {"type": "plan", "text": msg.content}

        # Append the assistant turn (with its tool calls) to the history.
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
        })

        # Execute each requested tool and feed the result back to the model.
        for tc in msg.tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments or "{}")
            yield {"type": "tool_call", "name": name, "args": args}

            try:
                result = tools.run_tool(name, args)
            except Exception as e:  # tool errors are data the model can react to
                result = {"error": str(e)}

            yield {"type": "tool_result", "name": name, "result": result}

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str),
            })

    yield {"type": "error", "text": "Agent hit its step limit without a verdict."}
