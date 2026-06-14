from __future__ import annotations

import pytest

import agentreplay
from agentreplay import _state


def test_sync_tool_records_span_with_args_kwargs_and_output():
    @agentreplay.tool
    def add(a, b, *, c=0):
        return a + b + c

    agentreplay.init(api_key="key", project_id="proj")

    result = add(1, 2, c=3)
    assert result == 6

    spans = agentreplay.get_recorded_spans()
    assert len(spans) == 1
    span = spans[0]

    assert span.type == "tool"
    assert span.name == add.__qualname__
    assert span.input == {"args": [1, 2], "kwargs": {"c": 3}}
    assert span.output == 6
    assert span.error is None
    assert span.run_id == _state.get_run_id()
    assert span.parent_id is None
    assert span.duration_ms >= 0
    assert isinstance(span.fingerprint, str)


def test_custom_name_overrides_span_name():
    @agentreplay.tool(name="custom_name")
    def my_func():
        return "ok"

    agentreplay.init(api_key="key", project_id="proj")
    my_func()

    span = agentreplay.get_recorded_spans()[0]
    assert span.name == "custom_name"


async def test_async_tool_records_span():
    @agentreplay.tool
    async def fetch(url: str) -> dict:
        return {"url": url, "status": 200}

    agentreplay.init(api_key="key", project_id="proj")

    result = await fetch("https://example.com")
    assert result == {"url": "https://example.com", "status": 200}

    span = agentreplay.get_recorded_spans()[0]
    assert span.type == "tool"
    assert span.name == fetch.__qualname__
    assert span.input == {"args": ["https://example.com"], "kwargs": {}}
    assert span.output == {"url": "https://example.com", "status": 200}
    assert span.error is None


def test_exception_records_error_span_and_reraises():
    @agentreplay.tool
    def failing():
        raise RuntimeError("boom")

    agentreplay.init(api_key="key", project_id="proj")

    with pytest.raises(RuntimeError, match="boom"):
        failing()

    span = agentreplay.get_recorded_spans()[0]
    assert span.type == "tool"
    assert span.output is None
    assert span.error == {"type": "RuntimeError", "message": "boom"}


async def test_async_exception_records_error_span_and_reraises():
    @agentreplay.tool
    async def failing():
        raise ValueError("nope")

    agentreplay.init(api_key="key", project_id="proj")

    with pytest.raises(ValueError, match="nope"):
        await failing()

    span = agentreplay.get_recorded_spans()[0]
    assert span.output is None
    assert span.error == {"type": "ValueError", "message": "nope"}


def test_nests_under_existing_parent_span():
    @agentreplay.tool
    def leaf():
        return "done"

    agentreplay.init(api_key="key", project_id="proj")

    _state.push_parent_span_id("node-123")
    leaf()
    _state.pop_parent_span_id("node-123")

    span = agentreplay.get_recorded_spans()[0]
    assert span.parent_id == "node-123"
    # stack restored to empty afterward
    assert _state.peek_parent_span_id() is None


def test_tool_span_becomes_parent_for_nested_work():
    seen_parent_ids = []

    @agentreplay.tool
    def outer():
        seen_parent_ids.append(_state.peek_parent_span_id())
        return "ok"

    agentreplay.init(api_key="key", project_id="proj")
    outer()

    span = agentreplay.get_recorded_spans()[0]
    # while `outer` was executing, it was its own span's parent context
    assert seen_parent_ids == [span.id]
    # stack empty again after return
    assert _state.peek_parent_span_id() is None


def test_redact_applied_to_input_and_output():
    @agentreplay.tool
    def whoami(secret):
        return {"secret": secret, "ok": True}

    def redact(payload):
        if isinstance(payload, dict) and "secret" in payload:
            return {**payload, "secret": "[REDACTED]"}
        if isinstance(payload, dict) and "args" in payload:
            return {**payload, "args": ["[REDACTED]" for _ in payload["args"]]}
        return payload

    agentreplay.init(api_key="key", project_id="proj", redact=redact)
    whoami("shh")

    span = agentreplay.get_recorded_spans()[0]
    assert span.input["args"] == ["[REDACTED]"]
    assert span.output["secret"] == "[REDACTED]"


def test_enabled_false_runs_without_recording():
    @agentreplay.tool
    def add(a, b):
        return a + b

    agentreplay.init(enabled=False)

    assert add(1, 2) == 3
    assert agentreplay.get_recorded_spans() == []


def test_not_initialized_runs_without_recording():
    @agentreplay.tool
    def add(a, b):
        return a + b

    assert not _state.is_initialized()
    assert add(1, 2) == 3
