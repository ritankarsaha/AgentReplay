from __future__ import annotations

from datetime import datetime, timezone

import pytest

import agentreplay
from agentreplay import _state
from agentreplay.fingerprint import compute_fingerprint
from agentreplay.replay import ReplayDivergence, ReplayedError, replay_mode
from agentreplay.span import Span
from agentreplay.tool import _build_tool_payload


def _tool_span(name, idx, fingerprint, output=None, error=None, run_id="run-1", input=None):
    return Span(
        id=f"tool-span-{name}-{idx}",
        run_id=run_id,
        parent_id=None,
        type="tool",
        name=name,
        input=input if input is not None else {"seq": idx},
        output=output,
        error=error,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        duration_ms=1.0,
        fingerprint=fingerprint,
    )


def _tool_fingerprint(span_name: str, args: tuple, kwargs: dict) -> str:
    payload = _build_tool_payload(args, kwargs)
    return compute_fingerprint({"tool": span_name, "input": payload})


def test_tool_replay_returns_recorded_output_without_calling_real_function():
    calls = []

    @agentreplay.tool
    def search(query: str) -> list:
        calls.append(query)
        return ["live", "result"]

    fp = _tool_fingerprint(search.__qualname__, ("hello",), {})
    span = _tool_span(search.__qualname__, 0, fp, output=["recorded", "result"])

    with replay_mode([span]) as session:
        result = search("hello")
        assert result == ["recorded", "result"]
        assert calls == []  # real function body never ran
        assert session.remaining_count() == 0


def test_tool_replay_with_custom_name():
    @agentreplay.tool(name="custom_tool")
    def whatever():
        return "live"

    fp = _tool_fingerprint("custom_tool", (), {})
    span = _tool_span("custom_tool", 0, fp, output="recorded")

    with replay_mode([span]):
        assert whatever() == "recorded"


async def test_tool_replay_async():
    calls = []

    @agentreplay.tool
    async def fetch(url: str) -> dict:
        calls.append(url)
        return {"url": url, "status": "live"}

    fp = _tool_fingerprint(fetch.__qualname__, ("https://x",), {})
    span = _tool_span(fetch.__qualname__, 0, fp, output={"url": "https://x", "status": "recorded"})

    with replay_mode([span]):
        result = await fetch("https://x")
        assert result == {"url": "https://x", "status": "recorded"}
        assert calls == []


def test_tool_replay_fingerprint_match_independent_of_call_order():
    @agentreplay.tool
    def echo(value: str) -> str:
        return f"live:{value}"

    fp_a = _tool_fingerprint(echo.__qualname__, ("a",), {})
    fp_b = _tool_fingerprint(echo.__qualname__, ("b",), {})
    span_a = _tool_span(echo.__qualname__, 0, fp_a, output="recorded:a")
    span_b = _tool_span(echo.__qualname__, 1, fp_b, output="recorded:b")

    with replay_mode([span_a, span_b]):
        # Call "b" first even though it was recorded second.
        assert echo("b") == "recorded:b"
        assert echo("a") == "recorded:a"


def test_tool_replay_sequence_fallback_when_fingerprint_does_not_match():
    @agentreplay.tool
    def echo(value: str) -> str:
        return f"live:{value}"

    span_0 = _tool_span(echo.__qualname__, 0, "fp-recorded-0", output="first")
    span_1 = _tool_span(echo.__qualname__, 1, "fp-recorded-1", output="second")

    with replay_mode([span_0, span_1]):
        assert echo("not recorded verbatim") == "first"
        assert echo("also not recorded verbatim") == "second"


def test_tool_replay_divergence_when_nothing_recorded():
    @agentreplay.tool
    def echo(value: str) -> str:
        return value

    with replay_mode([]):
        with pytest.raises(ReplayDivergence) as excinfo:
            echo("x")
        assert excinfo.value.call_site == echo.__qualname__
        assert excinfo.value.recorded_count == 0
        assert excinfo.value.expected_request is None
        assert excinfo.value.diff[0].path == "$"


def test_tool_replay_divergence_when_exhausted():
    @agentreplay.tool
    def echo(value: str) -> str:
        return value

    fp = _tool_fingerprint(echo.__qualname__, ("x",), {})
    span = _tool_span(echo.__qualname__, 0, fp, output="recorded")

    with replay_mode([span]):
        echo("x")
        with pytest.raises(ReplayDivergence) as excinfo:
            echo("x")
        assert excinfo.value.recorded_count == 1


def test_tool_replay_divergence_diff_compares_args_shape_correctly():
    @agentreplay.tool
    def echo(value: str) -> str:
        return value

    recorded_payload = _build_tool_payload(("hello",), {})
    fp = _tool_fingerprint(echo.__qualname__, ("hello",), {})
    span = _tool_span(echo.__qualname__, 0, fp, output="recorded", input=recorded_payload)

    with replay_mode([span]):
        echo("hello")  # consumes the only recorded call
        with pytest.raises(ReplayDivergence) as excinfo:
            echo("goodbye")

    divergence = excinfo.value
    # expected_request/request_payload are both the unwrapped {"args":...,
    # "kwargs":...} shape (not the {"tool": ..., "input": ...} fingerprint
    # wrapper) -- diffing compares like for like.
    assert divergence.expected_request == recorded_payload
    assert divergence.request_payload == _build_tool_payload(("goodbye",), {})
    assert len(divergence.diff) == 1
    assert divergence.diff[0].path == "$.args[0]"
    assert divergence.diff[0].expected == "hello"
    assert divergence.diff[0].actual == "goodbye"


def test_tool_replayed_error_for_recorded_failed_call():
    @agentreplay.tool
    def flaky():
        return "live"

    fp = _tool_fingerprint(flaky.__qualname__, (), {})
    span = _tool_span(
        flaky.__qualname__, 0, fp, output=None, error={"type": "ToolError", "message": "boom"}
    )

    with replay_mode([span]):
        with pytest.raises(ReplayedError) as excinfo:
            flaky()
        assert excinfo.value.original_type == "ToolError"
        assert excinfo.value.original_message == "boom"


def test_replay_session_combines_llm_and_tool_remaining_count():
    from anthropic.resources import messages as anthropic_messages  # noqa: F401

    pytest.importorskip("anthropic")

    @agentreplay.tool
    def echo(value: str) -> str:
        return value

    tool_fp = _tool_fingerprint(echo.__qualname__, ("x",), {})
    tool_span = _tool_span(echo.__qualname__, 0, tool_fp, output="recorded")

    llm_request = {"model": "m", "messages": []}
    llm_fp = compute_fingerprint(llm_request)
    llm_span = Span(
        id="llm-span-0",
        run_id="run-1",
        parent_id=None,
        type="llm",
        name="anthropic.messages.create",
        input={},
        output={
            "id": "msg_1",
            "model": "m",
            "role": "assistant",
            "type": "message",
            "content": [{"type": "text", "text": "hi"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
        error=None,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        duration_ms=1.0,
        fingerprint=llm_fp,
    )

    with replay_mode([tool_span, llm_span]) as session:
        assert session.remaining_count() == 2
        echo("x")
        assert session.remaining_count() == 1

        self_obj = anthropic_messages.Messages.__new__(anthropic_messages.Messages)
        anthropic_messages.Messages.create(self_obj, **llm_request)
        assert session.remaining_count() == 0


def test_tool_resumes_normal_behavior_after_replay_exits():
    calls = []

    @agentreplay.tool
    def echo(value: str) -> str:
        calls.append(value)
        return f"live:{value}"

    fp = _tool_fingerprint(echo.__qualname__, ("x",), {})
    span = _tool_span(echo.__qualname__, 0, fp, output="recorded")

    with replay_mode([span]):
        assert echo("x") == "recorded"

    agentreplay.init(enabled=False)
    assert echo("x") == "live:x"
    assert calls == ["x"]
    assert _state.get_active_tool_replay_run() is None


def test_tool_replay_works_without_init():
    @agentreplay.tool
    def echo(value: str) -> str:
        return value

    assert not _state.is_initialized()
    fp = _tool_fingerprint(echo.__qualname__, ("x",), {})
    span = _tool_span(echo.__qualname__, 0, fp, output="recorded")

    with replay_mode([span]):
        assert echo("x") == "recorded"
