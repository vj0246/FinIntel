"""
groq_pool.py
------------
Groq API key pool with automatic fallback.

Set GROQ_API_KEY to a comma-separated list of keys:
    GROQ_API_KEY=gsk_abc123,gsk_def456,gsk_ghi789

When a key hits its rate limit or fails, the next key in the list is tried
automatically. Uses LangChain's built-in `with_fallbacks()` so it works
seamlessly with .invoke(), .ainvoke(), .astream(), create_react_agent(), and
LangGraph StateGraph — no custom wrappers needed.

If only one key is provided (or no commas), it behaves exactly like before.
"""

import os
import logging
from dotenv import load_dotenv
from langchain_groq import ChatGroq

# Load .env so GROQ_API_KEY is available
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

logger = logging.getLogger(__name__)


def _parse_keys() -> list[str]:
    """Parse comma-separated API keys from GROQ_API_KEY env var."""
    raw = os.environ.get("GROQ_API_KEY", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        logger.warning("GROQ_API_KEY is empty — LLM calls will fail.")
        return [""]
    if len(keys) > 1:
        logger.info(f"Groq key pool: {len(keys)} keys loaded (key rotation enabled).")
    return keys


_KEYS = _parse_keys()


def create_llm(model: str, temperature: float = 0.3):
    """Create a ChatGroq LLM with automatic key fallback.

    If multiple keys are configured, returns a RunnableWithFallbacks that
    tries each key in order. If only one key, returns a plain ChatGroq.

    Compatible with:
      - llm.invoke() / llm.ainvoke()
      - create_react_agent(llm, ...)
      - StateGraph nodes that call llm.invoke()
      - llm.astream()
    """
    if len(_KEYS) <= 1:
        return ChatGroq(model=model, temperature=temperature, api_key=_KEYS[0])

    # Build one ChatGroq per key
    llms = [ChatGroq(model=model, temperature=temperature, api_key=k) for k in _KEYS]

    # Primary = first key; fallbacks = rest.  LangChain tries them in order.
    primary = llms[0]
    fallbacks = llms[1:]
    return primary.with_fallbacks(fallbacks)


def key_count() -> int:
    """How many API keys are in the pool."""
    return len(_KEYS)
