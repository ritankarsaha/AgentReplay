from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.classifier import (
    ClassificationResult,
    ClassifierNotConfigured,
    _result_from_tool_input,
    build_trace_summary,
    classify_run_async,
    classify_trace,
)
from app import crud
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


async def _make_failed_run(
    session, *, run_id: str = "run-1", status: str = "failure", classification_status: str = "none"
) -> Run:
    run = Run(
        id=run_id,
        project_id="proj-1",
        started_at=_now(),
        last_seen_at=_now(),
        status=status,
        classification_status=classification_status,
    )
    session.add(run)
    span1 = SpanModel(
        id="span-1",
        run_id=run_id,
        parent_id=None,
        type="tool",
        name="search",
        input={"query": "x"},
        output={"result": "garbage"},
        error=None,
        started_at=_now(),
        duration_ms=5.0,
        fingerprint="fp-1",
    )
    span2 = SpanModel(
        id="span-2",
        run_id=run_id,
        parent_id=None,
        type="checkpoint",
        name="agentreplay.fail",
        input={"reason": "tool returned garbage"},
        output=None,
        error=None,
        started_at=_now(),
        duration_ms=0.0,
        fingerprint="fp-2",
    )
    session.add_all([span1, span2])
    await session.commit()
    return run


def _result(
    *,
    failure_class: str = "tool_execution_error",
    culprit_span_id: str = "span-1",
    diagnosis: str = "the tool returned malformed output",
) -> ClassificationResult:
    return ClassificationResult(
        failure_class=failure_class,
        culprit_span_id=culprit_span_id,
        diagnosis=diagnosis,
        suggested_assertion={"type": "structural", "description": "tool output must be valid JSON"},
        model="test-model",
        backend="test-backend",
    )


# --- build_trace_summary ----------------------------------------------------


async def test_build_trace_summary_includes_span_fields(db_session):
    await _make_failed_run(db_session)
    run = await crud.get_run_with_spans_by_id(db_session, run_id="run-1")
    summary = build_trace_summary(run, run.spans)
    assert "span-1" in summary
    assert "search" in summary
    assert "agentreplay.fail" in summary
    assert run.id in summary


def test_build_trace_summary_truncates_large_fields():
    run = Run(
        id="run-big",
        project_id="proj-1",
        started_at=_now(),
        last_seen_at=_now(),
        status="failure",
    )
    big_span = SpanModel(
        id="span-big",
        run_id="run-big",
        parent_id=None,
        type="llm",
        name="anthropic.messages.create",
        input={"text": "x" * 5000},
        output=None,
        error=None,
        started_at=_now(),
        duration_ms=1.0,
        fingerprint="fp",
    )
    summary = build_trace_summary(run, [big_span])
    assert "truncated" in summary
    assert len(summary) < 5000


# --- _result_from_tool_input (pure parsing) ---------------------------------


def test_result_from_tool_input_unknown_failure_class_falls_back_to_other():
    result = _result_from_tool_input(
        {"failure_class": "not_a_real_category", "culprit_span_id": "span-1", "diagnosis": "x"},
        model="m",
        backend="b",
    )
    assert result.failure_class == "other"


def test_result_from_tool_input_unknown_culprit_string_becomes_none():
    result = _result_from_tool_input(
        {"failure_class": "other", "culprit_span_id": "unknown", "diagnosis": "x"},
        model="m",
        backend="b",
    )
    assert result.culprit_span_id is None


def test_result_from_tool_input_missing_suggested_assertion_defaults():
    result = _result_from_tool_input(
        {"failure_class": "other", "culprit_span_id": "span-1", "diagnosis": "x"},
        model="m",
        backend="b",
    )
    assert result.suggested_assertion == {"type": "structural", "description": ""}


# --- classify_trace dispatcher ----------------------------------------------


def test_classify_trace_raises_when_sonnet_not_configured():
    settings = Settings(classifier_backend="sonnet", anthropic_api_key=None)
    with pytest.raises(ClassifierNotConfigured):
        classify_trace("summary", settings)


def test_classify_trace_raises_when_nim_not_configured():
    settings = Settings(classifier_backend="nim", nim_api_key=None)
    with pytest.raises(ClassifierNotConfigured):
        classify_trace("summary", settings)


# --- classify_run_async ------------------------------------------------------


async def test_classify_run_async_skips_when_run_missing(db_session):
    calls = []
    await classify_run_async(
        "no-such-run", db_session, Settings(), classify_fn=lambda *a: calls.append(a) or _result()
    )
    assert calls == []


async def test_classify_run_async_skips_when_status_not_failure(db_session):
    await _make_failed_run(db_session, status="ok")
    calls = []
    await classify_run_async(
        "run-1", db_session, Settings(), classify_fn=lambda *a: calls.append(a) or _result()
    )
    assert calls == []


async def test_classify_run_async_skips_when_already_done(db_session):
    await _make_failed_run(db_session, classification_status="done")
    calls = []
    await classify_run_async(
        "run-1", db_session, Settings(), classify_fn=lambda *a: calls.append(a) or _result()
    )
    assert calls == []


async def test_classify_run_async_happy_path_updates_run(db_session):
    await _make_failed_run(db_session)

    await classify_run_async("run-1", db_session, Settings(), classify_fn=lambda *a: _result())

    run = await db_session.get(Run, "run-1")
    assert run.classification_status == "done"
    assert run.failure_class == "tool_execution_error"
    assert run.root_span_id == "span-1"
    assert run.diagnosis["text"] == "the tool returned malformed output"
    assert run.diagnosis["suggested_assertion"]["type"] == "structural"
    assert run.diagnosis["model"] == "test-model"
    assert run.diagnosis["backend"] == "test-backend"
    assert run.diagnosis["classified_at"]


async def test_classify_run_async_rejects_hallucinated_culprit_span_id(db_session):
    await _make_failed_run(db_session)

    await classify_run_async(
        "run-1",
        db_session,
        Settings(),
        classify_fn=lambda *a: _result(culprit_span_id="span-does-not-exist"),
    )

    run = await db_session.get(Run, "run-1")
    assert run.classification_status == "done"
    # root_span_id was never set (no explicit chunk-3.5 span_id), and the
    # hallucinated id is rejected, so it stays null rather than trusting it.
    assert run.root_span_id is None
    assert run.diagnosis["culprit_span_id"] is None


async def test_classify_run_async_preserves_existing_root_span_id_when_culprit_unknown(db_session):
    run = await _make_failed_run(db_session)
    run.root_span_id = "span-2"  # e.g. set explicitly by chunk 3.5's fail(span_id=...)
    await db_session.commit()

    await classify_run_async(
        "run-1", db_session, Settings(), classify_fn=lambda *a: _result(culprit_span_id=None)
    )

    run = await db_session.get(Run, "run-1")
    assert run.root_span_id == "span-2"


async def test_classify_run_async_handles_classifier_exception_sets_error_status(db_session):
    await _make_failed_run(db_session)

    def boom(*args):
        raise RuntimeError("anthropic api exploded")

    await classify_run_async("run-1", db_session, Settings(), classify_fn=boom)

    run = await db_session.get(Run, "run-1")
    assert run.classification_status == "error"
    assert "anthropic api exploded" in run.diagnosis["error"]
    assert run.failure_class is None  # untouched on error


async def test_classify_run_async_is_idempotent(db_session):
    await _make_failed_run(db_session)

    call_count = 0

    def counting(*args):
        nonlocal call_count
        call_count += 1
        return _result()

    await classify_run_async("run-1", db_session, Settings(), classify_fn=counting)
    await classify_run_async("run-1", db_session, Settings(), classify_fn=counting)

    assert call_count == 1
