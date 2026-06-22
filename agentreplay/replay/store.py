"""Recorded-call matching for replay (CLAUDE.md §3.4).

Keys recorded LLM-call spans by call site (the span `name`, e.g.
"anthropic.messages.create" — recording is per class+method, so the name
already identifies the call site uniquely) and matches a live call against
that call site's recorded calls: fingerprint match first, falling back to
the next not-yet-consumed call in original recorded order. No match at all
means the call site is exhausted (or was never recorded) — the caller
(`client.py`) turns that into a `ReplayDivergence`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..fingerprint import compute_fingerprint


@dataclass
class RecordedCall:
    """One recorded `type="llm"` span, as seen by the replay matcher."""

    span_id: str
    name: str
    sequence: int  # 0-based position among calls sharing `name`, in recorded order
    fingerprint: str
    input: dict
    output: Optional[Any]
    error: Optional[dict]
    consumed: bool = field(default=False)


class CallSiteQueue:
    """Recorded calls for one call site, in original recorded order."""

    def __init__(self, calls: List[RecordedCall]) -> None:
        self._calls = calls

    def resolve(self, request_fingerprint: str) -> Optional[RecordedCall]:
        # 1. Fingerprint match among not-yet-consumed calls, anywhere in the
        #    queue (a retried/repeated call later in the trace should still
        #    match its own content, not just the next position).
        for call in self._calls:
            if not call.consumed and call.fingerprint == request_fingerprint:
                call.consumed = True
                return call
        # 2. Fall back to the next not-yet-consumed call in recorded order.
        for call in self._calls:
            if not call.consumed:
                call.consumed = True
                return call
        return None

    def __len__(self) -> int:
        return len(self._calls)

    def remaining(self) -> int:
        return sum(1 for call in self._calls if not call.consumed)

    def last_request(self) -> Optional[dict]:
        """The most recently recorded call's `input` (chunk 3.3's diff reference point).

        Independent of `consumed` state — used as the "expected" side of a
        `ReplayDivergence` diff, which should point at the closest available
        reference even when every recorded call here is already consumed.
        """
        return self._calls[-1].input if self._calls else None


def _coerce_span(raw: Any) -> dict:
    """Accept a `Span`, a `Span.to_dict()` dict, or an ingest-API span dict."""
    if isinstance(raw, dict):
        return raw
    to_dict = getattr(raw, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    raise TypeError(f"cannot use {type(raw)!r} as a recorded span")


class RecordedRun:
    """A loaded trace (or subset of it), grouped into per-call-site queues.

    `span_type` selects which span kind this run indexes/matches against —
    `"llm"` (chunk 3.1, call sites are e.g. `"anthropic.messages.create"`)
    or `"tool"` (chunk 3.2, call sites are `@agentreplay.tool` names).
    Build one `RecordedRun` per type you need to replay against the same
    `spans` list (see `agentreplay/replay/client.py: ReplaySession`) — the
    two types' call-site names share no namespace collision risk since
    they're indexed in entirely separate `RecordedRun` instances.
    """

    def __init__(self, spans: List[Any], span_type: str = "llm") -> None:
        coerced = [_coerce_span(raw) for raw in spans]
        matching_spans = [s for s in coerced if s.get("type") == span_type]
        # `started_at` is an ISO-8601 string (Span.to_dict()) so lexical sort
        # is chronological. Defensive: callers (e.g. the ingest API) already
        # return spans in this order, but replay correctness depends on it.
        matching_spans.sort(key=lambda s: s.get("started_at") or "")

        per_site: Dict[str, List[RecordedCall]] = {}
        for data in matching_spans:
            name = data["name"]
            calls = per_site.setdefault(name, [])
            calls.append(
                RecordedCall(
                    span_id=data["id"],
                    name=name,
                    sequence=len(calls),
                    fingerprint=data["fingerprint"],
                    input=data.get("input") or {},
                    output=data.get("output"),
                    error=data.get("error"),
                )
            )

        self._queues: Dict[str, CallSiteQueue] = {
            name: CallSiteQueue(calls) for name, calls in per_site.items()
        }

    def resolve(self, call_site: str, request_payload: dict) -> Optional[RecordedCall]:
        queue = self._queues.get(call_site)
        if queue is None:
            return None
        fingerprint = compute_fingerprint(request_payload)
        return queue.resolve(fingerprint)

    def call_site_total(self, call_site: str) -> int:
        queue = self._queues.get(call_site)
        return len(queue) if queue is not None else 0

    def last_request(self, call_site: str) -> Optional[dict]:
        """The most recently recorded request at `call_site`, or `None` if never recorded."""
        queue = self._queues.get(call_site)
        return queue.last_request() if queue is not None else None

    def remaining_count(self) -> int:
        return sum(queue.remaining() for queue in self._queues.values())
