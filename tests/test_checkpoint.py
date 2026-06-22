from __future__ import annotations

import agentreplay
from agentreplay import _state


def test_records_checkpoint_span_with_state():
    agentreplay.init(api_key="key", project_id="proj")

    span_id = agentreplay.checkpoint("after_step_1", state={"counter": 1})
    assert isinstance(span_id, str)

    spans = agentreplay.get_recorded_spans()
    assert len(spans) == 1
    span = spans[0]

    assert span.id == span_id
    assert span.type == "checkpoint"
    assert span.name == "after_step_1"
    assert span.input == {"counter": 1}
    assert span.output is None
    assert span.error is None
    assert span.run_id == _state.get_run_id()
    assert span.parent_id is None
    assert span.duration_ms == 0.0
    assert isinstance(span.fingerprint, str)


def test_kwargs_merge_with_state_and_take_precedence():
    agentreplay.init(api_key="key", project_id="proj")

    agentreplay.checkpoint("merged", state={"a": 1, "b": 2}, b=3, c=4)

    span = agentreplay.get_recorded_spans()[0]
    assert span.input == {"a": 1, "b": 3, "c": 4}


def test_no_state_records_empty_input():
    agentreplay.init(api_key="key", project_id="proj")

    agentreplay.checkpoint("no_state")

    span = agentreplay.get_recorded_spans()[0]
    assert span.input == {}


def test_nests_under_current_parent_span():
    agentreplay.init(api_key="key", project_id="proj")

    _state.push_parent_span_id("node-123")
    agentreplay.checkpoint("inside_node", state={"x": 1})
    _state.pop_parent_span_id("node-123")

    span = agentreplay.get_recorded_spans()[0]
    assert span.parent_id == "node-123"


def test_fingerprint_is_deterministic_for_identical_name_and_state():
    agentreplay.init(api_key="key", project_id="proj")

    agentreplay.checkpoint("step", state={"x": 1})
    agentreplay.checkpoint("step", state={"x": 1})
    agentreplay.checkpoint("step", state={"x": 2})

    spans = agentreplay.get_recorded_spans()
    assert spans[0].fingerprint == spans[1].fingerprint
    assert spans[0].fingerprint != spans[2].fingerprint


def test_redact_applied_to_state():
    def redact(payload):
        return {k: ("[REDACTED]" if k == "secret" else v) for k, v in payload.items()}

    agentreplay.init(api_key="key", project_id="proj", redact=redact)

    agentreplay.checkpoint("with_secret", state={"secret": "shh", "ok": True})

    span = agentreplay.get_recorded_spans()[0]
    assert span.input == {"secret": "[REDACTED]", "ok": True}


def test_enabled_false_is_noop():
    agentreplay.init(enabled=False)

    result = agentreplay.checkpoint("step", state={"x": 1})

    assert result is None
    assert agentreplay.get_recorded_spans() == []


def test_not_initialized_is_noop():
    assert not _state.is_initialized()

    result = agentreplay.checkpoint("step", state={"x": 1})

    assert result is None
