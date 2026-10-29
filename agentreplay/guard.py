"""Opt-in enforcement hook for `@agentreplay.tool`.

A guard is any object with `check(tool_name, args, kwargs) -> GuardDecision`.
Optional methods: `is_halted() -> bool` (lets in-flight async tools be
cancelled) and `on_violation(tool_name, decision, span_id)` (called after a
denial has been recorded). With no guard installed, tools behave exactly as
before. Guard errors fail closed.
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from . import _state
from .collector import get_collector
from .fingerprint import compute_fingerprint
from .span import Span


@dataclass
class GuardDecision:
    allowed: bool
    rule: str
    reason: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "decision": "allow" if self.allowed else "deny",
            "rule": self.rule,
            "reason": self.reason,
            "details": self.details,
        }


def set_tool_guard(guard: Optional[Any]) -> None:
    """Install (or, with `None`, remove) the process-wide tool guard."""
    _state.set_tool_guard(guard)


def get_tool_guard() -> Optional[Any]:
    return _state.get_tool_guard()


def emit_span(
    span_type: str, name: str, payload: dict, output: Any, error: Optional[dict] = None
) -> Optional[str]:
    """Record a governance span (`policy`, `scope_violation`); never raises.

    The fingerprint matches the tool span for the same call, so replay can
    pair a recorded decision with its tool call.
    """
    if not (_state.is_initialized() and _state.get_config().enabled):
        return None
    try:
        recorded_input, recorded_output = payload, output
        redact = _state.get_config().redact
        if redact is not None:
            recorded_input = redact(recorded_input)
            recorded_output = redact(recorded_output)
        span = Span(
            id=str(uuid.uuid4()),
            run_id=_state.get_run_id(),
            parent_id=_state.peek_parent_span_id(),
            type=span_type,
            name=name,
            input=recorded_input,
            output=recorded_output,
            error=error,
            started_at=datetime.now(timezone.utc),
            duration_ms=0.0,
            fingerprint=compute_fingerprint({"tool": name, "input": payload}),
        )
        get_collector().add(span)
        return span.id
    except Exception:
        print(f"agentreplay: failed to record {span_type} span ({name})", file=sys.stderr)
        return None
