"""
guardrails.py
-------------
Centralised input validation, output sanitisation, and safety rails for the
production-grade Agentic Equity Desk.

Every public function either returns a cleaned value or raises an HTTPException
so callers in app_multi.py can simply call and proceed.
"""

import json
import logging
import re
import uuid
from fastapi import HTTPException

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Input validation
# --------------------------------------------------------------------------- #
_TICKER_RE = re.compile(r"^[A-Z0-9&]{1,20}$")

def validate_ticker(ticker: str) -> str:
    """Normalise and validate an NSE ticker symbol.

    Allows 1-20 uppercase alphanumeric characters plus '&' (for M&M etc.).
    Strips whitespace, removes .NS/.BO suffixes, uppercases.
    """
    t = (ticker or "").strip().upper().replace(".NS", "").replace(".BO", "")
    if not t:
        raise HTTPException(status_code=422, detail="Ticker symbol is required.")
    if not _TICKER_RE.match(t):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid ticker '{t}'. Use 1-20 uppercase letters/digits (e.g. RELIANCE, TCS, INFY)."
        )
    return t


def validate_uuid(thread: str) -> str:
    """Validate that `thread` is a well-formed UUID (v4 hex format)."""
    t = (thread or "").strip()
    if not t:
        raise HTTPException(status_code=422, detail="Thread ID is required.")
    try:
        uuid.UUID(t)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid thread ID '{t}'. Must be a valid UUID."
        )
    return t


def validate_text(text: str, max_len: int, field_name: str = "text") -> str:
    """Validate and sanitise a free-text input (question, task, decision).

    - Strips leading/trailing whitespace
    - Collapses excessive whitespace
    - Strips control characters (except newline)
    - Enforces max length
    """
    t = (text or "").strip()
    if not t:
        raise HTTPException(status_code=422, detail=f"{field_name} cannot be empty.")
    # Strip control characters (keep newline and tab)
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", t)
    # Collapse excessive whitespace
    t = re.sub(r"[ \t]{10,}", " ", t)
    if len(t) > max_len:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} too long ({len(t)} chars, max {max_len})."
        )
    return t


_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv"}

def validate_file_extension(filename: str) -> bool:
    """Check that the uploaded file has an allowed extension."""
    if not filename:
        raise HTTPException(status_code=422, detail="Filename is required.")
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}."
        )
    return True


# --------------------------------------------------------------------------- #
# Prompt injection detection
# --------------------------------------------------------------------------- #
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"ignore\s+(all\s+)?prior\s+instructions",
    r"ignore\s+(all\s+)?above\s+instructions",
    r"disregard\s+(all\s+)?previous",
    r"you\s+are\s+now\s+a",
    r"pretend\s+you\s+are",
    r"act\s+as\s+if\s+you",
    r"forget\s+(all\s+)?your\s+(previous\s+)?instructions",
    r"new\s+system\s+prompt",
    r"override\s+system\s+prompt",
    r"reveal\s+your\s+(system\s+)?prompt",
    r"show\s+me\s+your\s+(system\s+)?prompt",
    r"what\s+is\s+your\s+system\s+prompt",
    r"\bsystem:\s",
    r"\[INST\]",
    r"<\|system\|>",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def check_prompt_injection(text: str) -> bool:
    """Return True if the text contains likely prompt-injection patterns.

    This is a lightweight blocklist — not a silver bullet, but catches the
    most common script-kiddie attempts.
    """
    return bool(_INJECTION_RE.search(text))


# --------------------------------------------------------------------------- #
# Output sanitisation
# --------------------------------------------------------------------------- #
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
_PHONE_RE = re.compile(r"\b(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}\b")
_MAX_OUTPUT = 8000


def sanitise_output(text: str) -> str:
    """Post-process an LLM response to strip accidental PII and enforce length."""
    if not text:
        return text
    # Strip email addresses
    text = _EMAIL_RE.sub("[email redacted]", text)
    # Strip Indian phone numbers
    text = _PHONE_RE.sub("[phone redacted]", text)
    # Cap length
    if len(text) > _MAX_OUTPUT:
        text = text[:_MAX_OUTPUT] + "\n\n[Response truncated]"
    return text


# --------------------------------------------------------------------------- #
# SEC / SEBI regulatory compliance guardrail
#
# Three layers, cheapest first:
#   1. Hardcoded forbidden-phrase list (regex)  — deterministic block/neutralise
#   2. Semantic compliance check via a fast LLM — catches paraphrased violations
#   3. Mandatory legal disclaimer               — appended exactly once
#
# The app's core feature is analytic BUY/HOLD/SELL verdicts, which are legal
# research opinions. What regulators forbid is *directive personal advice* and
# *promises of returns* — that is what this layer targets.
# --------------------------------------------------------------------------- #

# (pattern, replacement) — replacement keeps the sentence readable after neutralising
_FORBIDDEN_PHRASES: list[tuple[str, str]] = [
    (r"guaranteed\s+(returns?|profits?|gains?|income)",   "potential (never guaranteed) returns"),
    (r"assured\s+(returns?|profits?|gains?)",             "potential (never assured) returns"),
    (r"risk[-\s]?free\s+(returns?|profits?|investment|trade|bet)", "lower-risk (but never risk-free) investment"),
    (r"(?:can(?:'|no)?t|cannot)\s+lose",                  "could still lose"),
    (r"sure[-\s]?shot",                                   "possible"),
    (r"100\s*%\s*(safe|guaranteed|certain|sure)",         "not 100% certain"),
    (r"double\s+your\s+money",                            "seek returns (which are never assured)"),
    (r"get\s+rich\s+quick",                               "build wealth gradually"),
    (r"insider\s+(tip|tips|information|news)",            "public information"),
    (r"hot\s+(stock\s+)?tip",                             "widely discussed idea"),
    # compound directive first — otherwise the two shorter patterns below both fire
    # on "you should buy this stock now" and garble the sentence
    (r"you\s+(?:should|must|need\s+to|have\s+to)\s+(?:buy|sell)\s+this\s+(?:stock\s+)?(?:now|immediately|today)",
     "this stock may merit further research"),
    (r"you\s+(?:should|must|need\s+to|have\s+to)\s+(buy|sell)\b", r"one could consider whether to \1"),
    (r"i\s+(?:urge|advise|recommend)\s+you\s+to\s+(buy|sell)\b",  r"the analysis leans towards \1"),
    (r"buy\s+this\s+(?:stock\s+)?(?:now|immediately|today)",      "this stock may merit further research"),
    (r"sell\s+everything",                                "review the position"),
    (r"(?:will\s+|is\s+going\s+to\s+)?definitely\s+(?:will\s+)?(rise|fall|go\s+up|go\s+down|double)", r"may \1"),
    (r"(?:is\s+)?certain\s+to\s+(rise|fall|go\s+up|go\s+down|double)", r"may \1"),
    (r"(?:will|going\s+to)\s+definitely",                 "may"),
    (r"multibagger\s+guaranteed",                         "high-growth candidate (no guarantees)"),
]
_FORBIDDEN_RES = [(re.compile(p, re.IGNORECASE), r) for p, r in _FORBIDDEN_PHRASES]

DISCLAIMER = (
    "\n\n---\n"
    "*This content is for informational and educational purposes only and does not "
    "constitute investment advice, research, or a recommendation to buy or sell any "
    "security. Investments in securities markets are subject to market risks. "
    "Please consult a SEBI-registered investment adviser before making investment decisions.*"
)
# Marker used to detect that a disclaimer is already present (idempotent append)
_DISCLAIMER_MARKER = "does not constitute investment advice"


def check_forbidden_phrases(text: str) -> list[str]:
    """Return the list of forbidden phrases found in the text (empty = clean)."""
    hits = []
    for rx, _ in _FORBIDDEN_RES:
        m = rx.search(text or "")
        if m:
            hits.append(m.group(0))
    return hits


def neutralise_forbidden(text: str) -> str:
    """Deterministically rewrite every forbidden phrase into compliant wording."""
    for rx, repl in _FORBIDDEN_RES:
        text = rx.sub(repl, text)
    return text


def append_disclaimer(text: str) -> str:
    """Append the mandatory legal disclaimer exactly once."""
    if not text:
        return text
    if _DISCLAIMER_MARKER.lower() in text.lower():
        return text
    return text.rstrip() + DISCLAIMER


# --- Layer 2: semantic compliance check via a fast LLM ---------------------- #
_compliance_llm = None

def _get_compliance_llm():
    """Lazy singleton — a small fast model dedicated to compliance screening."""
    global _compliance_llm
    if _compliance_llm is None:
        import groq_pool
        _compliance_llm = groq_pool.create_llm("llama-3.1-8b-instant", temperature=0.0)
    return _compliance_llm


_COMPLIANCE_RULES = (
    "1. No guaranteed/assured/risk-free returns or promises about future prices.\n"
    "2. No directive personal advice ('you should buy X', 'buy now', 'sell everything'). "
    "Analytic opinions like 'BUY — thesis...' or 'the bull case is stronger' are ALLOWED.\n"
    "3. No claims based on insider or non-public information.\n"
    "4. No pressure tactics or urgency ('act now', 'last chance').\n"
    "5. No misrepresentation of certainty — predictions must be framed as opinion.\n"
)


def semantic_compliance_check(text: str) -> dict:
    """LLM screen of a response against financial-promotion rules.

    Returns {"compliant": bool, "issues": str}. Fails OPEN (compliant=True) if
    the LLM is unavailable — the deterministic regex layer has already run.
    """
    from langchain_core.messages import HumanMessage
    try:
        raw = _get_compliance_llm().invoke([HumanMessage(content=(
            "You are a financial-compliance screener (SEC / SEBI style rules):\n"
            f"{_COMPLIANCE_RULES}\n"
            "Screen the RESPONSE below. Reply ONLY as compact JSON: "
            '{"compliant": true/false, "issues": "short description of each violation, or empty"}\n\n'
            f"RESPONSE:\n{text[:6000]}"
        ))]).content
        obj = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        return {"compliant": bool(obj.get("compliant", True)),
                "issues": str(obj.get("issues", ""))}
    except Exception as e:
        logger.warning(f"Semantic compliance check unavailable ({e}); regex layer only.")
        return {"compliant": True, "issues": ""}


def rewrite_for_compliance(text: str, issues: str) -> str:
    """One LLM pass that rewrites a violating response into compliant wording.

    Keeps every fact, figure and the analytic verdict; only fixes the framing.
    Falls back to deterministic neutralisation if the LLM is unavailable.
    """
    from langchain_core.messages import HumanMessage
    try:
        fixed = _get_compliance_llm().invoke([HumanMessage(content=(
            "Rewrite the RESPONSE so it complies with these financial-promotion rules:\n"
            f"{_COMPLIANCE_RULES}\n"
            f"Violations found: {issues or 'forbidden promotional phrasing'}\n"
            "STRICT RULES FOR THE REWRITE:\n"
            "- KEEP every number, fact and analytic verdict already present (BUY/HOLD/SELL "
            "as an opinion is allowed); only fix the non-compliant framing.\n"
            "- NEVER add facts, numbers, prices, company names, tables or sections that are "
            "not in the original.\n"
            "- If a sentence cannot be made compliant, DELETE it rather than replace it "
            "with new content.\n"
            "- Keep the original format (markdown/tables intact) and roughly the same length "
            "or shorter. Reply with ONLY the rewritten response.\n\n"
            f"RESPONSE:\n{text[:6000]}"
        ))]).content
        return fixed.strip() if fixed and fixed.strip() else neutralise_forbidden(text)
    except Exception as e:
        logger.warning(f"Compliance rewrite unavailable ({e}); using regex neutralisation.")
        return neutralise_forbidden(text)


def enforce_compliance(text: str, semantic: bool = True, disclaimer: bool = True) -> str:
    """Full compliance pipeline for an outbound response.

    regex screen -> neutralise -> (optional) semantic LLM screen -> rewrite on
    violation -> PII sanitise -> (optional) mandatory disclaimer.
    """
    if not text:
        return text

    # Layer 1 — hardcoded forbidden phrases (deterministic)
    hits = check_forbidden_phrases(text)
    if hits:
        logger.info(f"Compliance: neutralised forbidden phrases {hits}")
        text = neutralise_forbidden(text)

    # Layer 2 — semantic screen catches paraphrased violations
    if semantic:
        verdict = semantic_compliance_check(text)
        if not verdict["compliant"]:
            logger.info(f"Compliance: semantic violation -> rewrite ({verdict['issues']})")
            text = rewrite_for_compliance(text, verdict["issues"])
            # safety net: the rewrite itself must not contain forbidden phrases
            text = neutralise_forbidden(text)

    # PII + length, then the mandatory disclaimer (after truncation so it survives)
    text = sanitise_output(text)
    if disclaimer:
        text = append_disclaimer(text)
    return text
