import sys

import pytest

import agentreplay
from agentreplay import _state
from agentreplay.patching import responses_patch

openai = pytest.importorskip("openai")
from openai.resources.responses import responses as openai_responses  # noqa: E402


class FakeResponse:
    """Stand-in for openai.types.responses.Response (pydantic model with model_dump)."""

    def __init__(self, **kwargs):
        self._data = kwargs

    def model_dump(self):
        return dict(self._data)


def _fake_response(kwargs):
    return FakeResponse(
        id="resp_123",
        model=kwargs.get("model"),
        object="response",
        output=[
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "hello"}],
            }
        ],
        usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )


def _install_fake_sync_create(error=None):
    calls = []

    def _fake_create(self, **kwargs):
        calls.append(kwargs)
        if error is not None:
            raise error
        return _fake_response(kwargs)

    openai_responses.Responses.create = _fake_create
    return calls


def _install_fake_async_create(error=None):
    calls = []

    async def _fake_create(self, **kwargs):
        calls.append(kwargs)
        if error is not None:
            raise error
        return _fake_response(kwargs)

    openai_responses.AsyncResponses.create = _fake_create
    return calls


def _call_create(**kwargs):
    self_obj = openai_responses.Responses.__new__(openai_responses.Responses)
    return openai_responses.Responses.create(self_obj, **kwargs)


async def _acall_create(**kwargs):
    self_obj = openai_responses.AsyncResponses.__new__(openai_responses.AsyncResponses)
    return await openai_responses.AsyncResponses.create(self_obj, **kwargs)


def test_init_patches_responses_create():
    before_sync = openai_responses.Responses.create
    before_async = openai_responses.AsyncResponses.create
    agentreplay.init(api_key="key", project_id="proj")

    assert openai_responses.Responses.create is not before_sync
    assert openai_responses.AsyncResponses.create is not before_async
    assert responses_patch._patched is True


def test_records_llm_span_with_request_and_response():
    calls = _install_fake_sync_create()
    agentreplay.init(api_key="key", project_id="proj")

    response = _call_create(model="gpt-4o-mini", input="hi")

    assert len(calls) == 1
    assert response.model_dump()["output"][0]["content"][0]["text"] == "hello"

    spans = agentreplay.get_recorded_spans()
    assert len(spans) == 1
    span = spans[0]

    assert span.type == "llm"
    assert span.name == "openai.responses.create"
    assert span.run_id == _state.get_run_id()
    assert span.parent_id is None
    assert span.input["model"] == "gpt-4o-mini"
    assert span.input["input"] == "hi"
    assert span.output["output"][0]["content"][0]["text"] == "hello"
    assert span.output["usage"] == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    assert span.error is None
    assert span.duration_ms >= 0
    assert isinstance(span.fingerprint, str) and len(span.fingerprint) == 64


async def test_records_llm_span_for_async_create():
    calls = _install_fake_async_create()
    agentreplay.init(api_key="key", project_id="proj")

    response = await _acall_create(model="gpt-4o-mini", input="hi")

    assert len(calls) == 1
    assert response.model_dump()["output"][0]["content"][0]["text"] == "hello"

    spans = agentreplay.get_recorded_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.type == "llm"
    assert span.name == "openai.responses.create"
    assert span.input["model"] == "gpt-4o-mini"
    assert span.output["output"][0]["content"][0]["text"] == "hello"


def test_records_error_span_and_reraises():
    _install_fake_sync_create(error=RuntimeError("boom"))
    agentreplay.init(api_key="key", project_id="proj")

    with pytest.raises(RuntimeError, match="boom"):
        _call_create(model="gpt-4o-mini", input="hi")

    spans = agentreplay.get_recorded_spans()
    assert len(spans) == 1
    assert spans[0].output is None
    assert spans[0].error == {"type": "RuntimeError", "message": "boom"}


def test_disabled_mode_passes_through_without_recording():
    calls = _install_fake_sync_create()
    agentreplay.init(enabled=False)

    _call_create(model="gpt-4o-mini", input="hi")

    assert len(calls) == 1
    assert agentreplay.get_recorded_spans() == []


def test_streaming_request_records_placeholder_output():
    _install_fake_sync_create()
    agentreplay.init(api_key="key", project_id="proj")

    _call_create(model="gpt-4o-mini", input="hi", stream=True)

    span = agentreplay.get_recorded_spans()[0]
    assert span.output == {"streaming": True}
    assert span.input["stream"] is True


def test_unpatch_restores_original():
    _install_fake_sync_create()
    _install_fake_async_create()
    current_sync = openai_responses.Responses.create
    current_async = openai_responses.AsyncResponses.create

    agentreplay.init(api_key="key", project_id="proj")
    assert openai_responses.Responses.create is not current_sync
    assert openai_responses.AsyncResponses.create is not current_async

    responses_patch.unpatch_openai_responses()
    assert openai_responses.Responses.create is current_sync
    assert openai_responses.AsyncResponses.create is current_async


def test_patch_openai_responses_handles_missing_package(monkeypatch):
    responses_patch._patched = False
    monkeypatch.setitem(sys.modules, "openai", None)
    monkeypatch.delitem(sys.modules, "openai.resources", raising=False)
    monkeypatch.delitem(sys.modules, "openai.resources.responses", raising=False)
    monkeypatch.delitem(sys.modules, "openai.resources.responses.responses", raising=False)

    assert responses_patch.patch_openai_responses() is False
    assert responses_patch._patched is False
