from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agentreplay.replay.store import RecordedRun
from agentreplay.span import Span
from agentreplay.testgen.assertions import (
    SemanticJudgeNotConfigured,
    SemanticJudgment,
    _default_judge,
    _judge_user_message,
    assert_max_steps,
    assert_must_call_tools,
    assert_must_not_call_tools,
    assert_no_exception,
    assert_semantic,
)


def _tool_span(name: str, idx: int) -> dict:
    return Span(
        id=f"tool-{name}-{idx}", run_id="run-1", parent_id=None, type="tool", name=name,
        input={"args": [], "kwargs": {}}, output="ok", error=None,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc), duration_ms=1.0, fingerprint=f"fp-{name}",
    ).to_dict()


def _run_with_calls(*names: str) -> RecordedRun:
    """A RecordedRun where each `name` has been resolved (consumed) exactly once."""
    spans = [_tool_span(name, i) for i, name in enumerate(names)]
    run = RecordedRun(spans, span_type="tool")
    for name in names:
        assert run.resolve(name, {}) is not None  # any payload matches via sequence fallback
    return run


def _empty_run() -> RecordedRun:
    return RecordedRun([], span_type="tool")


# --- assert_no_exception ----------------------------------------------------


def test_assert_no_exception_passes_when_none():
    assert_no_exception(None)  # must not raise


def test_assert_no_exception_raises_with_clear_message():
    original = ValueError("boom")
    with pytest.raises(AssertionError, match="expected the agent to complete without raising"):
        assert_no_exception(original)


def test_assert_no_exception_chains_original_exception():
    original = ValueError("boom")
    try:
        assert_no_exception(original)
    except AssertionError as exc:
        assert exc.__cause__ is original
    else:
        pytest.fail("expected AssertionError")


# --- assert_must_call_tools --------------------------------------------------


def test_assert_must_call_tools_passes_when_all_called():
    run = _run_with_calls("search", "lookup")
    assert_must_call_tools(run, ["search"])  # must not raise


def test_assert_must_call_tools_empty_expected_always_passes():
    run = _empty_run()
    assert_must_call_tools(run, [])  # must not raise


def test_assert_must_call_tools_fails_when_missing():
    run = _run_with_calls("search")
    with pytest.raises(AssertionError, match=r"\['validate_output'\]"):
        assert_must_call_tools(run, ["search", "validate_output"])


# --- assert_must_not_call_tools ----------------------------------------------


def test_assert_must_not_call_tools_passes_when_none_called():
    run = _run_with_calls("search")
    assert_must_not_call_tools(run, ["risky_tool"])  # must not raise


def test_assert_must_not_call_tools_fails_when_violated():
    run = _run_with_calls("search", "risky_tool")
    with pytest.raises(AssertionError, match=r"\['risky_tool'\]"):
        assert_must_not_call_tools(run, ["risky_tool"])


def test_assert_must_not_call_tools_empty_forbidden_always_passes():
    run = _run_with_calls("search")
    assert_must_not_call_tools(run, [])  # must not raise


# --- assert_max_steps ---------------------------------------------------------


def test_assert_max_steps_none_is_a_noop():
    run = _run_with_calls("a", "b", "c")
    assert_max_steps(run, None)  # must not raise regardless of call count


def test_assert_max_steps_passes_within_budget():
    run = _run_with_calls("a", "b")
    assert_max_steps(run, 2)
    assert_max_steps(run, 5)


def test_assert_max_steps_fails_when_exceeded():
    run = _run_with_calls("a", "b", "c")
    with pytest.raises(AssertionError, match="expected at most 2 tool-call step"):
        assert_max_steps(run, 2)


# --- assert_semantic (chunk 4.7) ----------------------------------------------


def _fail_if_called(*args, **kwargs):
    pytest.fail("judge_fn should not be called")


def test_assert_semantic_noop_when_rubric_is_none():
    assert_semantic({"keywords": ["a"]}, None, judge_fn=_fail_if_called)  # must not raise


def test_assert_semantic_noop_when_rubric_is_empty_string():
    assert_semantic({"keywords": ["a"]}, "", judge_fn=_fail_if_called)  # must not raise


def test_assert_semantic_passes_when_judge_approves():
    judge_fn = lambda output, rubric: SemanticJudgment(passes=True, reasoning="looks fine")
    assert_semantic({"keywords": ["clean"]}, "no markdown artifacts", judge_fn=judge_fn)


def test_assert_semantic_fails_with_judge_reasoning_when_rejected():
    judge_fn = lambda output, rubric: SemanticJudgment(
        passes=False, reasoning="contains leftover '**' markdown artifacts"
    )
    with pytest.raises(AssertionError, match="leftover '\\*\\*' markdown artifacts"):
        assert_semantic({"keywords": ["Distributed Systems**"]}, "no markdown artifacts", judge_fn=judge_fn)


def test_assert_semantic_passes_actual_output_and_rubric_through_to_judge_fn():
    captured = {}

    def judge_fn(output, rubric):
        captured["output"] = output
        captured["rubric"] = rubric
        return SemanticJudgment(passes=True, reasoning="")

    assert_semantic({"x": 1}, "some rubric", judge_fn=judge_fn)
    assert captured == {"output": {"x": 1}, "rubric": "some rubric"}


# --- _default_judge / _judge_user_message -------------------------------------


def test_default_judge_raises_semantic_judge_not_configured_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AGENTREPLAY_SEMANTIC_JUDGE_BACKEND", raising=False)
    with pytest.raises(SemanticJudgeNotConfigured, match="ANTHROPIC_API_KEY"):
        _default_judge({"x": 1}, "some rubric")


# --- NIM backend (AGENTREPLAY_SEMANTIC_JUDGE_BACKEND=nim) — see this
# module's docstring for why this was added, deviating from CLAUDE.md's
# original "always Sonnet, never NIM" line for this tier. -------------------


def test_default_judge_defaults_to_anthropic_backend(monkeypatch):
    monkeypatch.delenv("AGENTREPLAY_SEMANTIC_JUDGE_BACKEND", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SemanticJudgeNotConfigured, match="ANTHROPIC_API_KEY"):
        _default_judge({"x": 1}, "some rubric")


def test_default_judge_raises_when_nim_backend_selected_without_its_key(monkeypatch):
    monkeypatch.setenv("AGENTREPLAY_SEMANTIC_JUDGE_BACKEND", "nim")
    monkeypatch.delenv("AGENTREPLAY_SEMANTIC_JUDGE_NIM_API_KEY", raising=False)
    with pytest.raises(SemanticJudgeNotConfigured, match="AGENTREPLAY_SEMANTIC_JUDGE_NIM_API_KEY"):
        _default_judge({"x": 1}, "some rubric")


def test_default_judge_dispatches_to_nim_when_selected(monkeypatch):
    import agentreplay.testgen.assertions as assertions_module

    monkeypatch.setenv("AGENTREPLAY_SEMANTIC_JUDGE_BACKEND", "nim")
    captured = {}

    def fake_judge_with_nim(actual_output, rubric, *, model):
        captured.update(actual_output=actual_output, rubric=rubric, model=model)
        return SemanticJudgment(passes=True, reasoning="nim says fine")

    monkeypatch.setattr(assertions_module, "_judge_with_nim", fake_judge_with_nim)

    result = _default_judge({"x": 1}, "some rubric")

    assert result.passes is True
    assert captured == {
        "actual_output": {"x": 1}, "rubric": "some rubric", "model": "meta/llama-3.1-8b-instruct",
    }


def test_default_judge_dispatches_to_anthropic_when_selected(monkeypatch):
    import agentreplay.testgen.assertions as assertions_module

    monkeypatch.setenv("AGENTREPLAY_SEMANTIC_JUDGE_BACKEND", "anthropic")
    captured = {}

    def fake_judge_with_anthropic(actual_output, rubric, *, model):
        captured.update(model=model)
        return SemanticJudgment(passes=False, reasoning="anthropic says no")

    monkeypatch.setattr(assertions_module, "_judge_with_anthropic", fake_judge_with_anthropic)

    result = _default_judge({"x": 1}, "some rubric")

    assert result.passes is False
    assert captured["model"] == "claude-sonnet-4-6"


def test_judge_user_message_embeds_rubric_and_serializes_non_json_types():
    message = _judge_user_message({"when": datetime(2026, 1, 1, tzinfo=timezone.utc)}, "be correct")
    assert "be correct" in message
    assert "2026-01-01" in message
def test_default_judge_raises_when_meta_backend_selected_without_key(monkeypatch):
    monkeypatch.setenv("AGENTREPLAY_SEMANTIC_JUDGE_BACKEND", "meta")
    monkeypatch.delenv("AGENTREPLAY_SEMANTIC_JUDGE_META_API_KEY", raising=False)
    monkeypatch.delenv("META_API_KEY", raising=False)
    with pytest.raises(SemanticJudgeNotConfigured, match="SEMANTIC_JUDGE_META_API_KEY"):
        _default_judge({"x": 1}, "some rubric")


def test_default_judge_dispatches_to_meta_when_selected(monkeypatch):
    import agentreplay.testgen.assertions as assertions_module

    monkeypatch.setenv("AGENTREPLAY_SEMANTIC_JUDGE_BACKEND", "meta")
    captured = {}

    def fake_judge_with_meta(actual_output, rubric, *, model):
        captured.update(model=model)
        return SemanticJudgment(passes=True, reasoning="meta says fine")

    monkeypatch.setattr(assertions_module, "_judge_with_meta", fake_judge_with_meta)
    assert _default_judge({"x": 1}, "r").passes is True
    assert captured == {"model": "muse-spark-1.3"}


def _fake_meta_openai(monkeypatch, message, captured):
    from types import SimpleNamespace

    import openai

    class _Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class _Client:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=_Completions())

    monkeypatch.setattr(openai, "OpenAI", _Client)


def test_judge_with_meta_uses_auto_tool_choice_and_parses_tool_call(monkeypatch):
    from types import SimpleNamespace

    import agentreplay.testgen.assertions as assertions_module

    monkeypatch.setenv("META_API_KEY", "k")
    monkeypatch.delenv("META_BASE_URL", raising=False)
    captured: dict = {}
    message = SimpleNamespace(
        content=None,
        tool_calls=[SimpleNamespace(function=SimpleNamespace(
            name="judge_output", arguments='{"passes": false, "reasoning": "bad"}'))],
    )
    _fake_meta_openai(monkeypatch, message, captured)

    judgment = assertions_module._judge_with_meta({"x": 1}, "rubric", model="muse-spark-1.3")

    assert (judgment.passes, judgment.reasoning) == (False, "bad")
    assert captured["tool_choice"] == "auto"
    assert captured["max_tokens"] >= 2000
    assert captured["client"]["base_url"] == "https://api.meta.ai/v1"


def test_judge_with_meta_falls_back_to_json_text(monkeypatch):
    from types import SimpleNamespace

    import agentreplay.testgen.assertions as assertions_module

    monkeypatch.setenv("META_API_KEY", "k")
    message = SimpleNamespace(content='Verdict: {"passes": true, "reasoning": "ok"}', tool_calls=None)
    _fake_meta_openai(monkeypatch, message, {})
    assert assertions_module._judge_with_meta({"x": 1}, "r", model="m").passes is True


def test_judge_with_meta_errors_on_unusable_reply(monkeypatch):
    from types import SimpleNamespace

    import agentreplay.testgen.assertions as assertions_module

    monkeypatch.setenv("META_API_KEY", "k")
    _fake_meta_openai(monkeypatch, SimpleNamespace(content=None, tool_calls=None), {})
    with pytest.raises(SemanticJudgeNotConfigured, match="neither"):
        assertions_module._judge_with_meta({"x": 1}, "r", model="m")
