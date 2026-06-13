from __future__ import annotations

import atexit
import json
import sys
import threading
from typing import List, Optional

import httpx

from .collector import SpanCollector, get_collector
from .config import Config
from .span import Span

DEFAULT_FLUSH_INTERVAL = 5.0  # seconds
DEFAULT_MAX_BATCH_SIZE = 100

MAX_SPAN_BYTES = 1_000_000

SPANS_PATH = "/v1/spans"


def _build_client(config: Config) -> httpx.Client:
    return httpx.Client(base_url=config.endpoint, timeout=5.0)


class BackgroundExporter:
    """Drains the SpanCollector and POSTs batches to the ingest API on a timer.

    Best-effort: a batch that fails to send (network error or 4xx/5xx) is
    logged to stderr and dropped — there is no on-disk retry queue in v1.
    """

    def __init__(
        self,
        config: Config,
        collector: Optional[SpanCollector] = None,
        flush_interval: float = DEFAULT_FLUSH_INTERVAL,
        max_batch_size: int = DEFAULT_MAX_BATCH_SIZE,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self._config = config
        self._collector = collector or get_collector()
        self._flush_interval = flush_interval
        self._max_batch_size = max_batch_size
        self._client = client or _build_client(config)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="agentreplay-exporter", daemon=True)
        self._thread.start()
        atexit.register(self.shutdown)

    def _run(self) -> None:
        # Event.wait() returns True as soon as stop_event is set, so
        # shutdown() doesn't have to wait out a full flush_interval.
        while not self._stop_event.wait(self._flush_interval):
            self.flush()

    def flush(self) -> None:
        """Drain and send everything currently buffered, in batches."""
        while True:
            batch = self._collector.drain(self._max_batch_size)
            if not batch:
                return
            self._send_batch(batch)
            if len(batch) < self._max_batch_size:
                return

    def shutdown(self) -> None:
        """Stop the background thread (if running), flush remaining spans, close the client."""
        if self._thread is not None:
            self._stop_event.set()
            self._thread.join(timeout=self._flush_interval + 1.0)
            self._thread = None
            atexit.unregister(self.shutdown)
        self.flush()
        self._client.close()

    def _send_batch(self, spans: List[Span]) -> None:
        payload_spans = []
        for span in spans:
            data = span.to_dict()
            size = len(json.dumps(data, default=str))
            if size > MAX_SPAN_BYTES:
                print(
                    f"agentreplay: dropping oversized span {span.id} "
                    f"({size} bytes > {MAX_SPAN_BYTES})",
                    file=sys.stderr,
                )
                continue
            payload_spans.append(data)

        if not payload_spans:
            return

        body = json.dumps(
            {
                "project_id": self._config.project_id,
                "agent_version": self._config.agent_version,
                "framework": self._config.framework,
                "spans": payload_spans,
            },
            default=str,
        ).encode("utf-8")

        try:
            response = self._client.post(
                SPANS_PATH,
                content=body,
                headers={
                    "Authorization": f"Bearer {self._config.api_key}",
                    "Content-Type": "application/json",
                },
            )
            if response.status_code >= 400:
                print(
                    f"agentreplay: ingest returned {response.status_code} for "
                    f"{len(payload_spans)} span(s): {response.text[:200]}",
                    file=sys.stderr,
                )
        except httpx.HTTPError as exc:
            print(
                f"agentreplay: failed to export {len(payload_spans)} span(s): {exc}",
                file=sys.stderr,
            )
