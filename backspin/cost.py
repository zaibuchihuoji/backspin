"""Token cost estimation for recorded runs.

Prices are USD per 1M tokens from public list pricing (collected 2026-08;
models drift — override or extend ``PRICE_TABLE`` as needed). Matching is
exact first, then longest-prefix, so dated snapshots like
``gpt-4o-2024-11-20`` resolve to their base model.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

# model prefix -> (USD per 1M input tokens, USD per 1M output tokens)
PRICE_TABLE: Dict[str, Tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "o3-mini": (1.10, 4.40),
    "o3": (2.00, 8.00),
    "o4-mini": (1.10, 4.40),
    "claude-opus-4": (15.00, 75.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-3-7-sonnet": (3.00, 15.00),
    "claude-3-5-haiku": (0.80, 4.00),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
}

_prefixes = sorted(PRICE_TABLE, key=len, reverse=True)


def lookup_price(model: Optional[str]) -> Optional[Tuple[float, float]]:
    """Find (input, output) per-1M-token prices for a model name."""
    if not model:
        return None
    name = re.sub(r"^(anthropic/|openai/|google/|deepseek/)", "", model.strip(), flags=re.I)
    if name in PRICE_TABLE:
        return PRICE_TABLE[name]
    for prefix in _prefixes:
        if name.startswith(prefix):
            return PRICE_TABLE[prefix]
    return None


def estimate_cost(
    model: Optional[str], prompt_tokens: Optional[int], completion_tokens: Optional[int]
) -> Optional[float]:
    """Cost of one LLM call in USD, or None when the model is unknown."""
    price = lookup_price(model)
    if price is None or not (prompt_tokens or completion_tokens):
        return None
    in_price, out_price = price
    return (prompt_tokens or 0) / 1e6 * in_price + (completion_tokens or 0) / 1e6 * out_price


def cost_report(run: Any) -> Dict[str, Any]:
    """Sum estimated cost over a run's LLM calls.

    Returns ``{"total_usd": float, "complete": bool, "unknown_models": [...]}``.
    ``complete`` is False when at least one LLM call used a model outside
    the price table (its cost is not counted).
    """
    total = 0.0
    unknown = set()
    for ev in run.llm_calls():
        usage = ev.get("usage") or {}
        cost = estimate_cost(
            ev.get("model"), usage.get("prompt_tokens"), usage.get("completion_tokens")
        )
        if cost is None:
            unknown.add(ev.get("model") or "?")
        else:
            total += cost
    return {
        "total_usd": round(total, 6),
        "complete": not unknown,
        "unknown_models": sorted(unknown),
    }
