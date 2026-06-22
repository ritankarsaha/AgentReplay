from __future__ import annotations

import pytest

import agentreplay
from agentreplay import _state
from agentreplay.fail import FAIL_SPAN_NAME, FAIL_SPAN_TYPE


def test_fail_records_span_with_reason():
    agentreplay.init(api_key="key", project_id="proj")

    span_id = agentreplay.fail("the agent looped forever")
    assert isinstance(span_id, str)

    spans = agentreplay.get_recorded_spans()
    assert len(spans) == 1
    span = spans[0]

    assert span.id == span_id
    assert span.type == FAIL_SPAN_TYPE
    assert span.name == FAIL_SPAN_NAME
    assert span.input == {"reason": "the agent looped forever"}
    assert span.output is None
    assert span.error is None
    assert span.run_id == _state.get_run_id()
    assert span.parent_id is None
    assert isinstance(span.fingerprint, str)


def test_fail_includes_failure_class_and_span_id():
    agentreplay.init(api_key="key", project_id="proj")

    agentreplay.fail(
        "bad tool output",
        failure_class="tool_error_unexpected_output",
        span_id="culprit-span-1",
    )

    span = agentreplay.get_recorded_spans()[0]
    assert span.input["failure_class"] == "tool_error_unexpected_output"
    assert span.input["span_id"] == "culprit-span-1"


def test_fail_includes_extra_kwargs():
    agentreplay.init(api_key="key", project_id="proj")

    agentreplay.fail("bad output", step=3, model="claude-3")

    span = agentreplay.get_recorded_spans()[0]
    assert span.input["extra"] == {"step": 3, "model": "claude-3"}


def test_fail_records_exception_as_error_payload():
    agentreplay.init(api_key="key", project_id="proj")

    try:
        raise ValueError("boom")
    except ValueError as exc:
        agentreplay.fail("agent raised", exception=exc)

    span = agentreplay.get_recorded_spans()[0]
    assert span.error == {"type": "ValueError", "message": "boom"}


def test_fail_nests_under_current_parent_span():
    agentreplay.init(api_key="key", project_id="proj")

    _state.push_parent_span_id("node-123")
    agentreplay.fail("nested failure")
    _state.pop_parent_span_id("node-123")

    span = agentreplay.get_recorded_spans()[0]
    assert span.parent_id == "node-123"


def test_fail_fingerprint_deterministic_for_identical_reason():
    agentreplay.init(api_key="key", project_id="proj")

    agentreplay.fail("same reason")
    agentreplay.fail("same reason")
    agentreplay.fail("different reason")

    spans = agentreplay.get_recorded_spans()
    assert spans[0].fingerprint == spans[1].fingerprint
    assert spans[0].fingerprint != spans[2].fingerprint


def test_fail_redact_applied_to_input():
    def redact(payload):
        return {k: ("[REDACTED]" if k == "reason" else v) for k, v in payload.items()}

    agentreplay.init(api_key="key", project_id="proj", redact=redact)

    agentreplay.fail("super secret crash detail")

    span = agentreplay.get_recorded_spans()[0]
    assert span.input == {"reason": "[REDACTED]"}


def test_fail_enabled_false_is_noop():
    agentreplay.init(enabled=False)

    result = agentreplay.fail("whatever")

    assert result is None
    assert agentreplay.get_recorded_spans() == []


def test_fail_not_initialized_is_noop():
    assert not _state.is_initialized()

    result = agentreplay.fail("whatever")

    assert result is None


def test_track_context_manager_passes_through_on_success():
    agentreplay.init(api_key="key", project_id="proj")

    with agentreplay.track():
        result = 1 + 1

    assert result == 2
    assert agentreplay.get_recorded_spans() == []


def test_track_context_manager_records_fail_on_exception_and_reraises():
    agentreplay.init(api_key="key", project_id="proj")

    with pytest.raises(ValueError, match="boom"):
        with agentreplay.track():
            raise ValueError("boom")

    span = agentreplay.get_recorded_spans()[0]
    assert span.type == FAIL_SPAN_TYPE
    assert span.name == FAIL_SPAN_NAME
    assert span.input["reason"] == "ValueError: boom"
    assert span.error == {"type": "ValueError", "message": "boom"}


def test_track_context_manager_custom_reason():
    agentreplay.init(api_key="key", project_id="proj")

    with pytest.raises(ValueError):
        with agentreplay.track(reason="custom label"):
            raise ValueError("boom")

    span = agentreplay.get_recorded_spans()[0]
    assert span.input["reason"] == "custom label"


def test_track_bare_decorator_sync():
    agentreplay.init(api_key="key", project_id="proj")

    @agentreplay.track
    def main():
        raise RuntimeError("agent crashed")

    with pytest.raises(RuntimeError):
        main()

    span = agentreplay.get_recorded_spans()[0]
    assert span.input["reason"] == "RuntimeError: agent crashed"


def test_track_bare_decorator_passes_through_return_value():
    agentreplay.init(api_key="key", project_id="proj")

    @agentreplay.track
    def main():
        return "ok"

    assert main() == "ok"
    assert agentreplay.get_recorded_spans() == []


def test_track_parameterized_decorator_sync():
    agentreplay.init(api_key="key", project_id="proj")

    @agentreplay.track(reason="entrypoint failed")
    def main():
        raise RuntimeError("agent crashed")

    with pytest.raises(RuntimeError):
        main()

    span = agentreplay.get_recorded_spans()[0]
    assert span.input["reason"] == "entrypoint failed"


async def test_track_decorator_async():
    agentreplay.init(api_key="key", project_id="proj")

    @agentreplay.track
    async def main():
        raise RuntimeError("async crash")

    with pytest.raises(RuntimeError):
        await main()

    span = agentreplay.get_recorded_spans()[0]
    assert span.input["reason"] == "RuntimeError: async crash"


async def test_track_context_manager_async_block():
    agentreplay.init(api_key="key", project_id="proj")

    async def boom():
        raise RuntimeError("async block crash")

    with pytest.raises(RuntimeError):
        with agentreplay.track():
            await boom()

    span = agentreplay.get_recorded_spans()[0]
    assert span.input["reason"] == "RuntimeError: async block crash"


def test_track_does_not_swallow_unrelated_exception_types():
    agentreplay.init(api_key="key", project_id="proj")

    with pytest.raises(KeyboardInterrupt):
        with agentreplay.track():
            raise KeyboardInterrupt()

    # KeyboardInterrupt is BaseException, not Exception — never recorded,
    # consistent with how every other recording path in this codebase
    # catches `Exception`, not `BaseException`.
    assert agentreplay.get_recorded_spans() == []
