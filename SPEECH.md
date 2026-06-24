# Speech Script, ~10 Minutes (matches the 4 slide deck)
### From Algorithms to Autonomous Capital, Mumbai Python Developers Group, Vivaan Jain

Stage directions in [brackets]. Memorise beats, not words. **Bold = land it.** Pause at **//**.

---

## 1, Hook + About me, 1:15  [Slide 1, then 2]

[Slide 1. One beat.]

Good evening. Until recently, AI in finance had one job, to **predict**. This year it learned to **act**. Tonight I show you what that means, and run a live multi agent system that does it, with a human still holding the wheel.

[Slide 2.]

Quick on me. I'm Vivaan, Computer Engineering at **DJ Sanghvi**. I'm on the **Synapse** ML committee, I research **credit scoring models** with **ACM**, and I intern at **Zeex AI** and **Internovo Ventures**. Finance plus Python plus AI is the seam this talk lives in. [QR goes to my portfolio.]

---

## 2, AI in finance, 1:00  [Slide 3]

AI already runs through finance. Credit scoring, fraud detection, research and document analysis, forecasting. [gesture left card.]

What is changing is how far it goes. [right card.] First we **predicted**, models that forecast and classify. Then we learned to **generate**, models that read, write, and explain. Now we **act**, agents that plan and take steps. // The frontier, and tonight's topic, is that third one, done responsibly.

---

## 3, What is an agent, 1:15  [Slide 4]

Before the demo, one slide on the idea. [Slide 4.]

An agent is not a chatbot. It is an **LLM that can plan, use tools, and act in a loop**. [point to the boxes.] Three parts: the **LLM** that reasons, **memory** that holds context, a **planner** that picks the next step. And **tools**, the functions it can call, pull data, hit an API, run code, search.

It works as a **loop**. [bottom band.] Think, act by calling a tool, observe the result, then repeat, until it is done and answers. // That loop is the whole thing. Everything I'm about to show is that picture, in Python.

---

## 4, Demo, run live, 0:30  [switch to browser]

[Browser loaded. Pick RELIANCE. Run the desk. Talk over the stream.]

This is a small **desk of agents**. A Researcher pulls data and finds the bull and bear signals. A Risk agent flags the biggest downside. A Synthesiser writes a verdict **and a proposed action**. Then it **stops**. It will not act until I approve. That pause is the point.

[Approval card appears. Pause. Approve, or type feedback to revise.]

All of it is a LangGraph. Let me open it.

---

## 5, Code walkthrough, 4:30  [Editor]

[Open `agent_multi.py`, scroll to `_build`.]

**The graph, 1:15.** Not one big loop, a graph. Shared state, nodes as steps, edges as flow. Read top to bottom: gather, researcher, risk, synthesise, human gate, finalise. // One conditional edge, right after the gate. Only branch in the whole thing.

[The three agent functions.]

**The agents, 1:00.** Each agent is a focused LLM call with a role. Researcher extracts signals. Risk names the single biggest downside. Synthesiser merges them and returns JSON, verdict, thesis, and an action. Small, single job agents, easy to swap.

[`human_gate` and `interrupt`. Slow down, the heart.]

**The human gate, 1:15.** This is why it matters. `interrupt()` **stops the graph mid run** and hands the proposal back to me. The agent does not act, it asks. On resume, whatever I sent, approve, reject, or feedback, comes back out of `interrupt()`, and the edge routes on it. Feedback loops back to the synthesiser to try again. // Human in the loop as a real step, not a bolt on. It needs a checkpointer, because the run is paused across two requests, state saved under a thread id and restored on resume.

[`app_multi.py` briefly.]

**Streaming and tracing, 1:00.** Because it pauses, the API is two endpoints. `/analyze` streams agents until the gate, then stops. `/resume` picks the same thread up and streams the outcome. Both Server Sent Events, so the browser sees each agent the moment it finishes. And set three env vars, every node and LLM call is traced in **LangSmith**, inputs, outputs, latency, cost. That is how you debug a multi agent system.

---

## 6, Close, 0:45  [back to Slide 4 or browser]

The arc, **predict, generate, act**, and we crossed into act.

Leave you with the real question. When agents gather, reason, and decide on their own, the hard part stops being the model, it becomes the **guardrails**. **Who signs off on the verdict?** Tonight, on purpose, a human did.

Mocked data, advisory only, not investment advice. I showed the mechanism, and now you have seen there is no magic in it, just a graph, a few agents, and a pause for a human.

Thank you, Vivaan Jain. Bring the hard questions, cost, hallucination, going live.

---

### Pace check
- ~2:30 starting slide 4 (agent anatomy).
- ~4:00 desk running on screen.
- ~9:00 on the close.

### If long, cut
- Slide 3 to one line: predict, generate, act, and we are at act.
- Drop `app_multi.py` beat, SSE is one sentence over the gate.
- **Never cut the human gate beat.**
