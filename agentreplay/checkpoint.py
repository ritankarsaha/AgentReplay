"""`agentreplay.checkpoint()` — generic state-snapshot API (CLAUDE.md §3.1#4).

For agents that don't go through a framework adapter (chunk 2.1's LangGraph
node spans), this is the manual equivalent: call `agentreplay.checkpoint()`
at any point to record a point-in-time `type="checkpoint"` span with
arbitrary state. Nests under the current LLM/node/tool span via `_state`'s
per-thread parent stack, same as every other span type.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from . import _state
from .collector import get_collector
from .fingerprint import compute_fingerprint
from .serialize import safe_serialize
from .span import Span


def checkpoint(name: str, state: Optional[dict] = None, **kwargs: Any) -> Optional[str]:
    """Record a `type="checkpoint"` span with the given `state`.

    `state` and any extra keyword arguments are merged into a single dict
    (keyword arguments take precedence), serialized via `safe_serialize`,
    and recorded as the span's `input`. Returns the recorded span's id, or
    `None` if agentreplay isn't initialized or `enabled=False` (no-op).
    """
    if not _state.is_initialized() or not _state.get_config().enabled:
        return None

    merged: dict = {}
    if state is not None:
        merged.update(state)
    merged.update(kwargs)

    try:
        serialized = safe_serialize(merged)
        fingerprint = compute_fingerprint({"checkpoint": name, "state": serialized})

        recorded_input = serialized
        config = _state.get_config()
        if config.redact is not None:
            recorded_input = config.redact(recorded_input)

        span_id = str(uuid.uuid4())
        span = Span(
            id=span_id,
            run_id=_state.get_run_id(),
            parent_id=_state.peek_parent_span_id(),
            type="checkpoint",
            name=name,
            input=recorded_input,
            output=None,
            error=None,
            started_at=datetime.now(timezone.utc),
            duration_ms=0.0,
            fingerprint=fingerprint,
        )
        get_collector().add(span)
        return span_id
    except Exception:
        # Recording must never break the host application.
        print(f"agentreplay: failed to record checkpoint ({name})", file=sys.stderr)
        return None
