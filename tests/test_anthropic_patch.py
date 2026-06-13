import sys

import pytest

import agentreplay
from agentreplay import _state
from agentreplay.patching import anthropic_patch

anthropic = pytest.importorskip("anthropic")
from anthropic.resources import messages as anthropic_messages  # noqa: E402


class FakeMessage:
    """Stand-in for anthropic.types.Message (pydantic model with model_dump)."""

    def __init__(self, **kwargs):
        self._data = kwargs

    def model_dump(self):
        return dict(self._data)


def _fake_response(kwargs):
    return FakeMessage(
        id="msg_123",
        model=kwargs.get("model"),
        role="assistant",
        content=[{"type": "text", "text": "hello"}],
        stop_reason="end_turn",
        usage={"input_tokens": 10, "output_tokens": 5},
    )


def _install_fake_sync_create(error=None):
    calls = []

    def _fake_create(self, **kwargs):
        calls.append(kwargs)
        if error is not None:
            raise error
        return _fake_response(kwargs)

    anthropic_messages.Messages.create = _fake_create
    return calls


def _install_fake_async_create(error=None):
    calls = []

    async def _fake_create(self, **kwargs):
        calls.append(kwargs)
        if error is not None:
            raise error
        return _fake_response(kwargs)

    anthropic_messages.AsyncMessages.create = _fake_create
    return calls


def _call_create(**kwargs):
    self_obj = anthropic_messages.Messages.__new__(anthropic_messages.Messages)
    return anthropic_messages.Messages.create(self_obj, **kwargs)


async def _acall_create(**kwargs):
    self_obj = anthropic_messages.AsyncMessages.__new__(anthropic_messages.AsyncMessages)
    return await anthropic_messages.AsyncMessages.create(self_obj, **kwargs)


def test_init_patches_messages_create():
    before_sync = anthropic_messages.Messages.create
    before_async = anthropic_messages.AsyncMessages.create
    agentreplay.init(api_key="key", project_id="proj")

    assert anthropic_messages.Messages.create is not before_sync
    assert anthropic_messages.AsyncMessages.create is not before_async
    assert anthropic_patch._patched is True


def test_records_llm_span_with_request_and_response():
    calls = _install_fake_sync_create()
    agentreplay.init(api_key="key", project_id="proj")

    response = _call_create(
        model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
    )

    assert len(calls) == 1
    assert response.model_dump()["content"][0]["text"] == "hello"

    spans = agentreplay.get_recorded_spans()
    assert len(spans) == 1
    span = spans[0]

    assert span.type == "llm"
    assert span.name == "anthropic.messages.create"
    assert span.run_id == _state.get_run_id()
    assert span.parent_id is None
    assert span.input["model"] == "claude-sonnet-4-6"
    assert span.input["messages"] == [{"role": "user", "content": "hi"}]
    assert span.output["content"][0]["text"] == "hello"
    assert span.output["usage"] == {"input_tokens": 10, "output_tokens": 5}
    assert span.error is None
    assert span.duration_ms >= 0
    assert isinstance(span.fingerprint, str) and len(span.fingerprint) == 64


async def test_records_llm_span_for_async_create():
    calls = _install_fake_async_create()
    agentreplay.init(api_key="key", project_id="proj")

    response = await _acall_create(
        model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
    )

    assert len(calls) == 1
    assert response.model_dump()["content"][0]["text"] == "hello"

    spans = agentreplay.get_recorded_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.type == "llm"
    assert span.name == "anthropic.messages.create"
    assert span.input["model"] == "claude-sonnet-4-6"
    assert span.output["content"][0]["text"] == "hello"


def test_records_error_span_and_reraises():
    _install_fake_sync_create(error=RuntimeError("boom"))
    agentreplay.init(api_key="key", project_id="proj")

    with pytest.raises(RuntimeError, match="boom"):
        _call_create(model="claude-sonnet-4-6", messages=[], max_tokens=10)

    spans = agentreplay.get_recorded_spans()
    assert len(spans) == 1
    assert spans[0].output is None
    assert spans[0].error == {"type": "RuntimeError", "message": "boom"}


async def test_async_records_error_span_and_reraises():
    _install_fake_async_create(error=RuntimeError("boom"))
    agentreplay.init(api_key="key", project_id="proj")

    with pytest.raises(RuntimeError, match="boom"):
        await _acall_create(model="claude-sonnet-4-6", messages=[], max_tokens=10)

    spans = agentreplay.get_recorded_spans()
    assert len(spans) == 1
    assert spans[0].output is None
    assert spans[0].error == {"type": "RuntimeError", "message": "boom"}


def test_disabled_mode_passes_through_without_recording():
    calls = _install_fake_sync_create()
    agentreplay.init(enabled=False)

    _call_create(model="claude-sonnet-4-6", messages=[], max_tokens=10)

    assert len(calls) == 1
    assert agentreplay.get_recorded_spans() == []


def test_fingerprint_is_deterministic_for_identical_requests():
    _install_fake_sync_create()
    agentreplay.init(api_key="key", project_id="proj")

    _call_create(model="m", messages=[{"role": "user", "content": "hi"}], max_tokens=10)
    _call_create(model="m", messages=[{"role": "user", "content": "hi"}], max_tokens=10)
    _call_create(model="m", messages=[{"role": "user", "content": "bye"}], max_tokens=10)

    spans = agentreplay.get_recorded_spans()
    assert spans[0].fingerprint == spans[1].fingerprint
    assert spans[0].fingerprint != spans[2].fingerprint


def test_streaming_request_records_placeholder_output():
    _install_fake_sync_create()
    agentreplay.init(api_key="key", project_id="proj")

    _call_create(model="m", messages=[], max_tokens=10, stream=True)

    span = agentreplay.get_recorded_spans()[0]
    assert span.output == {"streaming": True}
    assert span.input["stream"] is True


def test_redact_callback_applied_to_input_and_output():
    _install_fake_sync_create()

    def redact(payload):
        redacted = dict(payload)
        if "messages" in redacted:
            redacted["messages"] = "[REDACTED]"
        if "content" in redacted:
            redacted["content"] = "[REDACTED]"
        return redacted

    agentreplay.init(api_key="key", project_id="proj", redact=redact)

    _call_create(model="m", messages=[{"role": "user", "content": "secret"}], max_tokens=10)

    span = agentreplay.get_recorded_spans()[0]
    assert span.input["messages"] == "[REDACTED]"
    assert span.output["content"] == "[REDACTED]"
    # fingerprint computed pre-redaction, still deterministic
    assert isinstance(span.fingerprint, str)


def test_excluded_transport_kwargs_not_captured():
    _install_fake_sync_create()
    agentreplay.init(api_key="key", project_id="proj")

    _call_create(model="m", messages=[], max_tokens=10, timeout=30, extra_headers={"X-Foo": "bar"})

    span = agentreplay.get_recorded_spans()[0]
    assert "timeout" not in span.input
    assert "extra_headers" not in span.input


def test_unpatch_restores_original():
    _install_fake_sync_create()
    _install_fake_async_create()
    current_sync = anthropic_messages.Messages.create
    current_async = anthropic_messages.AsyncMessages.create

    agentreplay.init(api_key="key", project_id="proj")
    assert anthropic_messages.Messages.create is not current_sync
    assert anthropic_messages.AsyncMessages.create is not current_async

    anthropic_patch.unpatch_anthropic()
    assert anthropic_messages.Messages.create is current_sync
    assert anthropic_messages.AsyncMessages.create is current_async


def test_patch_anthropic_handles_missing_package(monkeypatch):
    anthropic_patch._patched = False
    monkeypatch.setitem(sys.modules, "anthropic", None)
    monkeypatch.delitem(sys.modules, "anthropic.resources", raising=False)
    monkeypatch.delitem(sys.modules, "anthropic.resources.messages", raising=False)

    assert anthropic_patch.patch_anthropic() is False
    assert anthropic_patch._patched is False
