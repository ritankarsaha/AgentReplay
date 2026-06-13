import json
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, List, Optional

import httpx
import pytest

import agentreplay
from agentreplay.collector import SpanCollector
from agentreplay.config import Config
from agentreplay.exporter import (
    MAX_SPAN_BYTES,
    SPANS_PATH,
    BackgroundExporter,
)
from agentreplay.span import Span


def _make_span(**overrides) -> Span:
    defaults = dict(
        id=str(uuid.uuid4()),
        run_id="run-1",
        parent_id=None,
        type="llm",
        name="test.span",
        input={"foo": "bar"},
        output={"result": "ok"},
        error=None,
        started_at=datetime.now(timezone.utc),
        duration_ms=1.23,
        fingerprint="abc123",
    )
    defaults.update(overrides)
    return Span(**defaults)


class RecordingTransport(httpx.BaseTransport):
    """Captures every request; responds via a configurable handler (default 202)."""

    def __init__(self, handler: Optional[Callable[[httpx.Request], httpx.Response]] = None):
        self.requests: List[httpx.Request] = []
        self._handler = handler

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        # Read the body now — httpx streams it and it won't be accessible later.
        request.read()
        self.requests.append(request)
        if self._handler is not None:
            return self._handler(request)
        return httpx.Response(202)


def _make_exporter(transport: httpx.BaseTransport, **overrides) -> BackgroundExporter:
    config = Config(api_key="key", project_id="proj", enabled=True)
    collector = overrides.pop("collector", None) or SpanCollector()
    client = httpx.Client(base_url="http://agentreplay.test", transport=transport)
    return BackgroundExporter(config, collector=collector, client=client, **overrides)


def test_flush_sends_batch_and_drains_collector():
    transport = RecordingTransport()
    collector = SpanCollector()
    collector.add(_make_span())
    collector.add(_make_span())
    exp = _make_exporter(transport, collector=collector)

    exp.flush()

    assert collector.get_all() == []
    assert len(transport.requests) == 1

    request = transport.requests[0]
    assert request.url.path == SPANS_PATH
    assert request.headers["authorization"] == "Bearer key"
    assert request.headers["content-type"] == "application/json"

    body = json.loads(request.content)
    assert body["project_id"] == "proj"
    assert len(body["spans"]) == 2
    assert body["spans"][0]["run_id"] == "run-1"
    assert body["spans"][0]["type"] == "llm"


def test_flush_includes_run_lifecycle_metadata_in_body():
    transport = RecordingTransport()
    collector = SpanCollector()
    collector.add(_make_span())
    config = Config(
        api_key="key", project_id="proj", enabled=True, agent_version="abc123", framework="langgraph"
    )
    client = httpx.Client(base_url="http://agentreplay.test", transport=transport)
    exp = BackgroundExporter(config, collector=collector, client=client)

    exp.flush()

    body = json.loads(transport.requests[0].content)
    assert body["agent_version"] == "abc123"
    assert body["framework"] == "langgraph"


def test_flush_sends_null_run_lifecycle_metadata_when_unset():
    transport = RecordingTransport()
    collector = SpanCollector()
    collector.add(_make_span())
    exp = _make_exporter(transport, collector=collector)

    exp.flush()

    body = json.loads(transport.requests[0].content)
    assert body["agent_version"] is None
    assert body["framework"] is None


def test_flush_on_empty_collector_sends_nothing():
    transport = RecordingTransport()
    exp = _make_exporter(transport)

    exp.flush()

    assert transport.requests == []


def test_flush_batches_by_max_batch_size():
    transport = RecordingTransport()
    collector = SpanCollector()
    for _ in range(5):
        collector.add(_make_span())
    exp = _make_exporter(transport, collector=collector, max_batch_size=2)

    exp.flush()

    assert collector.get_all() == []
    # 5 spans in batches of 2 -> 3 requests (2, 2, 1)
    sizes = [len(json.loads(r.content)["spans"]) for r in transport.requests]
    assert sizes == [2, 2, 1]


def test_oversized_span_is_dropped_not_sent():
    transport = RecordingTransport()
    collector = SpanCollector()
    collector.add(_make_span(input={"data": "x" * (MAX_SPAN_BYTES + 1)}))
    collector.add(_make_span())  # normal-sized span in the same batch
    exp = _make_exporter(transport, collector=collector)

    exp.flush()

    assert len(transport.requests) == 1
    body = json.loads(transport.requests[0].content)
    assert len(body["spans"]) == 1
    assert body["spans"][0]["input"] == {"foo": "bar"}


def test_all_oversized_spans_sends_no_request():
    transport = RecordingTransport()
    collector = SpanCollector()
    collector.add(_make_span(input={"data": "x" * (MAX_SPAN_BYTES + 1)}))
    exp = _make_exporter(transport, collector=collector)

    exp.flush()

    assert transport.requests == []
    assert collector.get_all() == []


def test_network_error_is_logged_and_spans_dropped(capsys):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    transport = RecordingTransport(handler)
    collector = SpanCollector()
    collector.add(_make_span())
    exp = _make_exporter(transport, collector=collector)

    exp.flush()  # must not raise

    assert collector.get_all() == []  # best-effort: dropped, not requeued
    captured = capsys.readouterr()
    assert "agentreplay: failed to export" in captured.err


def test_4xx_response_is_logged(capsys):
    transport = RecordingTransport(lambda r: httpx.Response(401, text="unauthorized"))
    collector = SpanCollector()
    collector.add(_make_span())
    exp = _make_exporter(transport, collector=collector)

    exp.flush()

    captured = capsys.readouterr()
    assert "agentreplay: ingest returned 401" in captured.err


def test_background_thread_flushes_periodically():
    transport = RecordingTransport()
    collector = SpanCollector()
    exp = _make_exporter(transport, collector=collector, flush_interval=0.05)

    exp.start()
    try:
        collector.add(_make_span())
        deadline = time.monotonic() + 2.0
        while not transport.requests and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        exp.shutdown()

    assert len(transport.requests) >= 1


def test_shutdown_flushes_remaining_spans_and_stops_thread():
    transport = RecordingTransport()
    collector = SpanCollector()
    # Long interval so only shutdown's final flush sends anything.
    exp = _make_exporter(transport, collector=collector, flush_interval=10.0)

    exp.start()
    collector.add(_make_span())
    exp.shutdown()

    assert collector.get_all() == []
    assert len(transport.requests) == 1
    assert exp._thread is None

    # idempotent
    exp.shutdown()


def test_shutdown_without_start_still_flushes():
    transport = RecordingTransport()
    collector = SpanCollector()
    collector.add(_make_span())
    exp = _make_exporter(transport, collector=collector)

    exp.shutdown()

    assert collector.get_all() == []
    assert len(transport.requests) == 1


# --- init()/flush()/shutdown() integration (uses conftest's mocked _build_client) ---


def test_init_starts_exporter():
    agentreplay.init(api_key="key", project_id="proj")

    from agentreplay import _state

    assert _state.get_exporter() is not None


def test_disabled_mode_does_not_start_exporter():
    agentreplay.init(enabled=False)

    from agentreplay import _state

    assert _state.get_exporter() is None


def test_flush_and_shutdown_are_noop_when_disabled():
    agentreplay.init(enabled=False)

    agentreplay.flush()  # must not raise
    agentreplay.shutdown()  # must not raise


def test_reinit_shuts_down_previous_exporter():
    agentreplay.init(api_key="key", project_id="proj")

    from agentreplay import _state

    first_exporter = _state.get_exporter()
    agentreplay.init(api_key="key2", project_id="proj2")
    second_exporter = _state.get_exporter()

    assert first_exporter is not second_exporter
    assert first_exporter._thread is None  # shut down by re-init


def test_end_to_end_span_recorded_then_flushed(monkeypatch):
    """A recorded LLM span makes it through the collector -> exporter -> HTTP layer."""
    anthropic = pytest.importorskip("anthropic")
    from anthropic.resources import messages as anthropic_messages

    class FakeMessage:
        def model_dump(self):
            return {"id": "msg_1", "content": [{"type": "text", "text": "hi"}]}

    def _fake_create(self, **kwargs):
        return FakeMessage()

    monkeypatch.setattr(anthropic_messages.Messages, "create", _fake_create)

    agentreplay.init(api_key="key", project_id="proj", flush_interval=10.0)

    self_obj = anthropic_messages.Messages.__new__(anthropic_messages.Messages)
    anthropic_messages.Messages.create(self_obj, model="m", messages=[], max_tokens=10)

    assert len(agentreplay.get_recorded_spans()) == 1

    agentreplay.flush()

    assert agentreplay.get_recorded_spans() == []
