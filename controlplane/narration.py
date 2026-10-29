"""Muse Spark wording for packets. It receives structured facts and returns prose only; callers
reject any text that omits the exact amount or booking reference."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

from controlplane import cassette, meta

NARRATION_MAX_TOKENS = 8192


def meta_narrator(chat: Optional[Callable[..., str]] = None) -> Callable[[Dict[str, Any]], str]:
    def narrate(facts: Dict[str, Any]) -> str:
        brief = {
            key: facts[key]
            for key in ("principal_intent", "transaction", "discrepancy", "causation", "requested_remedy")
            if key in facts
        }
        prompt = (
            "Write a 3-4 sentence plain-English narrative for a dispute filing about an AI agent's purchase. "
            "Use only the facts below, state the exact amount in INR and the booking reference, and invent "
            "nothing.\n\n" + json.dumps(brief, ensure_ascii=False, indent=2)
        )
        return cassette.run(
            "narrate",
            {"prompt": prompt},
            lambda: (chat or meta.chat)(
                prompt, system="You write precise, neutral incident narratives.", max_tokens=NARRATION_MAX_TOKENS
            ).strip(),
            valid=bool,
        )

    return narrate
