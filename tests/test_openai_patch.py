import sys

import pytest

import agentreplay
from agentreplay import _state
from agentreplay.patching import openai_patch

openai = pytest.importorskip("openai")
from openai.resources.chat import completions as openai_completions  # noqa: E402


class FakeChatCompletion:
    """Stand-in for openai.types.chat.ChatCompletion (pydantic model with model_dump)."""

    def __init__(self, **kwargs):
        self._data = kwargs

    def model_dump(self):
        return dict(self._data)


def _fake_response(kwargs):
    return FakeChatCompletion(
        id="chatcmpl_123",
        model=kwargs.get("model"),
        object="chat.completion",
        choices=[
            {
                "index": 0,
                "message": {"role": "assistant", "content": "hello"},
                "finish_reason": "stop",
            }
        ],
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )


def _install_fake_sync_create(error=None):
    calls = []

    def _fake_create(self, **kwargs):
        calls.append(kwargs)
        if error is not None:
            raise error
        return _fake_response(kwargs)

    openai_completions.Completions.create = _fake_create
    return calls


def _install_fake_async_create(error=None):
    calls = []

    async def _fake_create(self, **kwargs):
        calls.append(kwargs)
        if error is not None:
            raise error
        return _fake_response(kwargs)

    openai_completions.AsyncCompletions.create = _fake_create
    return calls


def _call_create(**kwargs):
    self_obj = openai_completions.Completions.__new__(openai_completions.Completions)
    return openai_completions.Completions.create(self_obj, **kwargs)


async def _acall_create(**kwargs):
    self_obj = openai_completions.AsyncCompletions.__new__(openai_completions.AsyncCompletions)
    return await openai_completions.AsyncCompletions.create(self_obj, **kwargs)


def test_init_patches_completions_create():
    before_sync = openai_completions.Completions.create
    before_async = openai_completions.AsyncCompletions.create
    agentreplay.init(api_key="key", project_id="proj")

    assert openai_completions.Completions.create is not before_sync
    assert openai_completions.AsyncCompletions.create is not before_async
    assert openai_patch._patched is True


def test_records_llm_span_with_request_and_response():
    calls = _install_fake_sync_create()
    agentreplay.init(api_key="key", project_id="proj")

    response = _call_create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
    )

    assert len(calls) == 1
    assert response.model_dump()["choices"][0]["message"]["content"] == "hello"

    spans = agentreplay.get_recorded_spans()
    assert len(spans) == 1
    span = spans[0]

    assert span.type == "llm"
    assert span.name == "openai.chat.completions.create"
    assert span.run_id == _state.get_run_id()
    assert span.parent_id is None
    assert span.input["model"] == "gpt-4o-mini"
    assert span.input["messages"] == [{"role": "user", "content": "hi"}]
    assert span.output["choices"][0]["message"]["content"] == "hello"
    assert span.output["usage"] == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert span.error is None
    assert span.duration_ms >= 0
    assert isinstance(span.fingerprint, str) and len(span.fingerprint) == 64


async def test_records_llm_span_for_async_create():
    calls = _install_fake_async_create()
    agentreplay.init(api_key="key", project_id="proj")

    response = await _acall_create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
    )

    assert len(calls) == 1
    assert response.model_dump()["choices"][0]["message"]["content"] == "hello"

    spans = agentreplay.get_recorded_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.type == "llm"
    assert span.name == "openai.chat.completions.create"
    assert span.input["model"] == "gpt-4o-mini"
    assert span.output["choices"][0]["message"]["content"] == "hello"


def test_records_error_span_and_reraises():
    _install_fake_sync_create(error=RuntimeError("boom"))
    agentreplay.init(api_key="key", project_id="proj")

    with pytest.raises(RuntimeError, match="boom"):
        _call_create(model="gpt-4o-mini", messages=[], max_tokens=10)

    spans = agentreplay.get_recorded_spans()
    assert len(spans) == 1
    assert spans[0].output is None
    assert spans[0].error == {"type": "RuntimeError", "message": "boom"}


async def test_async_records_error_span_and_reraises():
    _install_fake_async_create(error=RuntimeError("boom"))
    agentreplay.init(api_key="key", project_id="proj")

    with pytest.raises(RuntimeError, match="boom"):
        await _acall_create(model="gpt-4o-mini", messages=[], max_tokens=10)

    spans = agentreplay.get_recorded_spans()
    assert len(spans) == 1
    assert spans[0].output is None
    assert spans[0].error == {"type": "RuntimeError", "message": "boom"}


def test_disabled_mode_passes_through_without_recording():
    calls = _install_fake_sync_create()
    agentreplay.init(enabled=False)

    _call_create(model="gpt-4o-mini", messages=[], max_tokens=10)

    assert len(calls) == 1
    assert agentreplay.get_recorded_spans() == []


def test_streaming_request_records_placeholder_output():
    _install_fake_sync_create()
    agentreplay.init(api_key="key", project_id="proj")

    _call_create(model="gpt-4o-mini", messages=[], max_tokens=10, stream=True)

    span = agentreplay.get_recorded_spans()[0]
    assert span.output == {"streaming": True}
    assert span.input["stream"] is True


def test_nim_style_base_url_uses_same_patch():
    """NIM is OpenAI-compatible: same Completions class, only base_url differs.

    Patching the class covers NIM-served models automatically (CLAUDE.md §3.3) —
    this test documents that no NIM-specific branch exists in openai_patch.
    """
    calls = _install_fake_sync_create()
    agentreplay.init(api_key="key", project_id="proj")

    _call_create(model="meta/llama-3.1-8b-instruct", messages=[{"role": "user", "content": "hi"}], max_tokens=10)

    assert len(calls) == 1
    span = agentreplay.get_recorded_spans()[0]
    assert span.name == "openai.chat.completions.create"
    assert span.input["model"] == "meta/llama-3.1-8b-instruct"


def test_unpatch_restores_original():
    _install_fake_sync_create()
    _install_fake_async_create()
    current_sync = openai_completions.Completions.create
    current_async = openai_completions.AsyncCompletions.create

    agentreplay.init(api_key="key", project_id="proj")
    assert openai_completions.Completions.create is not current_sync
    assert openai_completions.AsyncCompletions.create is not current_async

    openai_patch.unpatch_openai()
    assert openai_completions.Completions.create is current_sync
    assert openai_completions.AsyncCompletions.create is current_async


def test_patch_openai_handles_missing_package(monkeypatch):
    openai_patch._patched = False
    monkeypatch.setitem(sys.modules, "openai", None)
    monkeypatch.delitem(sys.modules, "openai.resources", raising=False)
    monkeypatch.delitem(sys.modules, "openai.resources.chat", raising=False)
    monkeypatch.delitem(sys.modules, "openai.resources.chat.completions", raising=False)

    assert openai_patch.patch_openai() is False
    assert openai_patch._patched is False
