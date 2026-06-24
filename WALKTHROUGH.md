# 8-Minute Code Walkthrough — Speaker Script

This is your teaching script. It is written in *your* voice, first person, as if
you built it. Each section: what to show, what to say, and the questions a Python
crowd will fire at you with ready answers.

Open the project in two split panes: `tools.py` / `agent.py` on the left, the
running browser on the right. **Run the demo once before you explain anything.**

---

## 0:00 – 0:30 · Run it first, then explain

> "Before I show a single line, let me run it." *(Pick RELIANCE, hit Run.)*
> "Watch the right side. The agent is deciding what to do, calling tools, and
> writing a verdict — nothing here is scripted, it's the model choosing each step.
> Now let me show you the four files that make that happen."

Keep the result on screen while you talk. The live stream is your hook.

---

## 0:30 – 2:00 · `tools.py` — the agent's hands

Show the four functions and the two Pydantic models.

> "An agent is only as good as its tools. I gave it four. Three fetch data —
> price history, news, fundamentals. The fourth, `generate_summary`, is special:
> it's a **generative tool**. The agent calls an LLM *as a tool* to turn its
> findings into prose. So the agent orchestrates, and generative AI is one thing
> it can reach for. That's the 'GenAI inside an agent' idea in one function."

Then the Python flex — Pydantic:

> "I didn't hand-write JSON schemas for the model. I described each tool's
> arguments as a Pydantic model — `TickerArg`, `SummaryArg` — and called
> `.model_json_schema()`. One source of truth. I get the schema the LLM needs
> *and* runtime validation of whatever the model sends back, for free."

Then the registry:

> "Dispatch is a dict, not a pile of if/elif. `REGISTRY` maps name → (function,
> arg model, description). `tool_schemas()` builds the whole tools array from it,
> and `run_tool()` validates and calls in one line. Add a fifth tool? One dict
> entry, zero changes to the loop."

**Likely questions**
- *"Why Pydantic over raw dicts?"* → Validation + schema generation from the same
  class. If the model hallucinates a bad argument, Pydantic raises before my code
  runs on garbage.
- *"Is `generate_summary` recursion / an agent calling itself?"* → No, it's a
  plain one-shot LLM call. The *agent* is the loop in `agent.py`; this tool is
  just a generation step the agent can trigger.
- *"Mocked data — would real APIs drop in cleanly?"* → Yes. The tool signatures
  stay the same; I'd swap the JSON read for an `nsepython` / broker API call. The
  agent doesn't know or care.

---

## 2:00 – 5:30 · `agent.py` — the loop (the heart)

This is the centre of the talk. Slow down here.

Put the loop on screen:

```python
for _ in range(8):
    resp = await client.chat.completions.create(
        model=MODEL, messages=messages, tools=schemas, tool_choice="auto",
    )
    msg = resp.choices[0].message
    if not msg.tool_calls:
        yield {"type": "final", "text": msg.content}; return
    ...
    for tc in msg.tool_calls:
        result = tools.run_tool(tc.function.name, json.loads(tc.function.arguments))
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": ...})
```

> "This is the whole idea behind *agentic* AI, and it's about fifteen real lines.
> Loop: ask the model what to do. If it asks for a tool, I run it and feed the
> result back into the conversation. If it doesn't ask for a tool, it's done —
> it has written its verdict, and I return. The model is driving; I'm just the
> runtime that executes its decisions and hands back results."

Hit the key mechanics a Python dev wants:

> - "`tools=schemas` and `tool_choice='auto'` — I offer the tools, the model
>   decides if and which to call. I never hard-code the order."
> - "When the model calls a tool, I append the assistant turn *and* a
>   `role: 'tool'` message with the result, keyed by `tool_call_id`. That id
>   linkage is what lets the model match results to the calls it made."
> - "The `range(8)` is a safety cap. A confused model can loop; I bound it. In
>   production you'd also cap tokens and cost."
> - "It's an **async generator** — notice `yield` inside `async def`. Every step
>   the agent takes, I yield an event. That's what makes the live streaming
>   possible; I'll show that next."

Point at the **system prompt**:

> "The behaviour — gather first, then summarise, then give a one-word verdict —
> lives in the system prompt, not in if-statements. That's the shift: I'm
> programming with instructions and tools, not control flow."

**Likely questions**
- *"What if the model calls a tool that doesn't exist / bad args?"* → `run_tool`
  raises, I catch it, and I feed the error back as the tool result. The model
  sees the error and recovers. Errors are just more data to the agent.
- *"Why async if it's one user?"* → Two reasons: streaming needs an async
  generator to yield mid-flight, and FastAPI serves many viewers concurrently
  without blocking. Groq is fast, so the loop feels instant.
- *"Could it loop forever?"* → The `range(8)` cap. If it never stops, I emit an
  error event instead of hanging.
- *"Is this LangChain?"* → No framework. Just the Groq SDK and a `for` loop. I
  wanted you to see the actual mechanism, not a black box. Frameworks wrap
  exactly this.

---

## 5:30 – 7:00 · `app.py` — FastAPI + Server-Sent Events

> "The agent yields events. Now I need them in the browser the instant they
> happen. I use Server-Sent Events — a one-way stream over plain HTTP, simpler
> than WebSockets and perfect for 'server pushes updates'."

Show `event_stream` + `StreamingResponse`:

```python
async def event_stream():
    async for event in run_agent(ticker):
        yield f"data: {json.dumps(event)}\n\n"
return StreamingResponse(event_stream(), media_type="text/event-stream")
```

> "I wrap the agent's async generator in another async generator that formats
> each event as an SSE frame — `data: {...}\n\n`. `StreamingResponse` keeps the
> connection open and flushes each frame as it's produced. No polling, no
> buffering. The agent thinks, the browser sees it immediately."

> "Two generators chained: the agent yields domain events, the web layer yields
> wire frames. Clean separation — the agent knows nothing about HTTP."

**Likely questions**
- *"SSE vs WebSocket?"* → SSE is one-directional (server → client), text, and
  rides normal HTTP — exactly my need. WebSocket is bidirectional and heavier; I
  don't need the client to stream back.
- *"`X-Accel-Buffering: no`?"* → Stops proxies like nginx from buffering the
  stream and killing the real-time feel on deploy.
- *"How does the browser read it?"* → The built-in `EventSource` API — next file.

---

## 7:00 – 8:00 · `App.jsx` — surfacing it live

Keep this short; Python's the star.

> "React side is thin on purpose. `new EventSource('/api/analyze?ticker=...')` —
> the browser's built-in SSE client. Every frame fires `onmessage`; I parse the
> JSON and append it to React state. The reasoning spine you saw is just that
> array of events rendered — teal nodes for tool calls, the verdict card at the
> end. The intelligence is all server-side; the frontend just narrates it."

> "And that's the full path: a `for` loop in Python decides what to do, yields
> events through FastAPI as SSE, and React paints them as they land. That's an
> AI agent, end to end, no magic."

**Likely questions**
- *"Why not just fetch the final answer?"* → The *point* is showing the agent
  reason. Streaming the steps is the product, not a nicety.
- *"EventSource only does GET?"* → Right, so I pass the ticker as a query param.
  For larger inputs I'd switch to a fetch + `ReadableStream` POST.

---

## Closing line for the demo

> "Fifteen lines of loop, four tools, one system prompt. Swap the mocked data for
> a live market feed and the news tool for a real one, and this same skeleton is
> what powers 'autonomous capital' — agents that gather, reason, and decide.
> That's the shift from AI that predicts to AI that acts."

## If something breaks live
- Backend down → `/api/health` shows it. Restart `uvicorn`.
- No key → health shows `has_key: false`. Re-export `GROQ_API_KEY`.
- Wifi flaky → data is mocked, only the LLM call needs network; Groq is one fast
  round-trip per step. Worst case, run RELIANCE which you've pre-warmed.
