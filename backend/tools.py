"""
tools.py
--------
The agent's "hands". Four tools it can call:

  get_price_history   -> recent price action
  get_news            -> latest headlines
  get_fundamentals    -> valuation + financial health
  generate_summary    -> a GENERATIVE tool. The agent calls an LLM *as a tool*
                         to turn everything it gathered into a thesis.

Two ideas a Python crowd will care about here:
  1. Pydantic models describe each tool's arguments -> we get the JSON schema
     the LLM needs *for free*, and runtime validation for free too.
  2. A registry dict maps tool name -> callable, so dispatch is one line
     instead of a wall of if/elif.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from groq import Groq

# Load backend/.env into os.environ BEFORE any client reads a key.
# tools.py is imported by every entry point, so this one call covers all of them
# (GROQ_API_KEY, LANGCHAIN_API_KEY, LANGCHAIN_TRACING_V2, LANGCHAIN_PROJECT, ...).
load_dotenv(Path(__file__).parent / ".env")

DATA_DIR = Path(__file__).parent / "data"

# A plain Groq client used *inside* the generative tool.
# (The agent loop uses its own async client - see agent.py.)
_client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))


def _load(ticker: str) -> dict:
    """Load mocked market data for one ticker. Raises if unknown."""
    path = DATA_DIR / f"{ticker.upper()}.json"
    if not path.exists():
        raise ValueError(f"No data for ticker '{ticker}'. Try RELIANCE, TCS, or INFY.")
    return json.loads(path.read_text())


# --------------------------------------------------------------------------- #
# 1. Argument models. One Pydantic class per tool = one source of truth.
# --------------------------------------------------------------------------- #
class TickerArg(BaseModel):
    ticker: str = Field(description="NSE ticker symbol, e.g. RELIANCE, TCS, INFY")


class SummaryArg(BaseModel):
    ticker: str = Field(description="The ticker being analysed")
    findings: str = Field(
        description="A compact note of everything gathered so far: price action, "
        "fundamentals and news, written by you for yourself to summarise."
    )


# --------------------------------------------------------------------------- #
# 2. The tools themselves. Each returns a plain dict/str (JSON-serialisable).
# --------------------------------------------------------------------------- #
def get_price_history(ticker: str) -> dict:
    return _load(ticker)["price_history"]


def get_news(ticker: str) -> list:
    return _load(ticker)["news"]


def get_fundamentals(ticker: str) -> dict:
    return _load(ticker)["fundamentals"]


def generate_summary(ticker: str, findings: str) -> str:
    """
    The generative tool. We hand the agent's own findings to an LLM and ask
    for a crisp investment thesis. This is 'GenAI as a tool' - the agent
    orchestrates, the model writes.
    """
    prompt = (
        f"You are an equity analyst. Using only these findings about {ticker}, "
        f"write a 3-4 sentence investment thesis in plain English. Be balanced, "
        f"mention one risk.\n\nFINDINGS:\n{findings}"
    )
    resp = _client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=300,
    )
    return resp.choices[0].message.content


# --------------------------------------------------------------------------- #
# 3. Registry: name -> (callable, pydantic arg model).
#    Dispatch and schema generation both read from this single dict.
# --------------------------------------------------------------------------- #
REGISTRY = {
    "get_price_history": (get_price_history, TickerArg, "Get 30-day price action for a stock."),
    "get_news": (get_news, TickerArg, "Get the latest news headlines for a stock."),
    "get_fundamentals": (get_fundamentals, TickerArg, "Get valuation and financial-health metrics."),
    "generate_summary": (generate_summary, SummaryArg, "Write the final investment thesis from gathered findings."),
}


def tool_schemas() -> list:
    """Build the OpenAI/Groq 'tools' array straight from Pydantic models."""
    schemas = []
    for name, (_, arg_model, description) in REGISTRY.items():
        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": arg_model.model_json_schema(),
            },
        })
    return schemas


def run_tool(name: str, raw_args: dict):
    """Validate args with Pydantic, then call the tool. One line of dispatch."""
    func, arg_model, _ = REGISTRY[name]
    args = arg_model(**raw_args)        # validation happens here
    return func(**args.model_dump())
