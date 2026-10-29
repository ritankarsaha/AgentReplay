"""Per-call cost estimates from token usage. Budgeting aid, not a billing source of truth.
Unknown models cost `None`, never a guess."""

from __future__ import annotations

from typing import Dict, Optional, Tuple

PRICES_PER_M_USD: Dict[str, Tuple[float, float]] = {"muse-spark": (1.25, 4.25)}


def cost_usd(model: str, usage: Optional[dict]) -> Optional[float]:
    prices = next((p for prefix, p in PRICES_PER_M_USD.items() if model.startswith(prefix)), None)
    if prices is None or not usage:
        return None
    prompt = usage.get("prompt_tokens") or 0
    completion = usage.get("completion_tokens") or 0
    return round(prompt * prices[0] / 1e6 + completion * prices[1] / 1e6, 6)
