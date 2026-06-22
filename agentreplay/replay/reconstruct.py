"""Rebuild real SDK response objects from a recorded `.model_dump()` payload.

Recording (`patching/common.py: build_response_payload`) stores
`response.model_dump()`. Replay reverses that with `Model.model_validate()`
on the *same* SDK class — so a replayed response is a real
`anthropic.types.Message` / `openai.types.chat.ChatCompletion` /
`openai.types.responses.Response`, not a stand-in, and user code that calls
`.content[0].text` or similar keeps working unmodified.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional


def _anthropic_message(output: dict) -> Any:
    from anthropic.types import Message

    return Message.model_validate(output)


def _openai_chat_completion(output: dict) -> Any:
    from openai.types.chat import ChatCompletion

    return ChatCompletion.model_validate(output)


def _openai_response(output: dict) -> Any:
    from openai.types.responses import Response

    return Response.model_validate(output)


_RECONSTRUCTORS: Dict[str, Callable[[dict], Any]] = {
    "anthropic.messages.create": _anthropic_message,
    "openai.chat.completions.create": _openai_chat_completion,
    "openai.responses.create": _openai_response,
}


def reconstruct_response(call_site: str, output: Optional[Any]) -> Any:
    """Rebuild the SDK response object recorded at `call_site`.

    Falls back to returning the raw recorded payload if the call site is
    unknown, `output` isn't a dict (e.g. already a placeholder), or
    `model_validate()` fails (e.g. an installed SDK version whose schema
    moved since the trace was recorded) — still useful to callers that only
    read dict keys, and keeps replay from hard-failing on a version skew.
    """
    builder = _RECONSTRUCTORS.get(call_site)
    if builder is None or not isinstance(output, dict):
        return output
    try:
        return builder(output)
    except Exception:
        return output
