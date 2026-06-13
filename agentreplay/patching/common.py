from __future__ import annotations

import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .. import _state
from ..collector import get_collector
from ..config import Config
from ..fingerprint import compute_fingerprint
from ..span import Span

# Transport-level kwargs that aren't part of the logical request and would
# blow up the fingerprint/payload with non-serializable httpx objects.
# Shared across Anthropic and OpenAI SDKs (both Stainless-generated).
EXCLUDED_REQUEST_FIELDS = {"extra_headers", "extra_query", "extra_body", "timeout"}


def build_request_payload(kwargs: dict) -> dict:
    return {k: v for k, v in kwargs.items() if k not in EXCLUDED_REQUEST_FIELDS}


def build_response_payload(response: Any, streaming: bool) -> dict:
    if streaming:

        return {"streaming": True}

    if hasattr(response, "model_dump"):
        return response.model_dump()
    if isinstance(response, dict):
        return response
    return {"value": str(response)}


def build_error_payload(exc: Exception) -> dict:
    return {"type": type(exc).__name__, "message": str(exc)}


def record_span(
    *,
    name: str,
    config: Config,
    request_payload: dict,
    response_payload: Optional[dict],
    error_payload: Optional[dict],
    started_at: datetime,
    duration_ms: float,
) -> None:
    try:
        fingerprint = compute_fingerprint(request_payload)

        recorded_input = request_payload
        recorded_output = response_payload
        if config.redact is not None:
            if recorded_input is not None:
                recorded_input = config.redact(recorded_input)
            if recorded_output is not None:
                recorded_output = config.redact(recorded_output)

        span = Span(
            id=str(uuid.uuid4()),
            run_id=_state.get_run_id(),
            parent_id=None,
            type="llm",
            name=name,
            input=recorded_input,
            output=recorded_output,
            error=error_payload,
            started_at=started_at,
            duration_ms=duration_ms,
            fingerprint=fingerprint,
        )
        get_collector().add(span)
    except Exception:
        # Recording must never break the host application.
        print(f"agentreplay: failed to record span ({name})", file=sys.stderr)


def wrap_sync_create(name: str, original: Callable) -> Callable:
    """Wrap a synchronous `*.create` client method to record an LLM span."""

    def patched(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not _state.is_initialized() or not _state.get_config().enabled:
            return original(self, *args, **kwargs)

        config = _state.get_config()
        request_payload = build_request_payload(kwargs)
        started_at = datetime.now(timezone.utc)
        start = time.perf_counter()

        try:
            response = original(self, *args, **kwargs)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            record_span(
                name=name,
                config=config,
                request_payload=request_payload,
                response_payload=None,
                error_payload=build_error_payload(exc),
                started_at=started_at,
                duration_ms=duration_ms,
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        response_payload = build_response_payload(response, streaming=bool(kwargs.get("stream")))
        record_span(
            name=name,
            config=config,
            request_payload=request_payload,
            response_payload=response_payload,
            error_payload=None,
            started_at=started_at,
            duration_ms=duration_ms,
        )
        return response

    return patched


def wrap_async_create(name: str, original: Callable) -> Callable:
    """Wrap an async `*.create` client method to record an LLM span."""

    async def patched(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not _state.is_initialized() or not _state.get_config().enabled:
            return await original(self, *args, **kwargs)

        config = _state.get_config()
        request_payload = build_request_payload(kwargs)
        started_at = datetime.now(timezone.utc)
        start = time.perf_counter()

        try:
            response = await original(self, *args, **kwargs)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            record_span(
                name=name,
                config=config,
                request_payload=request_payload,
                response_payload=None,
                error_payload=build_error_payload(exc),
                started_at=started_at,
                duration_ms=duration_ms,
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        response_payload = build_response_payload(response, streaming=bool(kwargs.get("stream")))
        record_span(
            name=name,
            config=config,
            request_payload=request_payload,
            response_payload=response_payload,
            error_payload=None,
            started_at=started_at,
            duration_ms=duration_ms,
        )
        return response

    return patched
