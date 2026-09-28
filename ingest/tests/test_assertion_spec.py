from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app import crud
from app.assertion_spec import (
    AssertionSpec,
    AssertionSpecNotConfigured,
    RunNotClassifiedError,
    _result_from_tool_input,
    generate_assertion_spec,
    generate_assertion_spec_for_run,
)
from app.config import Settings
from app.db import Base, make_session_factory
from app.models import Run, SpanModel


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = make_session_factory(engine)
    async with session_factory() as session:
        yield session
    await engine.dispose()


def _now() -> datetime:
    return datetime.now(timezone.utc)


_DEFAULT_DIAGNOSIS = {"text": "the tool returned malformed output"}


async def _make_run(
    session,
    *,
    run_id: str = "run-1",
    classification_status: str = "done",
    failure_class: str = "tool_execution_error",
    diagnosis: object = _DEFAULT_DIAGNOSIS,
) -> Run:
    if diagnosis is _DEFAULT_DIAGNOSIS and classification_status != "done":
        diagnosis = None
    run = Run(
        id=run_id,
        project_id="proj-1",
        started_at=_now(),
        last_seen_at=_now(),
        status="failure",
        classification_status=classification_status,
        failure_class=failure_class if classification_status == "done" else None,
        diagnosis=diagnosis,
    )
    session.add(run)
    span1 = SpanModel(
        id="span-1", run_id=run_id, parent_id=None, type="tool", name="search",
        input={"query": "x"}, output={"result": "garbage"}, error=None,
        started_at=_now(), duration_ms=5.0, fingerprint="fp-1",
    )
    session.add(span1)
    await session.commit()
    return await crud.get_run_with_spans_by_id(session, run_id=run_id)


def _spec(**overrides) -> AssertionSpec:
    defaults = dict(
        must_call_tools=["validate_output"],
        must_not_call_tools=[],
        max_steps=None,
        no_exception=True,
        rationale="the tool returned malformed output without validation",
        model="test-model",
    )
    defaults.update(overrides)
    return AssertionSpec(**defaults)


# --- _result_from_tool_input (pure parsing) ---------------------------------


def test_result_from_tool_input_happy_path():
    result = _result_from_tool_input(
        {
            "must_call_tools": ["validate_output"],
            "must_not_call_tools": ["risky_tool"],
            "max_steps": 10,
            "no_exception": True,
            "rationale": "because X",
        },
        model="m",
    )
    assert result.must_call_tools == ["validate_output"]
    assert result.must_not_call_tools == ["risky_tool"]
    assert result.max_steps == 10
    assert result.no_exception is True
    assert result.rationale == "because X"
    assert result.model == "m"


def test_result_from_tool_input_missing_lists_default_to_empty():
    result = _result_from_tool_input({"max_steps": None, "no_exception": True}, model="m")
    assert result.must_call_tools == []
    assert result.must_not_call_tools == []


def test_result_from_tool_input_null_max_steps_stays_none():
    result = _result_from_tool_input({"max_steps": None}, model="m")
    assert result.max_steps is None


def test_result_from_tool_input_non_numeric_max_steps_falls_back_to_none():
    result = _result_from_tool_input({"max_steps": "not-a-number"}, model="m")
    assert result.max_steps is None


def test_result_from_tool_input_bool_max_steps_falls_back_to_none():
    # bool is an int subclass -- must not be mistaken for a real step count.
    result = _result_from_tool_input({"max_steps": True}, model="m")
    assert result.max_steps is None


def test_result_from_tool_input_missing_rationale_defaults_to_empty_string():
    result = _result_from_tool_input({}, model="m")
    assert result.rationale == ""


def test_result_from_tool_input_missing_no_exception_defaults_true():
    result = _result_from_tool_input({}, model="m")
    assert result.no_exception is True


def test_result_from_tool_input_missing_semantic_rubric_defaults_to_none():
    result = _result_from_tool_input({}, model="m")
    assert result.semantic_rubric is None


def test_result_from_tool_input_null_semantic_rubric_stays_none():
    result = _result_from_tool_input({"semantic_rubric": None}, model="m")
    assert result.semantic_rubric is None


def test_result_from_tool_input_empty_string_semantic_rubric_becomes_none():
    # An empty/whitespace-only rubric is functionally "not applicable" --
    # same treatment as `assert_semantic()`'s own falsy-is-noop check.
    result = _result_from_tool_input({"semantic_rubric": "   "}, model="m")
    assert result.semantic_rubric is None


def test_result_from_tool_input_real_semantic_rubric_is_kept():
    result = _result_from_tool_input(
        {"semantic_rubric": "Output must not contain markdown artifacts like '**'."}, model="m"
    )
    assert result.semantic_rubric == "Output must not contain markdown artifacts like '**'."


def test_result_from_tool_input_non_string_semantic_rubric_falls_back_to_none():
    result = _result_from_tool_input({"semantic_rubric": 123}, model="m")
    assert result.semantic_rubric is None


# --- generate_assertion_spec dispatcher (anthropic default, nim available --
# see this module's docstring for why NIM was added here, deviating from
# CLAUDE.md's original "always Sonnet" line) ---------------------------------


def test_generate_assertion_spec_raises_when_anthropic_not_configured():
    settings = Settings(anthropic_api_key=None)
    with pytest.raises(AssertionSpecNotConfigured):
        generate_assertion_spec("summary", "diagnosis", "other", settings)


def test_generate_assertion_spec_classifier_nim_setting_is_irrelevant(monkeypatch):
    # The classifier's own nim_api_key/classifier_backend must not leak into
    # this generator's decision -- they're deliberately separate settings
    # (separate NIM quota) -- so this still raises via the anthropic branch.
    settings = Settings(classifier_backend="nim", nim_api_key="fake-classifier-nim-key", anthropic_api_key=None)
    with pytest.raises(AssertionSpecNotConfigured):
        generate_assertion_spec("summary", "diagnosis", "other", settings)


def test_generate_assertion_spec_calls_anthropic_when_configured(monkeypatch):
    captured = {}

    def fake_generate_with_anthropic(trace_summary, diagnosis_text, failure_class, *, api_key, model):
        captured.update(
            trace_summary=trace_summary, diagnosis_text=diagnosis_text,
            failure_class=failure_class, api_key=api_key, model=model,
        )
        return _spec()

    import app.assertion_spec as assertion_spec_module

    monkeypatch.setattr(assertion_spec_module, "generate_with_anthropic", fake_generate_with_anthropic)

    settings = Settings(anthropic_api_key="real-key", anthropic_model="claude-sonnet-4-6")
    result = generate_assertion_spec("trace", "diag", "tool_execution_error", settings)

    assert result.model == "test-model"
    assert captured["api_key"] == "real-key"
    assert captured["model"] == "claude-sonnet-4-6"
    assert captured["failure_class"] == "tool_execution_error"


def test_generate_assertion_spec_raises_when_nim_backend_not_configured():
    settings = Settings(assertion_spec_backend="nim", assertion_spec_nim_api_key=None)
    with pytest.raises(AssertionSpecNotConfigured, match="ASSERTION_SPEC_NIM_API_KEY"):
        generate_assertion_spec("summary", "diagnosis", "other", settings)


def test_generate_assertion_spec_calls_nim_when_configured(monkeypatch):
    captured = {}

    def fake_generate_with_nim(trace_summary, diagnosis_text, failure_class, *, api_key, model, base_url):
        captured.update(
            trace_summary=trace_summary, diagnosis_text=diagnosis_text,
            failure_class=failure_class, api_key=api_key, model=model, base_url=base_url,
        )
        return _spec(model=model)

    import app.assertion_spec as assertion_spec_module

    monkeypatch.setattr(assertion_spec_module, "generate_with_nim", fake_generate_with_nim)

    settings = Settings(
        assertion_spec_backend="nim",
        assertion_spec_nim_api_key="real-nim-key",
        assertion_spec_nim_model="meta/llama-3.1-8b-instruct",
    )
    result = generate_assertion_spec("trace", "diag", "tool_execution_error", settings)

    assert result.model == "meta/llama-3.1-8b-instruct"
    assert captured["api_key"] == "real-nim-key"
    assert captured["model"] == "meta/llama-3.1-8b-instruct"
    assert captured["failure_class"] == "tool_execution_error"
    assert captured["base_url"] == settings.nim_base_url


def test_generate_assertion_spec_nim_path_does_not_need_anthropic_key():
    # The whole point of adding the NIM backend: a project with zero
    # Anthropic key configured can still get a real (non-hand-authored) spec.
    settings = Settings(
        assertion_spec_backend="nim", assertion_spec_nim_api_key="real-nim-key", anthropic_api_key=None
    )
    assert settings.assertion_spec_configured is True


# --- generate_assertion_spec_for_run -----------------------------------------


async def test_generate_assertion_spec_for_run_raises_when_not_classified(db_session):
    run = await _make_run(db_session, classification_status="none")

    with pytest.raises(RunNotClassifiedError):
        await generate_assertion_spec_for_run(
            run, db_session, Settings(), generate_fn=lambda *a: _spec()
        )


async def test_generate_assertion_spec_for_run_happy_path_persists_spec(db_session):
    run = await _make_run(db_session, diagnosis={"text": "diag", "failure_class": "x"})

    result = await generate_assertion_spec_for_run(
        run, db_session, Settings(), generate_fn=lambda *a: _spec()
    )

    assert result.must_call_tools == ["validate_output"]

    refetched = await db_session.get(Run, "run-1")
    assert refetched.diagnosis["assertion_spec"]["must_call_tools"] == ["validate_output"]
    assert refetched.diagnosis["assertion_spec"]["model"] == "test-model"
    assert refetched.diagnosis["assertion_spec"]["semantic_rubric"] is None
    # existing diagnosis keys (chunk 3.6's own output) are preserved, not clobbered.
    assert refetched.diagnosis["text"] == "diag"
    assert refetched.diagnosis["failure_class"] == "x"


async def test_generate_assertion_spec_for_run_persists_semantic_rubric_when_present(db_session):
    run = await _make_run(db_session)
    rubric = "Output must not contain markdown artifacts like '**'."

    await generate_assertion_spec_for_run(
        run, db_session, Settings(), generate_fn=lambda *a: _spec(semantic_rubric=rubric)
    )

    refetched = await db_session.get(Run, "run-1")
    assert refetched.diagnosis["assertion_spec"]["semantic_rubric"] == rubric


async def test_generate_assertion_spec_for_run_passes_diagnosis_and_failure_class(db_session):
    run = await _make_run(
        db_session,
        failure_class="tool_execution_error",
        diagnosis={"text": "the tool returned malformed output"},
    )
    captured = {}

    def capturing_generate_fn(trace_summary, diagnosis_text, failure_class, settings):
        captured.update(
            trace_summary=trace_summary, diagnosis_text=diagnosis_text, failure_class=failure_class
        )
        return _spec()

    await generate_assertion_spec_for_run(run, db_session, Settings(), generate_fn=capturing_generate_fn)

    assert captured["diagnosis_text"] == "the tool returned malformed output"
    assert captured["failure_class"] == "tool_execution_error"
    assert "span-1" in captured["trace_summary"]


async def test_generate_assertion_spec_for_run_propagates_generator_exceptions(db_session):
    run = await _make_run(db_session)

    def boom(*args):
        raise AssertionSpecNotConfigured("no key")

    with pytest.raises(AssertionSpecNotConfigured):
        await generate_assertion_spec_for_run(run, db_session, Settings(), generate_fn=boom)

    # Unlike classify_run_async, this does NOT swallow the exception into
    # the diagnosis column -- the caller (a synchronous HTTP request) sees
    # it directly. diagnosis stays untouched.
    refetched = await db_session.get(Run, "run-1")
    assert "assertion_spec" not in (refetched.diagnosis or {})


async def test_generate_assertion_spec_for_run_handles_missing_diagnosis(db_session):
    run = await _make_run(db_session, diagnosis=None)
    captured = {}

    def capturing_generate_fn(trace_summary, diagnosis_text, failure_class, settings):
        captured["diagnosis_text"] = diagnosis_text
        return _spec()

    await generate_assertion_spec_for_run(run, db_session, Settings(), generate_fn=capturing_generate_fn)
    assert captured["diagnosis_text"] == ""

    refetched = await db_session.get(Run, "run-1")
    assert refetched.diagnosis["assertion_spec"]["must_call_tools"] == ["validate_output"]
