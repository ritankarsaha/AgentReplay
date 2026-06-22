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

**Replay mode (chunk 3.2, CLAUDE.md §3.2/§9 risk #3):** when
`agentreplay.replay.replay_mode()` is active, calls to a decorated function
are served from the recorded trace instead — the real function body is
NEVER executed (tools are always mocked in replay; this is a safety
invariant, not an optimization). Matching reuses the exact same
fingerprint-first/sequence-fallback logic as LLM replay (chunk 3.1), keyed
by this tool's `span_name` instead of an LLM call-site name.
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
from .exceptions import ReplayDivergence, ReplayedError
from .fingerprint import compute_fingerprint
from .patching.common import build_error_payload
from .serialize import safe_serialize
from .span import Span

F = TypeVar("F", bound=Callable[..., Any])


def _build_tool_payload(args: tuple, kwargs: dict) -> dict:
    return safe_serialize({"args": list(args), "kwargs": kwargs})


def _resolve_replay(run: Any, span_name: str, args: tuple, kwargs: dict) -> Any:
    """Resolve a replayed tool call against `run` (a `RecordedRun` for `type="tool"`).

    `run` is duck-typed (only `.resolve()`/`.call_site_total()`/`.last_request()`
    are used) so this module never imports `agentreplay.replay` (the optional
    subpackage) — see `_state.py`'s `_active_tool_replay_run` docstring.
    """
    payload = _build_tool_payload(args, kwargs)
    # `fingerprint_payload` matches the recording side's exact hashed shape
    # (`_finish`: `compute_fingerprint({"tool": name, "input": input})`) so
    # matching stays correct against already-recorded fingerprints. The
    # *diff*-relevant "request" (chunk 3.3, `ReplayDivergence.expected_request`
    # / `.request_payload`) is `payload` alone, unwrapped — that's the shape
    # `Span.input` was recorded in (`_finish`'s `recorded_input = ctx["input"]`),
    # so expected-vs-actual compares like for like instead of an
    # apples-to-`{"tool": ..., "input": ...}` mismatch.
    fingerprint_payload = {"tool": span_name, "input": payload}
    call = run.resolve(span_name, fingerprint_payload)
    if call is None:
        raise ReplayDivergence(
            call_site=span_name,
            request_payload=payload,
            fingerprint=compute_fingerprint(fingerprint_payload),
            recorded_count=run.call_site_total(span_name),
            expected_request=run.last_request(span_name),
        )
    if call.error is not None:
        raise ReplayedError(call.error)
    return call.output


def _start(span_name: str, args: tuple, kwargs: dict) -> dict:
    span_id = str(uuid.uuid4())
    parent_id = _state.peek_parent_span_id()
    _state.push_parent_span_id(span_id)
    return {
        "span_id": span_id,
        "name": span_name,
        "input": _build_tool_payload(args, kwargs),
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

    During an active `agentreplay.replay.replay_mode()` session, the real
    function is never called at all — the recorded output (or recorded
    error, re-raised as `ReplayedError`) is returned instead, regardless of
    `init()`/`enabled` state. See the module docstring's "Replay mode" note.
    """

    def decorator(fn: F) -> F:
        span_name = name or fn.__qualname__

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                active_replay_run = _state.get_active_tool_replay_run()
                if active_replay_run is not None:
                    return _resolve_replay(active_replay_run, span_name, args, kwargs)

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
            active_replay_run = _state.get_active_tool_replay_run()
            if active_replay_run is not None:
                return _resolve_replay(active_replay_run, span_name, args, kwargs)

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
