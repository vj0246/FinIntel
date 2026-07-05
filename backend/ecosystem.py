"""
ecosystem.py
------------
Company Ecosystem map: who a company competes with, sells to, buys from and
partners with — plus revenue segments, moat and key risks.

The relationship map comes from the LLM's knowledge of well-known, factual
business relationships (grounded with the company's real sector/industry and
current headlines); listed competitors are then priced LIVE so the peer table
is real numbers, not hallucinated ones. The narrative summary passes through
the full compliance pipeline (forbidden phrases -> semantic screen -> SEBI
disclaimer). All money in ₹.
"""

import asyncio
import json
import re

from langchain_core.messages import HumanMessage

import groq_pool
import market
import guardrails as gr

MODEL = "openai/gpt-oss-120b"
_llm = None

_TICKER_RE = re.compile(r"^[A-Z0-9&\-]{1,20}$")
_MAX_LIST = 6
_PEER_LIMIT = 4
_CONCURRENCY = 3


def _get_llm():
    global _llm
    if _llm is None:
        _llm = groq_pool.create_llm(MODEL, temperature=0.2)
    return _llm


def _json_block(raw: str) -> dict:
    return json.loads(raw[raw.find("{"):raw.rfind("}") + 1])


def _clean_list(items, fields=("name", "note"), cap=_MAX_LIST) -> list:
    """Keep only dict entries with a name; truncate strings so a runaway LLM
    can't flood the UI."""
    out = []
    for it in items or []:
        if not isinstance(it, dict) or not str(it.get("name", "")).strip():
            continue
        rec = {}
        for f in fields:
            v = str(it.get(f, "") or "").strip()
            rec[f] = v[:200]
        out.append(rec)
        if len(out) >= cap:
            break
    return out


def build_map(ticker: str) -> tuple:
    """(profile, ecosystem) for one NSE company. Raises on bad ticker/no data."""
    b = market.bundle(ticker)
    f = b.get("fundamentals", {})
    profile = {
        "ticker": b["ticker"], "name": b.get("name", b["ticker"]),
        "sector": f.get("sector"), "industry": f.get("industry"),
        "market_cap_cr": f.get("market_cap_cr"), "pe": f.get("pe"),
        "price": (b.get("quote") or {}).get("price"),
        "source": b.get("source", "sample"),
    }
    heads = "\n".join(f"- {n['headline']}" for n in b.get("news", [])[:6] if n.get("headline"))
    raw = _get_llm().invoke([HumanMessage(content=(
        "You are an equity research analyst mapping an Indian company's business "
        f"ecosystem.\nCOMPANY: {profile['name']} (NSE: {profile['ticker']})"
        f"{', sector: ' + profile['sector'] if profile.get('sector') else ''}"
        f"{', industry: ' + profile['industry'] if profile.get('industry') else ''}\n"
        f"RECENT HEADLINES:\n{heads or '(none)'}\n\n"
        "Reply ONLY as compact JSON with these keys (max 6 entries per list). Include "
        "ONLY relationships you are confident are real and well-known — OMIT anything "
        "uncertain; never invent company names or numbers:\n"
        '{"competitors":[{"ticker":"<NSE symbol, no .NS, or empty string if unlisted>",'
        '"name":"...","note":"why they compete"}],\n'
        ' "customers":[{"name":"<major customer or customer segment>","note":"..."}],\n'
        ' "suppliers":[{"name":"<key supplier / vendor or input source>","note":"..."}],\n'
        ' "partners":[{"name":"<JV / alliance / technology partner>","note":"..."}],\n'
        ' "subsidiaries":[{"name":"...","note":"what it does"}],\n'
        ' "revenue_segments":[{"segment":"...","approx_share_pct":<number or null>}],\n'
        ' "key_inputs":["<raw material / cost driver>", ...],\n'
        ' "moat":"one sentence on the durable advantage, or empty",\n'
        ' "key_risks":["<risk>", ...]}\n'
        "Indian/NSE context. Money in ₹ only. No investment advice."
    ))]).content
    obj = _json_block(raw)

    eco = {
        "competitors": [], "customers": _clean_list(obj.get("customers")),
        "suppliers": _clean_list(obj.get("suppliers")),
        "partners": _clean_list(obj.get("partners")),
        "subsidiaries": _clean_list(obj.get("subsidiaries")),
        "revenue_segments": [], "key_inputs": [], "moat": "", "key_risks": [],
    }
    for c in _clean_list(obj.get("competitors"), fields=("ticker", "name", "note")):
        t = c.get("ticker", "").strip().upper().replace(".NS", "").replace(".BO", "")
        c["ticker"] = t if (_TICKER_RE.match(t) and t != profile["ticker"]) else ""
        eco["competitors"].append(c)
    for s in obj.get("revenue_segments") or []:
        if isinstance(s, dict) and str(s.get("segment", "")).strip():
            pct = s.get("approx_share_pct")
            eco["revenue_segments"].append({
                "segment": str(s["segment"]).strip()[:120],
                "approx_share_pct": round(float(pct), 1) if isinstance(pct, (int, float)) else None})
        if len(eco["revenue_segments"]) >= _MAX_LIST:
            break
    eco["key_inputs"] = [str(x).strip()[:120] for x in (obj.get("key_inputs") or [])
                         if str(x).strip()][:_MAX_LIST]
    eco["moat"] = str(obj.get("moat", "") or "").strip()[:300]
    eco["key_risks"] = [str(x).strip()[:200] for x in (obj.get("key_risks") or [])
                        if str(x).strip()][:4]
    return profile, eco


def _peer_snapshot(sym: str) -> dict:
    """Live valuation snapshot for one listed competitor."""
    b = market.bundle(sym)
    f = b.get("fundamentals", {})
    return {"ticker": b["ticker"], "name": b.get("name", b["ticker"]),
            "price": (b.get("quote") or {}).get("price"),
            "change_6m_pct": (b.get("price") or {}).get("change_pct"),
            "pe": f.get("pe"), "pb": f.get("pb"),
            "market_cap_cr": f.get("market_cap_cr"), "roe_pct": f.get("roe_pct"),
            "dividend_yield_pct": f.get("dividend_yield_pct"),
            "source": b.get("source", "sample")}


def ecosystem_json(ticker: str) -> str:
    """Compact ecosystem map as JSON — used as a chat-agent tool."""
    profile, eco = build_map(ticker)
    return json.dumps({"company": profile, "ecosystem": eco}, default=str)


async def analyze(ticker: str, thread_id: str):
    """SSE generator: profile -> map -> live peer rows -> compliance-screened summary."""
    yield {"type": "phase", "text": f"Mapping {ticker.upper()}'s business ecosystem…"}
    try:
        profile, eco = await asyncio.wait_for(asyncio.to_thread(build_map, ticker), timeout=90)
    except Exception as e:
        yield {"type": "error", "text": f"Couldn't build the ecosystem map: {e}"}
        return
    yield {"type": "profile", **profile}
    yield {"type": "map", "ecosystem": eco}

    # Price the listed competitors live, streamed as each fetch completes.
    peers = [c["ticker"] for c in eco["competitors"] if c.get("ticker")][:_PEER_LIMIT]
    peer_rows = []
    if peers:
        yield {"type": "phase", "text": f"Pricing {len(peers)} listed competitors live…"}
        # Include the company itself so the table has a baseline row.
        syms = [profile["ticker"]] + peers
        sem = asyncio.Semaphore(_CONCURRENCY)

        async def fetch(sym):
            async with sem:
                return await asyncio.to_thread(_peer_snapshot, sym)

        for coro in asyncio.as_completed([fetch(s) for s in syms]):
            try:
                row = await coro
                row["is_self"] = row["ticker"] == profile["ticker"]
                peer_rows.append(row)
                yield {"type": "peer", **row}
            except Exception:
                continue

    # Narrative summary — grounded in the map + the REAL peer numbers just fetched.
    yield {"type": "phase", "text": "Writing the ecosystem read…"}
    try:
        raw = await asyncio.wait_for(asyncio.to_thread(lambda: _get_llm().invoke([HumanMessage(content=(
            "Write a short ecosystem read (3 tight paragraphs, markdown) for "
            f"{profile['name']} (NSE: {profile['ticker']}) using ONLY the data below — "
            "never invent numbers or company names. All money in ₹ (crore). "
            "1) Where the company sits in its value chain (customers, suppliers, key inputs). "
            "2) Competitive standing vs the peer table (cite the actual PE/market-cap figures). "
            "3) Key dependencies and risks. Analytical tone; no directive advice; no disclaimers.\n\n"
            f"PROFILE:\n{json.dumps(profile, default=str)}\n\n"
            f"ECOSYSTEM MAP:\n{json.dumps(eco, default=str)}\n\n"
            f"LIVE PEER TABLE:\n{json.dumps(peer_rows, default=str)}"
        ))]).content), timeout=60)
        summary = gr.enforce_compliance(raw)
    except Exception:
        summary = gr.append_disclaimer(
            "The ecosystem map above is the analysis; a narrative summary couldn't be generated right now.")
    yield {"type": "summary", "text": summary}
