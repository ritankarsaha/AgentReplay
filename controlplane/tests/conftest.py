from __future__ import annotations

import httpx
import pytest

from agentreplay import _state, exporter
from agentreplay.collector import get_collector


@pytest.fixture(autouse=True)
def _clean_agentreplay_state(monkeypatch):
    monkeypatch.setattr(
        exporter,
        "_build_client",
        lambda config: httpx.Client(
            base_url="http://agentreplay.test",
            transport=httpx.MockTransport(lambda request: httpx.Response(202)),
        ),
    )
    _state.reset()
    get_collector().clear()
    yield
    _state.reset()
    get_collector().clear()


@pytest.fixture
def recorded(monkeypatch):
    """Every span added to the collector, including ones the exporter later drains."""
    from agentreplay.collector import SpanCollector

    seen = []
    original = SpanCollector.add

    def add(self, span):
        seen.append(span)
        original(self, span)

    monkeypatch.setattr(SpanCollector, "add", add)
    return seen


SMS = "Book BLR→CCU Friday morning, under ₹6000."


@pytest.fixture
def travelbot_trace(monkeypatch, tmp_path, recorded):
    """Spans (ingest wire shape) of a guarded v1 TravelBot run that ends in a halted second booking."""
    import agentreplay
    from controlplane.blobs import BlobStore
    from controlplane.govern import Monitor, ScopeGuard, generate_keypair
    from controlplane.transact import travelbot as tb

    monkeypatch.setattr(tb, "capture_png", lambda html: b"\x89PNG-fake")
    keypair = generate_keypair()
    guard = ScopeGuard(
        tb.travelbot_manifest(keypair), keypair.public_key, bindings=tb.BINDINGS, arg_names=tb.ARG_NAMES, monitor=Monitor()
    )
    agentreplay.set_tool_guard(guard)
    agentreplay.init(api_key="k", project_id="p")
    try:
        tb.TravelBot(blobs=BlobStore(str(tmp_path))).run(SMS, attempt_fix=True)
    except agentreplay.ScopeViolation:
        pass
    agentreplay.set_tool_guard(None)
    spans = [s.to_dict() for s in recorded]
    _state.reset()
    return {"spans": spans, "agent_id": keypair.agent_id}
