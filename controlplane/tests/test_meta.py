from __future__ import annotations

from types import SimpleNamespace

import pytest

from controlplane import meta


def test_meta_client_requires_key(monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    with pytest.raises(meta.MetaNotConfigured):
        meta.meta_client()


def test_meta_client_defaults_and_env_override(monkeypatch):
    monkeypatch.setenv("META_API_KEY", "k")
    monkeypatch.delenv("META_BASE_URL", raising=False)
    assert str(meta.meta_client().base_url).rstrip("/") == "https://api.meta.ai/v1"
    monkeypatch.setenv("META_BASE_URL", "http://localhost:9/v1")
    assert str(meta.meta_client().base_url).rstrip("/") == "http://localhost:9/v1"


def test_meta_model_env_override(monkeypatch):
    monkeypatch.delenv("META_MODEL", raising=False)
    assert meta.meta_model() == "muse-spark-1.3"
    monkeypatch.setenv("META_MODEL", "muse-spark-1.2")
    assert meta.meta_model() == "muse-spark-1.2"


def test_chat_clamps_max_tokens_for_reasoning_headroom():
    seen = {}

    class _Completions:
        def create(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="pong"))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    assert meta.chat("hi", system="s", max_tokens=50, client=client) == "pong"
    assert seen["max_tokens"] == meta.MIN_MAX_TOKENS
    assert seen["messages"][0] == {"role": "system", "content": "s"}
