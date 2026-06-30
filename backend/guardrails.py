"""
guardrails.py
-------------
Centralised input validation, output sanitisation, and safety rails for the
production-grade Agentic Equity Desk.

Every public function either returns a cleaned value or raises an HTTPException
so callers in app_multi.py can simply call and proceed.
"""

import re
import uuid
from fastapi import HTTPException


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
