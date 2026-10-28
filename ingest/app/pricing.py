"""Per-call LLM cost estimation.

Computed from the token `usage` already present in every recorded `llm` span's
output -- nothing extra is stored in the span payload, so replay fixtures and
fingerprints are untouched. Estimates for budgeting the hackathon credit pool,
not a billing source of truth. Unknown models cost `None` (never guessed).
"""

from __future__ import annotations

from typing import Any, Optional

# (input, output) USD per 1M tokens. Matched by longest model-name prefix.
PRICES_PER_M_USD: dict[str, tuple[float, float]] = {
    "muse-spark": (1.25, 4.25),
}

PRICE_PER_M_INPUT_USD, PRICE_PER_M_OUTPUT_USD = PRICES_PER_M_USD["muse-spark"]


def price_for(model: Optional[str]) -> Optional[tuple[float, float]]:
    if not model:
        return None
    best = max(
        (prefix for prefix in PRICES_PER_M_USD if model.startswith(prefix)),
        key=len,
        default=None,
    )
    return PRICES_PER_M_USD[best] if best else None


def estimate_cost_usd(
    prompt_tokens: int, completion_tokens: int, model: str = "muse-spark"
) -> Optional[float]:
    prices = price_for(model)
    if prices is None:
        return None
    return round(
        prompt_tokens * prices[0] / 1_000_000 + completion_tokens * prices[1] / 1_000_000, 6
    )


def tokens_from_usage(usage: Any) -> tuple[int, int]:
    if not isinstance(usage, dict):
        return 0, 0
    prompt = usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0
    completion = usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
    return int(prompt), int(completion)


def span_cost_usd(span_input: Any, span_output: Any) -> Optional[float]:
    if not isinstance(span_output, dict):
        return None
    model = span_output.get("model") or (
        span_input.get("model") if isinstance(span_input, dict) else None
    )
    prompt, completion = tokens_from_usage(span_output.get("usage"))
    if not (prompt or completion):
        return None
    return estimate_cost_usd(prompt, completion, model or "")
