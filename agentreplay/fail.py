"""`agentreplay.fail()` + `agentreplay.track()` — failure detection (chunk 3.5, CLAUDE.md §3.6).

CLAUDE.md §3.6 lists `agentreplay.fail()` as one of four ways a run becomes
`status="failure"` (the trigger for the classifier, chunk 3.6). This module
provides that explicit hook plus a generic "auto-detect on exception" wrapper
that works for any agent regardless of framework (raw SDK, LangGraph, CrewAI):
nothing here is framework-specific, per CLAUDE.md §3.3/§9 risk #5.

**Wire contract (no new endpoint):** `fail()` records a normal
`type="checkpoint"` span named `FAIL_SPAN_NAME`, which rides the existing
collector -> `BackgroundExporter` -> `POST /v1/spans` path (CLAUDE.md §3.5
schema, chunk 1.4's exporter). `ingest/app/crud.py` recognizes this exact
`(type, name)` pair during normal span ingestion and flips `runs.status` to
"failure" (escalate-only — see that module's `FAILURE_SPAN_TYPE`/
`FAILURE_SPAN_NAME` constants, which must stay in sync with this module's).
"""

from __future__ import annotations

import functools
import inspect
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional, TypeVar

from . import _state
from .collector import get_collector
from .fingerprint import compute_fingerprint
from .patching.common import build_error_payload
from .serialize import safe_serialize
from .span import Span

# Must match `ingest/app/crud.py`'s `FAILURE_SPAN_TYPE`/`FAILURE_SPAN_NAME`.
FAIL_SPAN_TYPE = "checkpoint"
FAIL_SPAN_NAME = "agentreplay.fail"

F = TypeVar("F", bound=Callable[..., Any])


def fail(
    reason: str,
    *,
    exception: Optional[BaseException] = None,
    failure_class: Optional[str] = None,
    span_id: Optional[str] = None,
    **extra: Any,
) -> Optional[str]:
    """Explicitly mark the current run as failed (CLAUDE.md §3.6).

    Records a `type="checkpoint"` span named `"agentreplay.fail"` carrying
    `reason` (and optionally `failure_class`/`span_id`/extra context), plus
    an error payload if `exception` is given. The ingest API recognizes this
    span shape and flips `runs.status` to `"failure"` on the next batch that
    contains it — see the module docstring's wire contract.

    `failure_class` here is free-form, caller-supplied metadata, NOT the
    MAST-taxonomy classification — that's chunk 3.6's Celery/Sonnet job,
    which runs after a run is marked `"failure"` and may set its own
    `failure_class` via its own (future) write path.

    `span_id`, if given, should be the id of the span that's actually at
    fault (e.g. one returned by `agentreplay.checkpoint()`); it becomes the
    run's `root_span_id`. If omitted, the fail span itself becomes the
    `root_span_id`.

    Never raises — recording a failure must not itself break the host
    application. Returns the recorded span's id, or `None` if agentreplay
    isn't initialized, is `enabled=False`, or recording itself fails.
    """
    if not _state.is_initialized() or not _state.get_config().enabled:
        return None

    try:
        config = _state.get_config()

        payload: dict = {"reason": reason}
        if failure_class is not None:
            payload["failure_class"] = failure_class
        if span_id is not None:
            payload["span_id"] = span_id
        if extra:
            payload["extra"] = safe_serialize(extra)

        error_payload = build_error_payload(exception) if exception is not None else None
        fingerprint = compute_fingerprint({"fail": True, "reason": reason})

        recorded_input = payload
        if config.redact is not None:
            recorded_input = config.redact(recorded_input)

        fail_span_id = str(uuid.uuid4())
        span = Span(
            id=fail_span_id,
            run_id=_state.get_run_id(),
            parent_id=_state.peek_parent_span_id(),
            type=FAIL_SPAN_TYPE,
            name=FAIL_SPAN_NAME,
            input=recorded_input,
            output=None,
            error=error_payload,
            started_at=datetime.now(timezone.utc),
            duration_ms=0.0,
            fingerprint=fingerprint,
        )
        get_collector().add(span)
        return fail_span_id
    except Exception:
        # Recording must never break the host application.
        print(f"agentreplay: failed to record failure ({reason})", file=sys.stderr)
        return None


class _TrackHandle:
    """Returned by `agentreplay.track(...)` — both a context manager and a decorator.

    `with agentreplay.track():` and `@agentreplay.track(reason=...)` share
    this one object so "wrap my agent's entrypoint" works the same way
    whether the entrypoint is a function or an inline block.
    """

    def __init__(self, reason: Optional[str] = None, **extra: Any) -> None:
        self._reason = reason
        self._extra = extra

    def _record(self, exc: BaseException) -> None:
        reason = self._reason or f"{type(exc).__name__}: {exc}"
        fail(reason, exception=exc, **self._extra)

    def __enter__(self) -> "_TrackHandle":
        return self

    def __exit__(self, exc_type: Any, exc: Optional[BaseException], tb: Any) -> bool:
        # Only `Exception`, not `BaseException` (e.g. KeyboardInterrupt,
        # SystemExit) — consistent with every other recording path in this
        # codebase (`tool.py`, `patching/common.py` all catch `Exception`).
        if exc is not None and isinstance(exc, Exception):
            self._record(exc)
        return False  # never swallow the exception

    def __call__(self, fn: F) -> F:
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    return await fn(*args, **kwargs)
                except Exception as exc:
                    self._record(exc)
                    raise

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                self._record(exc)
                raise

        return sync_wrapper  # type: ignore[return-value]


def track(func: Optional[F] = None, *, reason: Optional[str] = None, **extra: Any) -> Any:
    """Auto-detect-on-exception wrapper (CLAUDE.md §3.6), usable 3 ways::

        with agentreplay.track():
            run_agent()

        @agentreplay.track
        def main():
            ...

        @agentreplay.track(reason="custom label")
        async def main():
            ...

    Any exception escaping the wrapped block/function calls `agentreplay.fail()`
    (`reason` defaults to `f"{type(exc).__name__}: {exc}"`, plus
    `exception=exc` for the recorded error payload) and then re-raises —
    this never swallows the real exception, it only ensures the failure is
    also recorded for replay/classification. Mirrors `agentreplay.tool`'s
    bare/parameterized dual-usage pattern (`func is not None` => bare).
    """
    handle = _TrackHandle(reason=reason, **extra)
    if func is not None:
        return handle(func)
    return handle
