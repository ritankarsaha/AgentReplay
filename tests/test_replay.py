import sys
from datetime import datetime, timezone

import pytest

from agentreplay.fingerprint import compute_fingerprint
from agentreplay.patching.common import build_request_payload
from agentreplay.replay import ReplayDivergence, ReplayedError, ReplayError, is_active, replay_mode
from agentreplay.replay import client as replay_client
from agentreplay.replay.store import CallSiteQueue, RecordedCall, RecordedRun
from agentreplay.span import Span

anthropic = pytest.importorskip("anthropic")
openai = pytest.importorskip("openai")

from anthropic.resources import messages as anthropic_messages  # noqa: E402
from openai.resources.chat import completions as openai_completions  # noqa: E402
from openai.resources.responses import responses as openai_responses  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_replay_state():
    replay_client._saved.clear()
    replay_client._active = False
    yield
    replay_client.unpatch_replay()


def _span(name, idx, fingerprint, output=None, error=None, run_id="run-1", input=None):
    return Span(
        id=f"span-{name}-{idx}",
        run_id=run_id,
        parent_id=None,
        type="llm",
        name=name,
        input=input if input is not None else {"seq": idx},
        output=output,
        error=error,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        duration_ms=1.0,
        fingerprint=fingerprint,
    )


def _anthropic_call(**kwargs):
    self_obj = anthropic_messages.Messages.__new__(anthropic_messages.Messages)
    return anthropic_messages.Messages.create(self_obj, **kwargs)


async def _anthropic_acall(**kwargs):
    self_obj = anthropic_messages.AsyncMessages.__new__(anthropic_messages.AsyncMessages)
    return await anthropic_messages.AsyncMessages.create(self_obj, **kwargs)


def _openai_chat_call(**kwargs):
    self_obj = openai_completions.Completions.__new__(openai_completions.Completions)
    return openai_completions.Completions.create(self_obj, **kwargs)


def _openai_responses_call(**kwargs):
    self_obj = openai_responses.Responses.__new__(openai_responses.Responses)
    return openai_responses.Responses.create(self_obj, **kwargs)


ANTHROPIC_OUTPUT = {
    "id": "msg_123",
    "model": "claude-sonnet-4-6",
    "role": "assistant",
    "type": "message",
    "content": [{"type": "text", "text": "hello from replay"}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 10, "output_tokens": 5},
}

OPENAI_CHAT_OUTPUT = {
    "id": "chatcmpl-123",
    "object": "chat.completion",
    "created": 1700000000,
    "model": "gpt-4o-mini",
    "choices": [
        {
            "index": 0,
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "hi there"},
        }
    ],
}

OPENAI_RESPONSES_OUTPUT = {
    "id": "resp_123",
    "object": "response",
    "created_at": 1700000000,
    "model": "gpt-4o-mini",
    "output": [],
    "parallel_tool_calls": True,
    "tool_choice": "auto",
    "tools": [],
}


# --- CallSiteQueue / RecordedRun matching logic (no SDK involved) ---------


def test_callsitequeue_matches_by_fingerprint_first():
    a = RecordedCall(span_id="a", name="x", sequence=0, fingerprint="fp-a", input={}, output={"v": "a"}, error=None)
    b = RecordedCall(span_id="b", name="x", sequence=1, fingerprint="fp-b", input={}, output={"v": "b"}, error=None)
    queue = CallSiteQueue([a, b])

    matched = queue.resolve("fp-b")
    assert matched is b
    assert b.consumed is True
    assert a.consumed is False


def test_callsitequeue_falls_back_to_sequence_when_no_fingerprint_match():
    a = RecordedCall(span_id="a", name="x", sequence=0, fingerprint="fp-a", input={}, output={"v": "a"}, error=None)
    b = RecordedCall(span_id="b", name="x", sequence=1, fingerprint="fp-b", input={}, output={"v": "b"}, error=None)
    queue = CallSiteQueue([a, b])

    assert queue.resolve("fp-unknown") is a
    assert queue.resolve("fp-unknown") is b


def test_callsitequeue_exhausted_returns_none():
    a = RecordedCall(span_id="a", name="x", sequence=0, fingerprint="fp-a", input={}, output={}, error=None)
    queue = CallSiteQueue([a])
    assert queue.resolve("fp-a") is a
    assert queue.resolve("fp-a") is None
    assert queue.resolve("anything") is None


def test_recordedrun_groups_by_call_site_and_ignores_non_llm_spans():
    node_span = Span(
        id="node-1",
        run_id="run-1",
        parent_id=None,
        type="node",
        name="n",
        input={},
        output={},
        error=None,
        started_at=datetime.now(timezone.utc),
        duration_ms=1.0,
        fingerprint="x",
    )
    spans = [
        _span("anthropic.messages.create", 0, "fp-0"),
        node_span,
        _span("openai.chat.completions.create", 0, "fp-1"),
    ]
    run = RecordedRun(spans)
    assert run.call_site_total("anthropic.messages.create") == 1
    assert run.call_site_total("openai.chat.completions.create") == 1
    assert run.call_site_total("unknown.call.site") == 0


def test_recordedrun_resolve_uses_compute_fingerprint_of_payload():
    payload = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    fp = compute_fingerprint(payload)
    spans = [_span("anthropic.messages.create", 0, fp, output={"hello": "world"})]
    run = RecordedRun(spans)

    call = run.resolve("anthropic.messages.create", payload)
    assert call is not None
    assert call.output == {"hello": "world"}
    assert run.remaining_count() == 0


def test_recordedrun_accepts_span_to_dict():
    payload = {"model": "m"}
    fp = compute_fingerprint(payload)
    span_dict = _span("anthropic.messages.create", 0, fp).to_dict()
    run = RecordedRun([span_dict])
    assert run.resolve("anthropic.messages.create", payload) is not None


# --- replay_mode() patch/unpatch + reconstruction against real SDK classes -


def test_replay_mode_serves_recorded_anthropic_response():
    request_payload = {"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]}
    fp = compute_fingerprint(request_payload)
    span = _span("anthropic.messages.create", 0, fp, output=ANTHROPIC_OUTPUT)

    with replay_mode([span]) as run:
        response = _anthropic_call(**request_payload)
        assert response.content[0].text == "hello from replay"
        assert run.remaining_count() == 0

    assert is_active() is False


async def test_replay_mode_serves_recorded_anthropic_response_async():
    request_payload = {"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]}
    fp = compute_fingerprint(request_payload)
    span = _span("anthropic.messages.create", 0, fp, output=ANTHROPIC_OUTPUT)

    with replay_mode([span]):
        response = await _anthropic_acall(**request_payload)
        assert response.content[0].text == "hello from replay"


def test_replay_mode_serves_recorded_openai_chat_completion():
    request_payload = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]}
    fp = compute_fingerprint(request_payload)
    span = _span("openai.chat.completions.create", 0, fp, output=OPENAI_CHAT_OUTPUT)

    with replay_mode([span]):
        response = _openai_chat_call(**request_payload)
        assert response.choices[0].message.content == "hi there"


def test_replay_mode_serves_recorded_openai_responses():
    request_payload = {"model": "gpt-4o-mini", "input": "hi"}
    fp = compute_fingerprint(request_payload)
    span = _span("openai.responses.create", 0, fp, output=OPENAI_RESPONSES_OUTPUT)

    with replay_mode([span]):
        response = _openai_responses_call(**request_payload)
        assert response.id == "resp_123"


def test_fingerprint_match_independent_of_call_order():
    payload_a = {"model": "m", "messages": [{"role": "user", "content": "a"}]}
    payload_b = {"model": "m", "messages": [{"role": "user", "content": "b"}]}
    fp_a, fp_b = compute_fingerprint(payload_a), compute_fingerprint(payload_b)
    span_a = _span("anthropic.messages.create", 0, fp_a, output={**ANTHROPIC_OUTPUT, "id": "a"})
    span_b = _span("anthropic.messages.create", 1, fp_b, output={**ANTHROPIC_OUTPUT, "id": "b"})

    with replay_mode([span_a, span_b]):
        # Live calls arrive out of recorded order -- fingerprint still wins.
        response_b = _anthropic_call(**payload_b)
        response_a = _anthropic_call(**payload_a)
        assert response_b.id == "b"
        assert response_a.id == "a"


def test_sequence_fallback_when_fingerprint_does_not_match():
    span_0 = _span("anthropic.messages.create", 0, "fp-recorded-0", output={**ANTHROPIC_OUTPUT, "id": "first"})
    span_1 = _span("anthropic.messages.create", 1, "fp-recorded-1", output={**ANTHROPIC_OUTPUT, "id": "second"})

    with replay_mode([span_0, span_1]):
        live_request = {"model": "m", "messages": [{"role": "user", "content": "not recorded verbatim"}]}
        first = _anthropic_call(**live_request)
        second = _anthropic_call(**live_request)
        assert first.id == "first"
        assert second.id == "second"


def test_no_recorded_calls_at_all_raises_divergence():
    with replay_mode([]):
        with pytest.raises(ReplayDivergence) as excinfo:
            _anthropic_call(model="m", messages=[], max_tokens=10)
        assert excinfo.value.call_site == "anthropic.messages.create"
        assert excinfo.value.recorded_count == 0


def test_exhausted_call_site_raises_divergence():
    span = _span("anthropic.messages.create", 0, "fp-0", output=ANTHROPIC_OUTPUT)

    with replay_mode([span]):
        _anthropic_call(model="m", messages=[], max_tokens=10)
        with pytest.raises(ReplayDivergence) as excinfo:
            _anthropic_call(model="m", messages=[], max_tokens=10)
        assert excinfo.value.recorded_count == 1


def test_divergence_diff_when_never_recorded():
    with replay_mode([]):
        with pytest.raises(ReplayDivergence) as excinfo:
            _anthropic_call(model="m", messages=[{"role": "user", "content": "hi"}])

    divergence = excinfo.value
    assert divergence.expected_request is None
    assert len(divergence.diff) == 1
    assert divergence.diff[0].path == "$"
    assert divergence.diff[0].actual == {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    assert "never recorded" in str(divergence)


def test_divergence_diff_against_last_recorded_request_when_exhausted():
    recorded_request = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    fp = compute_fingerprint(recorded_request)
    span = _span(
        "anthropic.messages.create", 0, fp, output=ANTHROPIC_OUTPUT, input=recorded_request
    )

    with replay_mode([span]):
        _anthropic_call(**recorded_request)  # consumes the only recorded call
        with pytest.raises(ReplayDivergence) as excinfo:
            _anthropic_call(model="m", messages=[{"role": "user", "content": "bye"}])

    divergence = excinfo.value
    assert divergence.expected_request == recorded_request
    paths = {d.path for d in divergence.diff}
    assert paths == {"$.messages[0].content"}
    diff = next(d for d in divergence.diff if d.path == "$.messages[0].content")
    assert diff.expected == "hi"
    assert diff.actual == "bye"


def test_replayed_error_for_recorded_failed_call():
    span = _span(
        "anthropic.messages.create",
        0,
        "fp-0",
        output=None,
        error={"type": "RateLimitError", "message": "rate limited"},
    )

    with replay_mode([span]):
        with pytest.raises(ReplayedError) as excinfo:
            _anthropic_call(model="m", messages=[], max_tokens=10)
        assert excinfo.value.original_type == "RateLimitError"
        assert excinfo.value.original_message == "rate limited"


def test_streaming_call_raises_replay_error():
    span = _span("anthropic.messages.create", 0, "fp-0", output=ANTHROPIC_OUTPUT)

    with replay_mode([span]):
        with pytest.raises(ReplayError):
            _anthropic_call(model="m", messages=[], max_tokens=10, stream=True)


def test_replay_mode_excludes_transport_kwargs_from_matching():
    request_payload = {"model": "m", "messages": []}
    fp = compute_fingerprint(build_request_payload(request_payload))
    span = _span("anthropic.messages.create", 0, fp, output=ANTHROPIC_OUTPUT)

    with replay_mode([span]):
        response = _anthropic_call(model="m", messages=[], timeout=30, extra_headers={"X-Foo": "bar"})
        assert response.id == "msg_123"


def test_unpatch_replay_restores_original_methods():
    before_sync = anthropic_messages.Messages.create
    before_async = anthropic_messages.AsyncMessages.create

    with replay_mode([]):
        assert anthropic_messages.Messages.create is not before_sync
        assert anthropic_messages.AsyncMessages.create is not before_async

    assert anthropic_messages.Messages.create is before_sync
    assert anthropic_messages.AsyncMessages.create is before_async


def test_patch_for_replay_skips_missing_provider(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    monkeypatch.delitem(sys.modules, "anthropic.resources", raising=False)
    monkeypatch.delitem(sys.modules, "anthropic.resources.messages", raising=False)

    before = openai_completions.Completions.create
    with replay_mode([]):
        assert openai_completions.Completions.create is not before
    assert openai_completions.Completions.create is before
