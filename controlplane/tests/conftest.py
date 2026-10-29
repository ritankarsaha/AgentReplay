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
