"""Meta Model API (Muse Spark) backend, OpenAI-compatible, with two quirks:

- `tool_choice` only accepts "auto" (forced/named is a 400), so we rely on the
  prompt and fall back to a JSON object in the message text.
- Reasoning tokens count against `max_tokens`; a low cap returns empty content.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

from .pricing import estimate_cost_usd

DEFAULT_MAX_TOKENS = 4096


class MetaResponseError(Exception):
    """No usable structured output from the model."""


@dataclass
class MetaToolResult:
    arguments: dict
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    cost_usd: float

    def usage_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cost_usd": self.cost_usd,
        }


_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _parse_json_object(text: Optional[str]) -> Optional[dict]:
    if not text:
        return None
    match = _JSON_OBJECT.search(text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def call_meta_tool(
    *,
    api_key: str,
    base_url: str,
    model: str,
    system: str,
    user: str,
    tool_name: str,
    tool_description: str,
    parameters: dict,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> MetaToolResult:
    import openai

    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_description,
                    "parameters": parameters,
                },
            }
        ],
        tool_choice="auto",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )

    message = response.choices[0].message
    arguments: Optional[dict] = None
    for call in message.tool_calls or []:
        if call.function.name == tool_name:
            try:
                parsed = json.loads(call.function.arguments)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                arguments = parsed
                break
    if arguments is None:
        arguments = _parse_json_object(message.content)
    if arguments is None:
        finish = response.choices[0].finish_reason
        raise MetaResponseError(
            f"{model} returned no `{tool_name}` call or JSON object (finish_reason={finish})"
        )

    usage: Any = response.usage
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    details = getattr(usage, "completion_tokens_details", None)
    reasoning_tokens = getattr(details, "reasoning_tokens", 0) or 0
    return MetaToolResult(
        arguments=arguments,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        reasoning_tokens=reasoning_tokens,
        cost_usd=estimate_cost_usd(prompt_tokens, completion_tokens, model) or 0.0,
    )
