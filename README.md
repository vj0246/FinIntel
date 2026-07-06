# FinIntel — Agentic Equity Desk

An agentic AI platform for Indian (NSE) equity research: a fleet of specialised
LLM agents — each grounded in live market data, each gated by a human-in-the-loop
approval step, all under a shared SEC/SEBI-style compliance guardrail — sharing
one desk.

**Not investment advice.** Every generated answer carries a mandatory disclaimer;
this is a demonstration of agentic architecture, not a trading tool.

## What's on the desk

| Tab | Agent | What it does |
|---|---|---|
| 📊 **Analyst** | task agent + chat | Pick a stock, ask anything. The task agent proposes one step at a time (Approve / Redirect / Stop); the side chat is a 31-tool ReAct agent that answers instantly, self-reviews its own draft, and screens every reply for compliance. |
| 🌅 **Brief** | morning brief | A saved watchlist (per-browser) plus global market cues (US/Asia/USD-INR/Brent/Gold) and Indian indices, written up as a daily brief. |
| 🔎 **Discover** | screener | Plain-English stock screens ("IT stocks, ROE>20, PE<30, FIIs buying") parsed into a validated filter plan, swept deterministically across a curated NSE universe. |
| 💼 **Portfolio** | risk auditor | Paste holdings or upload a broker CSV. Parallel per-stock analysis, portfolio-level risk flags, a rebalance proposal gate, a paper-trading ledger, and a scenario **stress test** (2008 crisis, COVID crash, rate shocks, or custom). |
| ⚔️ **War Room** | orchestrated debate | A Chief Analyst plans the research and deploys specialists (quant / fundamental / news / risk) in parallel; a Bull and a Bear argue the case; a Judge rules — with your sign-off. |
| 🕸️ **Ecosystem** | company map | Who a company competes with, sells to, buys from and partners with — competitors priced live for a real comparison table. |
| 📑 **Report** | research report | One click orchestrates every engine (quant, financials, shareholding, ecosystem, bull/bear, desk verdict) into a single printable research note. |
| ⏳ **Backtest** | what-if engine | Lumpsum vs SIP vs a NIFTY 50 benchmark over any window, with dividends, brokerage, step-up SIPs and XIRR/CAGR/drawdown — every number computed in Python, never by the LLM. |

Sign in (email + password) to keep your **risk profile** — a five-question
suitability questionnaire — against your account; every agent judges its
answers against it (a stock's volatility/beta/drawdown vs. your stated
tolerance).

## Architecture

```
                    FRONTEND (React + Vite, code-split per tab)
                              │  Server-Sent Events
                    FastAPI (app_multi.py) — rate-limited, guarded
     ┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
   chat_agent  desk      war_room  portfolio  discover   report / brief
   (ReAct,     (LangGraph (LangGraph (LangGraph  (screen   / backtest /
   31 tools)   StateGraph, StateGraph, StateGraph universe) ecosystem /
               interrupt) interrupt) interrupt)            stress
     └──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
                              │
              market.py / quant.py / screener.py / nse.py
              (yfinance + Screener.in + NSE, cached, sample fallback)
                              │
                    guardrails.py (compliance pipeline)
                    groq_pool.py  (multi-key failover)
                    llm_cache.py  (TTL cache on repeat LLM calls)
                    session_registry.py (bounded per-thread eviction)
                    auth.py       (PBKDF2 + signed tokens, Supabase-backed)
```

**Human-in-the-loop is LangGraph-native.** The four interactive agents (desk,
war room, portfolio auditor, task agent) are each a single checkpointed
`StateGraph`. The approval gate calls LangGraph's `interrupt()` — the graph
literally pauses and checkpoints itself; your approve/reject/revise resumes it
with `Command(resume=...)`. No hand-rolled pending-request dictionaries.

**Compliance pipeline** on every LLM output: hardcoded forbidden-phrase
neutralisation → semantic LLM screen → grounded rewrite (never invents facts,
deletes what it can't fix) → PII scrub → mandatory SEBI-style disclaimer.

**Deterministic math everywhere it matters.** Quant metrics (volatility,
Sharpe, beta, RSI, drawdown), portfolio weights/concentration, stress-test
shocks, and backtest CAGR/XIRR are all computed in Python — the LLM only
interprets and narrates, it never does arithmetic.

## Backend module map

```
backend/
  app_multi.py       FastAPI app: every SSE/REST endpoint, rate-limited & guarded
  guardrails.py      input validation, prompt-injection screen, compliance pipeline
  groq_pool.py       Groq key pool with automatic per-key failover
  llm_cache.py       TTL cache for repeat-invariant LLM calls (compliance, ecosystem, beta)
  session_registry.py bounded eviction for all per-thread in-memory state
  auth.py            email/password auth, PBKDF2 hashing, signed tokens, Supabase storage

  chat_agent.py      ReAct chat agent — 31 tools, self-review, compliance
  agent_multi.py     the Desk: gather→researcher→risk→synthesize→reflect→(HITL gate)
  agent_task.py      step-by-step task agent (propose→approve/redirect/stop loop)
  war_room.py        Chief Analyst → parallel specialists → bull/bear debate → judge
  portfolio.py       broker-CSV/paste parsing, parallel per-stock audit, rebalance gate
  stress.py          deterministic factor-model portfolio stress test
  discover.py        NL query → validated filters → deterministic universe sweep
  brief.py           watchlist + global/Indian market cues → morning brief
  report.py          orchestrates every engine into one research report
  ecosystem.py       LLM relationship map + live-priced competitor table
  backtest.py        lumpsum/SIP backtest engine (CAGR, XIRR, drawdown, benchmark)
  verdict_log.py     every approved verdict logged and later re-scored (track record + P&L ledger)

  market.py          yfinance NSE data layer (quote/fundamentals/financials), cached
  quant.py           volatility, Sharpe, beta, RSI, drawdown — computed from real prices
  screener.py        Screener.in scrape: consolidated ratios, quarterly/annual/shareholding
  nse.py             NSE India data (sector P/E, 52-week range) — best-effort
  companies.py       NSE ticker/name directory for the search-bar autocomplete
  docstore.py        uploaded-document store (PDF/Word/text) for chat Q&A
  seed_data.py        offline sample data so the demo always works without live feeds
  rate_limiter.py     per-tier sliding-window rate limits
  graph_stream.py      bridges LangGraph's sync interrupt-aware stream into async SSE
```

## Run locally

```bash
cd backend
python -m venv .mumpy
.mumpy\Scripts\Activate.ps1        # Windows PowerShell; mac/linux: source .mumpy/bin/activate
pip install -r requirements.txt

# backend/.env
#   GROQ_API_KEY=gsk_xxx[,gsk_yyy,...]     comma-separated keys = automatic failover
#   AUTH_SECRET=<any long random string>   keeps sign-ins valid across restarts
#   SUPABASE_URL=...                       optional — persists accounts across redeploys
#   SUPABASE_SERVICE_KEY=...               optional — falls back to a local users.json
#   LANGCHAIN_TRACING_V2=false             optional LangSmith tracing

uvicorn app_multi:app --reload --port 8000
```
Health check: http://localhost:8000/api/health

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173
```

## Notes

- **NSE symbols**: type any ticker (RELIANCE, TCS, INFY, HDFCBANK, …) — the
  autocomplete and every agent normalise it. A handful of seed tickers work
  fully offline as a sample-data fallback if live feeds are unreachable.
- **Live vs sample data** is always labelled in the UI — sample data is never
  silently presented as live.
- **Rate limits** are light-touch by design: every action is comfortably
  runnable several times a minute; only sustained hammering is blocked.
- See `DEPLOY.md` for the Render + Vercel deployment guide.
