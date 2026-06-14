"""`@agentreplay.tool` decorator (chunk 2.5, CLAUDE.md §3.3 Layer 3).

Wraps a plain Python function (sync or async) and records one `type="tool"`
span per call: input = serialized `(args, kwargs)`, output = the serialized
return value, error on exception.

Usage::

    @agentreplay.tool
    def search(query: str) -> list[str]:
        ...

    @agentreplay.tool(name="custom_name")
    async def fetch(url: str) -> dict:
        ...

Recorded spans nest under the current LLM/node span via `_state`'s per-thread
parent stack (same mechanism as the LangGraph adapter, chunk 2.1), and the
tool's own span becomes the parent for anything recorded during the call —
so a tool that itself makes an LLM call (or calls another `@agentreplay.tool`
function) gets that span nested under it.
"""

from __future__ import annotations

import functools
import inspect
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional, TypeVar

from . import _state
from .collector import get_collector
from .fingerprint import compute_fingerprint
from .patching.common import build_error_payload
from .serialize import safe_serialize
from .span import Span

F = TypeVar("F", bound=Callable[..., Any])


def _start(span_name: str, args: tuple, kwargs: dict) -> dict:
    span_id = str(uuid.uuid4())
    parent_id = _state.peek_parent_span_id()
    _state.push_parent_span_id(span_id)
    return {
        "span_id": span_id,
        "name": span_name,
        "input": safe_serialize({"args": list(args), "kwargs": kwargs}),
        "parent_id": parent_id,
        "started_at": datetime.now(timezone.utc),
        "start_perf": time.perf_counter(),
    }


def _finish(ctx: dict, output: Optional[Any], error: Optional[dict]) -> None:
    _state.pop_parent_span_id(ctx["span_id"])
    duration_ms = (time.perf_counter() - ctx["start_perf"]) * 1000

    try:
        fingerprint = compute_fingerprint({"tool": ctx["name"], "input": ctx["input"]})

        recorded_input = ctx["input"]
        recorded_output = output
        config = _state.get_config()
        if config.redact is not None:
            if recorded_input is not None:
                recorded_input = config.redact(recorded_input)
            if recorded_output is not None:
                recorded_output = config.redact(recorded_output)

        span = Span(
            id=ctx["span_id"],
            run_id=_state.get_run_id(),
            parent_id=ctx["parent_id"],
            type="tool",
            name=ctx["name"],
            input=recorded_input,
            output=recorded_output,
            error=error,
            started_at=ctx["started_at"],
            duration_ms=duration_ms,
            fingerprint=fingerprint,
        )
        get_collector().add(span)
    except Exception:
        # Recording must never break the host application.
        print(f"agentreplay: failed to record tool span ({ctx['name']})", file=sys.stderr)


def tool(func: Optional[F] = None, *, name: Optional[str] = None) -> Any:
    """Decorate a function so each call is recorded as a `type="tool"` span.

    Usable bare (`@agentreplay.tool`) or with a custom span name
    (`@agentreplay.tool(name="...")`). Works on both sync and async
    functions. When agentreplay isn't initialized or `enabled=False`, the
    function is called directly with no recording overhead.
    """

    def decorator(fn: F) -> F:
        span_name = name or fn.__qualname__

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                if not _state.is_initialized() or not _state.get_config().enabled:
                    return await fn(*args, **kwargs)

                ctx = _start(span_name, args, kwargs)
                try:
                    result = await fn(*args, **kwargs)
                except Exception as exc:
                    _finish(ctx, output=None, error=build_error_payload(exc))
                    raise
                _finish(ctx, output=safe_serialize(result), error=None)
                return result

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _state.is_initialized() or not _state.get_config().enabled:
                return fn(*args, **kwargs)

            ctx = _start(span_name, args, kwargs)
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                _finish(ctx, output=None, error=build_error_payload(exc))
                raise
            _finish(ctx, output=safe_serialize(result), error=None)
            return result

        return sync_wrapper  # type: ignore[return-value]

    if func is not None:
        return decorator(func)
    return decorator
