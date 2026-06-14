from __future__ import annotations

from typing import Any


def safe_serialize(value: Any) -> Any:
    """Best-effort JSON-safe snapshot of an arbitrary Python value.

    Used wherever we record an `input`/`output` payload that isn't already a
    plain JSON-serializable dict (LangGraph channel state, `@agentreplay.tool`
    function args/return values, ...). Recurses into containers, prefers
    `model_dump()`/`dict()` for model-like objects (LangChain messages,
    pydantic models), and falls back to `str()` for anything else so
    recording can never raise on unexpected shapes.
    """
    if isinstance(value, dict):
        return {k: safe_serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_serialize(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    for attr in ("model_dump", "dict"):
        method = getattr(value, attr, None)
        if callable(method):
            try:
                return safe_serialize(method())
            except Exception:
                break
    return str(value)
