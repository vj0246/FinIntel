"""
stress.py
---------
Portfolio STRESS-TEST agent: "what happens to my portfolio if crude spikes,
the rupee falls, rates rise, the market crashes?"

Every shocked number is DETERMINISTIC Python:

  holding move % = beta x market_shock
                 + sector_sensitivity(crude)  x crude_shock
                 + sector_sensitivity(inr)    x inr_shock
                 + sector_sensitivity(rates)  x rate_shock_bps/100
                 + explicit sector shock (scenario-specific, e.g. "IT -25%")

Beta comes from real 6-month price history (quant.py, cached 12h). Sector
sensitivities are a fixed, documented matrix — coarse by design, stated in the
UI. The LLM only narrates the computed damage; the suitability verdict against
the user's risk profile is deterministic too. All money ₹.
"""

import asyncio
import json

from langchain_core.messages import HumanMessage

import groq_pool
import guardrails as gr
import llm_cache
import portfolio as pf

MODEL = "openai/gpt-oss-120b"
_llm = None
_CONCURRENCY = 4

# Max tolerable one-shot portfolio drawdown per risk profile (%, deterministic).
PROFILE_DD = {"conservative": 10, "balanced": 20, "aggressive": 35}


def _get_llm():
    global _llm
    if _llm is None:
        _llm = groq_pool.create_llm(MODEL, temperature=0.2)
    return _llm


# --------------------------------------------------------------------------- #
# Sector buckets + factor sensitivity matrix
# (impact in % of stock price per +1% factor move; rates per +100bps)
# --------------------------------------------------------------------------- #
_BUCKETS = (
    ("it",        ("informat", "software", " it", "it ", "technology")),
    ("pharma",    ("pharma", "health", "drug", "hospital")),
    ("bank",      ("bank",)),
    ("nbfc",      ("nbfc", "finance", "financial services", "insurance")),
    ("auto",      ("auto",)),
    ("oil_gas",   ("oil", "gas", "petro", "refiner", "energy")),
    ("metals",    ("metal", "mining", "steel", "aluminium")),
    ("fmcg",      ("fmcg", "consumer", "food", "beverage")),
    ("realty",    ("realty", "real estate", "construction")),
    ("aviation",  ("aviation", "airline", "transport")),
    ("cement",    ("cement",)),
    ("telecom",   ("telecom",)),
    ("chemicals", ("chemical", "fertiliz", "agro")),
    ("power",     ("power", "utilit", "electric")),
)

#            crude+1%  inr+1% (rupee weakens)  rates+100bps
_SENS = {
    "it":        (0.00,  +0.30,  -0.5),
    "pharma":    (0.00,  +0.20,  -0.5),
    "bank":      (-0.02, -0.05,  -1.0),
    "nbfc":      (-0.02, -0.05,  -5.0),
    "auto":      (-0.08, -0.05,  -3.0),
    "oil_gas":   (+0.10, -0.10,  -0.5),
    "metals":    (+0.03, +0.10,  -1.0),
    "fmcg":      (-0.05, -0.05,  -0.5),
    "realty":    (-0.02, -0.05,  -6.0),
    "aviation":  (-0.25, -0.20,  -2.0),
    "cement":    (-0.08, -0.02,  -2.0),
    "telecom":   (-0.02, -0.05,  -1.5),
    "chemicals": (-0.05, +0.10,  -1.0),
    "power":     (-0.03, -0.02,  -2.0),
    "other":     (-0.02,  0.00,  -1.0),
}

# Preset scenarios: (market %, crude %, inr %, rates bps, {bucket: extra %}, label)
SCENARIOS = {
    "gfc_2008":    (-35, -30, +12, -150, {}, "2008-style global financial crisis"),
    "covid_crash": (-30, -50, +5, -100, {"aviation": -20, "realty": -10},
                    "COVID-March-2020-style crash"),
    "taper_2013":  (-10, +5, +15, +150, {"nbfc": -5, "realty": -8},
                    "2013 taper-tantrum: rupee rout + rate spike"),
    "crude_spike": (-5, +40, +4, +25, {}, "oil shock: Brent +40%"),
    "it_winter":   (-5, 0, +3, 0, {"it": -25}, "US tech-spending freeze hits Indian IT"),
    "rate_shock":  (-6, 0, +2, +100, {}, "RBI surprise +100bps"),
}


def _bucket(sector) -> str:
    s = (sector or "").lower()
    for name, keys in _BUCKETS:
        if any(k in s for k in keys):
            return name
    return "other"


def _beta(ticker: str):
    """Real beta vs NIFTY 50 (quant.py), cached 12h. None -> assume 1.0."""
    ck = llm_cache.key("beta", ticker.upper())
    cached = llm_cache.get(ck)
    if cached is not None:
        return cached
    beta = None
    try:
        import quant
        beta = quant.metrics(ticker).get("beta_vs_nifty50")
    except Exception:
        pass
    llm_cache.put(ck, beta, ttl=12 * 3600)
    return beta


def shock_holding(row: dict, market_pct, crude_pct, inr_pct, rate_bps, sector_shocks) -> dict:
    """Deterministic shocked value for one (already-priced) holding."""
    bucket = _bucket(row.get("sector"))
    beta = _beta(row["ticker"])
    beta_used = beta if isinstance(beta, (int, float)) else 1.0
    c, i, r = _SENS[bucket]
    move = (beta_used * market_pct
            + c * crude_pct
            + i * inr_pct
            + r * rate_bps / 100
            + sector_shocks.get(bucket, 0))
    move = max(-90.0, min(50.0, move))
    value = row.get("value") or 0
    shocked = value * (1 + move / 100)
    return {"ticker": row["ticker"], "sector": row.get("sector") or "—", "bucket": bucket,
            "beta": beta, "value": round(value), "est_move_pct": round(move, 1),
            "shocked_value": round(shocked), "loss": round(shocked - value)}


async def run(thread_id: str, scenario: str, custom: dict, profile: str):
    sess = pf._sessions.get(thread_id)
    if not sess or not sess.get("holdings"):
        yield {"type": "error", "text": "Load your holdings on this page first, then stress-test."}
        return

    if scenario == "custom":
        market_pct = max(-60.0, min(30.0, float(custom.get("market") or 0)))
        crude_pct = max(-60.0, min(80.0, float(custom.get("crude") or 0)))
        inr_pct = max(-15.0, min(25.0, float(custom.get("inr") or 0)))
        rate_bps = max(-300.0, min(300.0, float(custom.get("rates") or 0)))
        sector_shocks, label = {}, "custom scenario"
    elif scenario in SCENARIOS:
        market_pct, crude_pct, inr_pct, rate_bps, sector_shocks, label = SCENARIOS[scenario]
    else:
        yield {"type": "error", "text": f"Unknown scenario '{scenario}'."}
        return

    yield {"type": "scenario", "name": scenario, "label": label,
           "market_pct": market_pct, "crude_pct": crude_pct,
           "inr_pct": inr_pct, "rate_bps": rate_bps, "sector_shocks": sector_shocks}

    # Priced rows: reuse the audit's rows when present, else fetch now (parallel).
    rows = [r for r in sess.get("rows") or [] if not r.get("error") and r.get("value")]
    if not rows:
        yield {"type": "phase", "text": "Pricing holdings live…"}
        sem = asyncio.Semaphore(_CONCURRENCY)

        async def fetch(h):
            async with sem:
                return await asyncio.to_thread(pf._fetch_holding, h)

        fetched = await asyncio.gather(*[fetch(h) for h in sess["holdings"]])
        rows = [r for r in fetched if not r.get("error") and r.get("value")]
        sess["rows"] = list(fetched)
    if not rows:
        yield {"type": "error", "text": "No holdings could be priced right now — try again."}
        return

    # Betas fetch in parallel threads (each is cached after first run).
    yield {"type": "phase", "text": f"Shocking {len(rows)} holdings…"}
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def shock(r):
        async with sem:
            return await asyncio.to_thread(shock_holding, r, market_pct, crude_pct,
                                           inr_pct, rate_bps, sector_shocks)

    shocked = []
    for coro in asyncio.as_completed([shock(r) for r in rows]):
        s = await coro
        shocked.append(s)
        yield {"type": "shock", **s}

    total = sum(s["value"] for s in shocked)
    total_shocked = sum(s["shocked_value"] for s in shocked)
    dd_pct = round((total_shocked / total - 1) * 100, 1) if total else 0
    worst = min(shocked, key=lambda s: s["loss"]) if shocked else None
    result = {"total_value": round(total), "shocked_value": round(total_shocked),
              "total_loss": round(total_shocked - total), "portfolio_move_pct": dd_pct,
              "worst_position": {"ticker": worst["ticker"], "loss": worst["loss"],
                                 "est_move_pct": worst["est_move_pct"]} if worst else None}

    # Deterministic suitability verdict vs the user's risk profile.
    profile = gr.validate_profile(profile)
    if profile:
        tolerance = PROFILE_DD[profile]
        result["profile"] = profile
        result["tolerance_pct"] = tolerance
        result["within_tolerance"] = abs(min(dd_pct, 0)) <= tolerance
    yield {"type": "impact", **result}

    # Narrative — grounded ONLY in the computed shock table.
    yield {"type": "phase", "text": "Writing the damage report…"}
    suit = ""
    if profile:
        suit = (f"\nUSER RISK PROFILE: {profile} (max tolerable one-shot drawdown "
                f"{result['tolerance_pct']}%). The computed move "
                f"{'BREACHES' if not result['within_tolerance'] else 'stays within'} that tolerance "
                "— state this explicitly and, if breached, name which holdings drive the breach.")
    try:
        raw = await asyncio.wait_for(asyncio.to_thread(lambda: _get_llm().invoke([HumanMessage(content=(
            f"A portfolio was stress-tested against: {label} "
            f"(market {market_pct:+}%, crude {crude_pct:+}%, USD/INR {inr_pct:+}%, rates {rate_bps:+}bps). "
            "Write a short DAMAGE REPORT (markdown, max 3 paragraphs) from ONLY the computed "
            "numbers below — which holdings get hit hardest and why (beta/sector), which hold up, "
            "and the portfolio-level read. Cite the actual ₹ figures. Note this is a coarse "
            "factor model, not a prediction. No directive advice.\n" + suit + "\n\n"
            f"PER-HOLDING SHOCKS:\n{json.dumps(shocked, default=str)}\n\n"
            f"PORTFOLIO IMPACT:\n{json.dumps(result, default=str)}"
        ))]).content), timeout=60)
        yield {"type": "narrative", "text": gr.enforce_compliance(raw)}
    except Exception:
        yield {"type": "narrative",
               "text": gr.append_disclaimer("The shocked values above are the full result; "
                                            "a narrative couldn't be generated right now.")}
