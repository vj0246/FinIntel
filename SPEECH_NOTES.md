# Speech Notes — Intro, Finance Overview, Close

Total talk: 10–15 min. Demo eats ~8. This covers the rest.

## [0:00 – 2:00] About you

Keep it tight, land one hook.

- Name, what you do, why you're at the intersection of finance + Python/AI.
- One line of credibility (a project, a role, a thing you've shipped).
- **Hook to pivot into the topic:**
  > "Here's the shift I want to talk about tonight: until recently, AI in finance
  > *predicted*. This year, AI *acts*. Let me show you what that means — and then
  > I'll show you one running."

Don't over-rehearse the bio. Energy > completeness.

## [2:00 – 4:00] AI in finance — the three eras

Three beats, one breath each. Put this on a single slide.

1. **Predictive AI (the last decade).** Narrow models, one job: forecast a price,
   flag a fraudulent transaction, score a loan. Powerful, but it answers one
   question and stops. You ask, it scores.

2. **Generative AI (now mainstream).** Models that read filings, summarise
   earnings calls, explain a portfolio in English. They produce, not just score.

3. **Agentic AI (the frontier — tonight's topic).** Models that **plan and act**:
   pick what data to pull, call tools, reason over results, decide a next step,
   and only then answer. This is where "autonomous capital" comes from — systems
   that don't just predict the market, they *operate* in it.

> "The jump from era two to era three is small in code and huge in consequence.
> It's mostly a loop and some tools. Let me show you."

→ go straight into running the demo.

**One honest caveat to say out loud (builds trust):**
> "To be clear — autonomy in finance raises real questions: accountability,
> risk, who's liable when an agent acts. My demo is advisory and uses mocked
> data. I'm showing the *mechanism*, not pitching a trading bot."

## [12:00 – 15:00] Close + Q&A

Tie back to the slide title — "From Algorithms to Autonomous Capital."

- Recap in one sentence: predict → generate → act.
- The provocative question to leave them with:
  > "When an agent can gather, reason, and decide on its own, the hard part stops
  > being the model and starts being the guardrails. Who signs off on the
  > verdict?"
- Invite questions. Have `agent.py` open as the backdrop — people will ask about
  the loop, the cost, hallucinations, and going live with real data. Your
  walkthrough Q&A answers cover all of these.

## Timing cheat-sheet
| Segment | Target | Hard cap |
|---|---|---|
| About you | 2:00 | 2:30 |
| Three eras | 2:00 | 2:30 |
| Demo (run + code) | 8:00 | 9:00 |
| Close + Q&A | 2:00 | open |

If you're running long, the three-eras section is where you trim — collapse to
"predict → generate → act" in 45 seconds and move to the demo.
