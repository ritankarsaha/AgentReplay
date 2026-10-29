"""Plain `openai.OpenAI` client for the Meta Model API, so the SDK's client
patching records Muse Spark calls as ordinary `llm` spans.

Quirks: `tool_choice` accepts only "auto", and reasoning tokens count against
`max_tokens` (even a one-word reply spends 200-350), so keep generous headroom.
"""

from __future__ import annotations

import os
from typing import Optional

from controlplane.ledger import LEDGER

DEFAULT_BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3"
SAM_MODEL = "sam-3.1"

MIN_MAX_TOKENS = 2000
EMPTY_RETRIES = 1
REQUEST_TIMEOUT_S = 120.0


class MetaNotConfigured(Exception):
    """META_API_KEY is not set."""


def meta_model() -> str:
    return os.environ.get("META_MODEL") or DEFAULT_MODEL


def meta_client(api_key: Optional[str] = None, base_url: Optional[str] = None):
    import openai

    key = api_key or os.environ.get("META_API_KEY")
    if not key:
        raise MetaNotConfigured("META_API_KEY is not set (see .env.example)")
    return openai.OpenAI(
        api_key=key,
        base_url=base_url or os.environ.get("META_BASE_URL") or DEFAULT_BASE_URL,
        timeout=REQUEST_TIMEOUT_S,
    )


def chat(
    prompt: str,
    *,
    system: Optional[str] = None,
    max_tokens: int = MIN_MAX_TOKENS,
    client=None,
    temperature: Optional[float] = None,
    seed: Optional[int] = None,
) -> str:
    """One chat completion. Muse Spark sometimes returns empty content, so an empty reply is retried once."""
    client = client or meta_client()
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    params = {"model": meta_model(), "messages": messages, "max_tokens": max(max_tokens, MIN_MAX_TOKENS)}
    if temperature is not None:
        params["temperature"] = temperature
    if seed is not None:
        params["seed"] = seed
    text = ""
    for _ in range(EMPTY_RETRIES + 1):
        response = client.chat.completions.create(**params)
        usage = getattr(response, "usage", None)
        if usage is not None:
            LEDGER.record(
                params["model"],
                {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage, "completion_tokens", 0),
                },
            )
        text = response.choices[0].message.content or ""
        if text.strip():
            break
    return text
