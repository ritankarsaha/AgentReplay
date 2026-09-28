from __future__ import annotations

import ast
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app import crud
from app.assertion_spec import AssertionSpec, AssertionSpecNotConfigured, RunNotClassifiedError
from app.config import Settings
from app.db import Base, make_session_factory
from app.models import Run, SpanModel
from app.testgen import EntrypointFormatError, generate_test_files_for_run


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


_PERSISTED_SPEC = {
    "must_call_tools": ["search"],
    "must_not_call_tools": [],
    "max_steps": None,
    "no_exception": True,
    "rationale": "search must be called",
    "model": "already-generated",
}


async def _make_run(
    session,
    *,
    run_id: str = "run-1",
    classification_status: str = "done",
    diagnosis: object = None,
) -> Run:
    run = Run(
        id=run_id,
        project_id="proj-1",
        started_at=_now(),
        last_seen_at=_now(),
        status="failure",
        classification_status=classification_status,
        failure_class="tool_execution_error" if classification_status == "done" else None,
        diagnosis=diagnosis,
    )
    session.add(run)
    session.add(
        SpanModel(
            id="span-1", run_id=run_id, parent_id=None, type="tool", name="search",
            input={"query": "x"}, output={"result": "ok"}, error=None,
            started_at=_now(), duration_ms=5.0, fingerprint="fp-1",
        )
    )
    await session.commit()
    return await crud.get_run_with_spans_by_id(session, run_id=run_id)


def _spec() -> AssertionSpec:
    return AssertionSpec(
        must_call_tools=["search"],
        must_not_call_tools=[],
        max_steps=None,
        no_exception=True,
        rationale="search must be called",
        model="test-model",
    )


def _fail_if_called(*args, **kwargs):
    pytest.fail("generate_fn should not be called")


# --- entrypoint shape validation ---------------------------------------------


async def test_rejects_malformed_entrypoint_before_touching_db(db_session):
    run = await _make_run(db_session, classification_status="none")  # would also 409 if reached

    with pytest.raises(EntrypointFormatError, match="expected 'module.path:function_name'"):
        await generate_test_files_for_run(
            run, "no-colon-here", db_session, Settings(), generate_fn=_fail_if_called
        )


@pytest.mark.parametrize("bad_entrypoint", ["", ":fn", "mod:", "mod::fn", "1mod:fn", "mod:1fn"])
async def test_rejects_various_malformed_entrypoint_shapes(db_session, bad_entrypoint):
    run = await _make_run(db_session)
    with pytest.raises(EntrypointFormatError):
        await generate_test_files_for_run(
            run, bad_entrypoint, db_session, Settings(), generate_fn=_fail_if_called
        )


# --- classification gate ------------------------------------------------------


async def test_raises_when_not_classified_and_no_existing_spec(db_session):
    run = await _make_run(db_session, classification_status="none")

    with pytest.raises(RunNotClassifiedError):
        await generate_test_files_for_run(
            run, "mod.path:fn", db_session, Settings(), generate_fn=lambda *a: _spec()
        )


async def test_skips_classification_gate_when_spec_already_persisted(db_session):
    # Not classified (classification_status="none"), but already has a spec
    # from a prior run of this chunk -- must not re-gate or re-invoke Sonnet.
    run = await _make_run(
        db_session, classification_status="none", diagnosis={"assertion_spec": _PERSISTED_SPEC}
    )

    result = await generate_test_files_for_run(
        run, "mod.path:fn", db_session, Settings(), generate_fn=_fail_if_called
    )
    assert result.assertion_spec == _PERSISTED_SPEC


# --- happy paths ---------------------------------------------------------------


async def test_generates_spec_and_renders_when_none_exists_yet(db_session):
    run = await _make_run(db_session, diagnosis={"text": "diag"})

    result = await generate_test_files_for_run(
        run, "examples.langgraph_demo:main", db_session, Settings(), generate_fn=lambda *a: _spec()
    )

    assert result.run_id == "run-1"
    assert result.fixture_filename == "fixture_run_1.py"
    assert result.test_filename == "test_run_1.py"
    assert result.assertion_spec["must_call_tools"] == ["search"]
    assert "MUST_CALL_TOOLS = ['search']" in result.test_source
    assert "from fixture_run_1 import RECORDED_INPUT, TOOL_SPANS" in result.test_source
    assert "ENTRYPOINT = 'examples.langgraph_demo:main'" in result.test_source
    ast.parse(result.test_source)
    ast.parse(result.fixture_source)

    # the new spec was actually persisted onto the run, same as the
    # standalone POST /v1/runs/{run_id}/assertion-spec route would do.
    refetched = await db_session.get(Run, "run-1")
    assert refetched.diagnosis["assertion_spec"]["must_call_tools"] == ["search"]


async def test_reuses_existing_spec_without_recalling_sonnet(db_session):
    run = await _make_run(db_session, diagnosis={"assertion_spec": _PERSISTED_SPEC})

    result = await generate_test_files_for_run(
        run, "examples.langgraph_demo:main", db_session, Settings(), generate_fn=_fail_if_called
    )

    assert result.assertion_spec == _PERSISTED_SPEC
    assert "MUST_CALL_TOOLS = ['search']" in result.test_source


async def test_reuses_existing_spec_even_when_sonnet_unconfigured(db_session):
    # Settings() with no anthropic_api_key would make generate_assertion_spec
    # raise AssertionSpecNotConfigured -- but since a spec already exists,
    # that path is never reached.
    run = await _make_run(db_session, diagnosis={"assertion_spec": _PERSISTED_SPEC})

    result = await generate_test_files_for_run(
        run, "examples.langgraph_demo:main", db_session, Settings(anthropic_api_key=None)
    )
    assert result.assertion_spec == _PERSISTED_SPEC


async def test_propagates_assertion_spec_not_configured_when_new_spec_needed(db_session):
    run = await _make_run(db_session, diagnosis={"text": "diag"})

    with pytest.raises(AssertionSpecNotConfigured):
        await generate_test_files_for_run(
            run, "examples.langgraph_demo:main", db_session, Settings(anthropic_api_key=None)
        )


async def test_unclassified_run_with_null_assertion_spec_still_gates(db_session):
    # diagnosis={"assertion_spec": None} (explicitly null, e.g. left over
    # from a prior failed generation attempt) must be treated the same as a
    # missing key -- still needs a spec generated, so the classification
    # gate must still apply.
    run = await _make_run(
        db_session, classification_status="none", diagnosis={"assertion_spec": None}
    )

    with pytest.raises(RunNotClassifiedError):
        await generate_test_files_for_run(
            run, "examples.langgraph_demo:main", db_session, Settings(), generate_fn=lambda *a: _spec()
        )
