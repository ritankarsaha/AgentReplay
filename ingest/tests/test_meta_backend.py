from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app import classifier as classifier_module
from app import meta as meta_module
from app.assertion_spec import AssertionSpecNotConfigured, generate_assertion_spec
from app.classifier import ClassifierNotConfigured, classify_trace
from app.config import Settings
from app.meta import MetaResponseError, call_meta_tool
from app.pricing import estimate_cost_usd, price_for, span_cost_usd

from .conftest import TEST_API_KEY, auth_headers

SCHEMA = {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]}


def _fake_openai(monkeypatch, message, *, usage=None, finish_reason="stop", captured=None):
    usage = usage or SimpleNamespace(
        prompt_tokens=1000,
        completion_tokens=400,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=300),
    )

    class _Completions:
        def create(self, **kwargs):
            if captured is not None:
                captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=message, finish_reason=finish_reason)], usage=usage
            )

    class _Client:
        def __init__(self, **kwargs):
            if captured is not None:
                captured["client_kwargs"] = kwargs
            self.chat = SimpleNamespace(completions=_Completions())

    import openai

    monkeypatch.setattr(openai, "OpenAI", _Client)


def _call(**overrides):
    kwargs = dict(
        api_key="k", base_url="https://api.meta.ai/v1", model="muse-spark-1.3",
        system="sys", user="usr", tool_name="report", tool_description="d", parameters=SCHEMA,
    )
    kwargs.update(overrides)
    return call_meta_tool(**kwargs)


def _tool_call_message(name="report", args='{"label": "x"}'):
    return SimpleNamespace(
        content=None, tool_calls=[SimpleNamespace(function=SimpleNamespace(name=name, arguments=args))]
    )


def test_call_meta_tool_uses_auto_tool_choice_and_reasoning_headroom(monkeypatch):
    captured: dict = {}
    _fake_openai(monkeypatch, _tool_call_message(), captured=captured)
    result = _call()
    assert captured["tool_choice"] == "auto"
    assert captured["max_tokens"] >= 2000
    assert captured["client_kwargs"]["base_url"] == "https://api.meta.ai/v1"
    assert result.arguments == {"label": "x"}
    assert result.reasoning_tokens == 300
    assert result.cost_usd == pytest.approx(1000 * 1.25 / 1e6 + 400 * 4.25 / 1e6)


def test_call_meta_tool_falls_back_to_json_in_content(monkeypatch):
    message = SimpleNamespace(content='Sure!\n```json\n{"label": "y"}\n```', tool_calls=None)
    _fake_openai(monkeypatch, message)
    assert _call().arguments == {"label": "y"}


def test_call_meta_tool_ignores_other_tool_names_and_bad_json(monkeypatch):
    message = SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(function=SimpleNamespace(name="other", arguments='{"a": 1}')),
            SimpleNamespace(function=SimpleNamespace(name="report", arguments="not json")),
        ],
    )
    _fake_openai(monkeypatch, message)
    with pytest.raises(MetaResponseError, match="no `report` call"):
        _call()


def test_call_meta_tool_raises_on_empty_reasoning_truncation(monkeypatch):
    message = SimpleNamespace(content=None, tool_calls=None)
    _fake_openai(monkeypatch, message, finish_reason="length")
    with pytest.raises(MetaResponseError, match="finish_reason=length"):
        _call()


def test_classify_trace_meta_requires_key():
    with pytest.raises(ClassifierNotConfigured, match="META_API_KEY"):
        classify_trace("trace", Settings(classifier_backend="meta", meta_api_key=None))


def test_classify_trace_meta_dispatch_and_usage(monkeypatch):
    def fake_call(**kwargs):
        assert kwargs["base_url"] == "https://api.meta.ai/v1"
        assert kwargs["model"] == "muse-spark-1.3"
        return meta_module.MetaToolResult(
            arguments={
                "failure_class": "step_repetition",
                "culprit_span_id": "s1",
                "diagnosis": "looped",
                "suggested_assertion": {"type": "structural", "description": "d"},
            },
            prompt_tokens=10, completion_tokens=5, reasoning_tokens=2, cost_usd=0.01,
        )

    monkeypatch.setattr(meta_module, "call_meta_tool", fake_call)
    result = classify_trace("trace", Settings(classifier_backend="meta", meta_api_key="k"))
    assert result.backend == "meta"
    assert result.usage["cost_usd"] == 0.01
    assert result.failure_class in classifier_module.MAST_CATEGORY_KEYS


def test_settings_configured_flags_for_meta():
    assert not Settings(classifier_backend="meta", meta_api_key=None).classifier_configured
    assert Settings(classifier_backend="meta", meta_api_key="k").classifier_configured
    assert not Settings(assertion_spec_backend="meta").assertion_spec_configured
    assert Settings(assertion_spec_backend="meta", meta_api_key="k").assertion_spec_configured
    assert Settings(
        assertion_spec_backend="meta", assertion_spec_meta_api_key="own"
    ).assertion_spec_configured


def test_assertion_spec_meta_requires_key():
    with pytest.raises(AssertionSpecNotConfigured, match="META_API_KEY"):
        generate_assertion_spec("t", "d", None, Settings(assertion_spec_backend="meta"))


def test_assertion_spec_meta_prefers_dedicated_key(monkeypatch):
    seen: dict = {}

    def fake_call(**kwargs):
        seen.update(kwargs)
        return meta_module.MetaToolResult(
            arguments={
                "must_call_tools": ["search"], "must_not_call_tools": [], "max_steps": 3,
                "no_exception": True, "semantic_rubric": None, "rationale": "r",
            },
            prompt_tokens=1, completion_tokens=1, reasoning_tokens=0, cost_usd=0.002,
        )

    monkeypatch.setattr(meta_module, "call_meta_tool", fake_call)
    spec = generate_assertion_spec(
        "t", "d", None,
        Settings(assertion_spec_backend="meta", meta_api_key="shared", assertion_spec_meta_api_key="own"),
    )
    assert seen["api_key"] == "own"
    assert spec.must_call_tools == ["search"]
    assert spec.to_dict()["usage"]["cost_usd"] == 0.002


def test_pricing_prefix_match_and_unknown_models():
    assert price_for("muse-spark-1.3-contributor") == (1.25, 4.25)
    assert price_for("gpt-4o") is None
    assert estimate_cost_usd(1_000_000, 1_000_000, "muse-spark-1.3") == pytest.approx(5.5)
    assert estimate_cost_usd(5, 5, "gpt-4o") is None


def test_span_cost_handles_openai_and_anthropic_usage_shapes():
    openai_out = {"model": "muse-spark-1.3", "usage": {"prompt_tokens": 1000, "completion_tokens": 100}}
    anthropic_out = {"model": "muse-spark-1.3", "usage": {"input_tokens": 1000, "output_tokens": 100}}
    assert span_cost_usd({}, openai_out) == span_cost_usd({}, anthropic_out) > 0
    assert span_cost_usd({"model": "muse-spark-1.3"}, {"usage": {"prompt_tokens": 1}}) is not None
    assert span_cost_usd({}, {"model": "muse-spark-1.3"}) is None
    assert span_cost_usd({}, "text") is None


async def test_usage_costs_aggregates_per_model_and_budget(client):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()

    def llm_span(sid, model, p, c):
        return {
            "id": sid, "run_id": "run-cost", "parent_id": None, "type": "llm", "name": "chat",
            "input": {"model": model}, "output": {"model": model, "usage": {"prompt_tokens": p, "completion_tokens": c}},
            "error": None, "started_at": now, "duration_ms": 1.0, "fingerprint": sid,
        }

    spans = [
        llm_span("s1", "muse-spark-1.3", 1_000_000, 0),
        llm_span("s2", "muse-spark-1.3", 0, 1_000_000),
        llm_span("s3", "gpt-4o", 10, 10),
    ]
    resp = await client.post(
        "/v1/spans",
        json={"project_id": "test-project", "agent_version": "v1", "framework": "raw", "spans": spans},
        headers=auth_headers(TEST_API_KEY),
    )
    assert resp.status_code in (200, 201, 202), resp.text

    resp = await client.get("/v1/usage/costs", headers=auth_headers(TEST_API_KEY))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_cost_usd"] == pytest.approx(5.5)
    assert body["by_model"]["muse-spark-1.3"]["calls"] == 2
    assert body["by_model"]["gpt-4o"]["priced_calls"] == 0
    assert body["unpriced_calls"] == 1
    assert body["credit_budget_usd"] == 150.0
    assert body["credit_remaining_usd"] == pytest.approx(144.5)
    assert body["truncated"] is False


async def test_usage_costs_requires_auth_and_is_tenant_scoped(client):
    assert (await client.get("/v1/usage/costs")).status_code == 401


async def test_control_plane_tables_exist_and_halted_is_sticky(client):
    from sqlalchemy import inspect
    from app.db import Base

    names = set(Base.metadata.tables)
    assert {
        "agents", "scope_manifests", "access_tokens", "trust_scores",
        "incidents", "filings", "model_runs",
    } <= names
