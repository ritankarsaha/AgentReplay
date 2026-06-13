from __future__ import annotations

import threading
from typing import List, Optional

from .span import Span


class SpanCollector:
    """In-memory buffer of recorded spans.

    The background exporter (chunk 1.4) drains this and POSTs to the
    ingest API. Kept separate from _state so it survives independently
    of config re-init.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._spans: List[Span] = []

    def add(self, span: Span) -> None:
        with self._lock:
            self._spans.append(span)

    def get_all(self) -> List[Span]:
        with self._lock:
            return list(self._spans)

    def drain(self, max_count: Optional[int] = None) -> List[Span]:
        """Atomically remove and return up to max_count spans (all, if None)."""
        with self._lock:
            if max_count is None or max_count >= len(self._spans):
                drained, self._spans = self._spans, []
            else:
                drained, self._spans = self._spans[:max_count], self._spans[max_count:]
            return drained

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()


_collector = SpanCollector()


def get_collector() -> SpanCollector:
    return _collector
