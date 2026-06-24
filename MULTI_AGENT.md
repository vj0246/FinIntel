# Multi-Agent Desk (HITL) — Run + Walkthrough

The fascinating demo: a desk of three agents that researches, weighs risk, drafts
a call **plus a proposed action**, then **pauses for your sign-off** (LangGraph
`interrupt`) before acting. LangSmith traces every step.

This is now the headline demo. The simple single-loop version is still in the
repo (`agent.py`, `App_simple.jsx`) as a fallback.

## Files
```
backend/
  agent_multi.py   the StateGraph: gather → researcher → risk → synthesize → human_gate → finalize
  app_multi.py     FastAPI: /api/analyze (start, stops at gate) + /api/resume (approve/reject/revise)
frontend/
  src/App.jsx      HITL UI: streams agents, shows approval card, resumes
```

## Run

```bash
cd backend
source .venv/bin/activate
pip install -r requirements.txt -r requirements-langgraph.txt
export GROQ_API_KEY=gsk_xxx

# optional but great for the talk — turns on LangSmith tracing:
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY=ls__xxx
export LANGCHAIN_PROJECT=mumpy-agent

uvicorn app_multi:app --reload --port 8000
```
Health: http://localhost:8000/api/health → `has_key` and `langsmith` should be true.

```bash
cd frontend && npm install && npm run dev   # http://localhost:5173
```

Flow on screen: pick stock → **Run the desk** → three agents stream in → an
**Awaiting your sign-off** card appears with the verdict + proposed action →
**Approve & act** / **Reject** / type feedback + **Revise** (loops back). If
LangSmith is on, open smith.langchain.com to show the full trace.

## Architecture (what to say)

State (`DeskState`) is a typed dict every node reads/writes. Edges are fixed
except one conditional edge after the gate.

```
START → gather → researcher → risk → synthesize → human_gate → finalize → END
                                          ▲              │
                                          └─── revise ◄──┘
```

- **gather** — plain node, no LLM. Pulls price/news/fundamentals (mock data).
- **researcher / risk / synthesize** — three focused LLM agents, each its own
  role prompt. synthesize returns JSON `{verdict, thesis, action}`.
- **human_gate** — calls `interrupt({recommendation, action})`. The graph
  literally stops; control returns to the web layer. On `resume`, the value the
  human sent comes back from `interrupt()`.
- **conditional edge** — approve → finalize, reject → rejected, anything else →
  back to synthesize with the feedback (the revise loop).
- **checkpointer** (`MemorySaver`) — REQUIRED for interrupt/resume; it persists
  state under a `thread_id` between the two HTTP requests.

## 8-minute code walkthrough (script, your voice)

Run the desk live first (30s). Approve once so they see the full arc. Then code.

**1. State + graph shape — 1:30** (`agent_multi.py`, bottom `_build`)
> "Instead of one loop, I declared a graph. `DeskState` is shared memory; nodes
> are steps; edges are the flow. Read it top to bottom: gather, researcher, risk,
> synthesise, human gate, finalise. One conditional edge after the gate — that's
> the only branching."

**2. The agents — 2:00** (the three node functions)
> "Each agent is just a focused LLM call with a role. Researcher pulls out bull
> and bear signals. Risk names the single biggest downside. Synthesiser merges
> them and returns JSON — verdict, thesis, and a concrete action. Small, single-
> responsibility agents — easy to reason about, easy to swap."

**3. The human gate — 2:30** (`human_gate` + `interrupt`)  ← the heart
> "This is the whole point. `interrupt()` stops the graph mid-run and hands the
> proposal back to me — the human. The agent doesn't act; it *asks*. When I
> resume, whatever I sent — approve, reject, or feedback — comes back out of
> `interrupt()`, and the conditional edge routes on it. Feedback loops back to
> the synthesiser to try again. That's human-in-the-loop as a first-class step,
> not an afterthought. And it needs a checkpointer, because the run is paused
> across two separate HTTP requests — the graph's state is saved under a thread
> id and restored on resume."

**4. Two-phase streaming — 1:30** (`app_multi.py` + `start_run`/`resume_run`)
> "Because the run pauses, the API is two endpoints. `/analyze` streams agents
> until the gate, then emits an approval request and stops. `/resume` picks the
> same thread back up and streams the outcome. Both are Server-Sent Events, so
> the browser sees each agent the moment it finishes."

**5. Observability — 0:30** (LangSmith)
> "Set three env vars and every node and LLM call is traced in LangSmith — inputs,
> outputs, latency, cost. For a multi-agent system that's how you actually debug
> it." (Show the trace if online.)

> Close: "Three agents, one human gate, full tracing. That's the responsible
> shape of agentic finance — the agent proposes, a human signs off, then it acts."

## Practical Q&A (the new ones)

- **Why a graph not the raw loop?** Branching + a pause point. The revise loop
  and the human gate are edges; a graph expresses that cleanly. The raw loop is
  still here for the simpler story.
- **What is `interrupt()` really?** It raises a special signal LangGraph catches,
  saves state via the checkpointer, and returns control. `Command(resume=value)`
  re-enters at the same spot with your value.
- **Why a thread id?** It's the key the checkpointer uses to find the paused run.
  Two HTTP requests, one conversation — the id links them.
- **Latency?** Four LLM calls (3 agents + synthesise) on Groq ≈ 2-4s, then it
  waits on *you*. Multi-agent is more calls than the single loop — that's the
  trade for clearer roles.
- **Is the action real?** No — "executes" is simulated. The pattern (propose →
  approve → act) is the lesson; wiring a real action behind the gate is the same
  shape, with real stakes and real guardrails.
- **MemorySaver in production?** Swap for a persistent checkpointer (Postgres/
  Redis) so paused runs survive restarts.
- **Could agents run in parallel?** Yes — LangGraph supports parallel branches.
  I kept them sequential because each feeds the next (research → risk → synth).

## Speech changes vs the old script
Your `SPEECH.md` demo section now describes this desk instead of the single loop.
Swap the "code review" beats for the 5 above. Everything else (bio, three eras,
close) is unchanged. Ask me and I'll regenerate SPEECH.md to match.
```
