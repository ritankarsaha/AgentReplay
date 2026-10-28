from __future__ import annotations

from datetime import datetime, timezone

import app.routers.regression as regression_router
from app.regression import InvalidStatusTransition

from .conftest import OTHER_API_KEY, TEST_PROJECT_ID, auth_headers
from .test_spans import _span


def _fake_case(**overrides):
    """Built in-memory (never inserted), so every `server_default` column
    must be set explicitly — those defaults only apply on a real INSERT.
    """
    from app.models import RegressionCase

    now = datetime.now(timezone.utc)
    defaults = dict(
        id="case-1",
        project_id=TEST_PROJECT_ID,
        source_run_id="run-1",
        title="a case",
        entrypoint="mod.path:fn",
        recorded_input={"q": "hi"},
        tool_spans=[],
        assertion_spec={"must_call_tools": ["search"]},
        priority="P1",
        status="proposed",
        evidence_level="native_structured",
        source_case_key=None,
        incident_id=None,
        external_url=None,
        observed_at=None,
        created_by=None,
        extra_metadata={},
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return RegressionCase(**defaults)


async def _persist_fake_case(run, db, settings, *, entrypoint, title, priority, created_by):
    """A `create_case_from_run` stand-in that actually inserts, for tests that
    chain a follow-up request needing the row to really exist in the DB.
    """
    from app.models import RegressionCase

    case = RegressionCase(
        id="case-1",
        project_id=run.project_id,
        source_run_id=run.id,
        title=title or "a case",
        entrypoint=entrypoint,
        recorded_input={"q": "hi"},
        tool_spans=[],
        assertion_spec={"must_call_tools": ["search"]},
        priority=priority,
        status="proposed",
        evidence_level="native_structured",
        created_by=created_by,
    )
    db.add(case)
    await db.flush()
    await db.refresh(case)
    return case


# --- POST /v1/regression-cases (promote a run) ------------------------------


async def test_register_case_run_not_found(client):
    resp = await client.post(
        "/v1/regression-cases",
        json={"run_id": "does-not-exist", "entrypoint": "mod.path:fn"},
        headers=auth_headers(),
    )
    assert resp.status_code == 404


async def test_register_case_malformed_entrypoint(client):
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="run-1")]},
        headers=auth_headers(),
    )
    resp = await client.post(
        "/v1/regression-cases",
        json={"run_id": "run-1", "entrypoint": "not-a-valid-spec"},
        headers=auth_headers(),
    )
    assert resp.status_code == 400


async def test_register_case_run_not_classified_real_flow(client):
    # A real, unclassified run (classification_status defaults to "none") --
    # no monkeypatching, exercises the real create_case_from_run().
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="run-1")]},
        headers=auth_headers(),
    )
    resp = await client.post(
        "/v1/regression-cases",
        json={"run_id": "run-1", "entrypoint": "mod.path:fn"},
        headers=auth_headers(),
    )
    assert resp.status_code == 409


async def test_register_case_happy_path(client, monkeypatch):
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="run-1")]},
        headers=auth_headers(),
    )

    async def fake_create(run, db, settings, *, entrypoint, title, priority, created_by):
        assert run.id == "run-1"
        assert entrypoint == "mod.path:fn"
        assert priority == "P0"
        return _fake_case(priority="P0")

    monkeypatch.setattr(regression_router, "create_case_from_run", fake_create)

    resp = await client.post(
        "/v1/regression-cases",
        json={"run_id": "run-1", "entrypoint": "mod.path:fn", "priority": "P0"},
        headers=auth_headers(),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == "case-1"
    assert body["status"] == "proposed"
    assert body["priority"] == "P0"
    assert body["evidence_level"] == "native_structured"


# --- POST /v1/regression-cases/capture-production ----------------------------


async def test_capture_production_happy_path(client, monkeypatch):
    async def fake_create(db, **kw):
        assert kw["project_id"] == TEST_PROJECT_ID
        assert kw["entrypoint"] == "mod.path:fn"
        return _fake_case(evidence_level="derived_summary", source_run_id=None)

    monkeypatch.setattr(regression_router, "create_case_from_capture", fake_create)

    resp = await client.post(
        "/v1/regression-cases/capture-production",
        json={
            "entrypoint": "mod.path:fn",
            "recorded_input": {"q": "hi"},
            "incident_id": "INC-1",
        },
        headers=auth_headers(),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["evidence_level"] == "derived_summary"
    assert body["source_run_id"] is None


async def test_capture_production_malformed_entrypoint(client):
    resp = await client.post(
        "/v1/regression-cases/capture-production",
        json={"entrypoint": "not-a-valid-spec"},
        headers=auth_headers(),
    )
    assert resp.status_code == 400


# --- GET /v1/regression-cases -------------------------------------------------


async def test_list_cases_empty(client):
    resp = await client.get("/v1/regression-cases", headers=auth_headers())
    assert resp.status_code == 200
    assert resp.json() == {"cases": []}


async def test_list_cases_scoped_to_project_and_filters_by_status(client, monkeypatch):
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="run-1")]},
        headers=auth_headers(),
    )

    monkeypatch.setattr(regression_router, "create_case_from_run", _persist_fake_case)
    await client.post(
        "/v1/regression-cases",
        json={"run_id": "run-1", "entrypoint": "mod.path:fn"},
        headers=auth_headers(),
    )

    # Cross-tenant isolation.
    resp = await client.get("/v1/regression-cases", headers=auth_headers(OTHER_API_KEY))
    assert resp.json() == {"cases": []}

    # Status filter: created as "proposed", so "active" filter excludes it.
    resp = await client.get("/v1/regression-cases?status=active", headers=auth_headers())
    assert resp.json() == {"cases": []}

    resp = await client.get("/v1/regression-cases?status=proposed", headers=auth_headers())
    assert len(resp.json()["cases"]) == 1


# --- GET/PATCH /v1/regression-cases/{case_id} ---------------------------------


async def test_get_case_not_found(client):
    resp = await client.get("/v1/regression-cases/does-not-exist", headers=auth_headers())
    assert resp.status_code == 404


async def _register_real_case(client, monkeypatch) -> str:
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="run-1")]},
        headers=auth_headers(),
    )

    monkeypatch.setattr(regression_router, "create_case_from_run", _persist_fake_case)
    resp = await client.post(
        "/v1/regression-cases",
        json={"run_id": "run-1", "entrypoint": "mod.path:fn"},
        headers=auth_headers(),
    )
    return resp.json()["id"]


async def test_update_case_status_proposed_to_active(client, monkeypatch):
    case_id = await _register_real_case(client, monkeypatch)

    resp = await client.patch(
        f"/v1/regression-cases/{case_id}",
        json={"status": "active"},
        headers=auth_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


async def test_update_case_status_rejects_invalid_transition(client, monkeypatch):
    case_id = await _register_real_case(client, monkeypatch)
    await client.patch(
        f"/v1/regression-cases/{case_id}", json={"status": "active"}, headers=auth_headers()
    )

    # active -> proposed is not an allowed edge.
    resp = await client.patch(
        f"/v1/regression-cases/{case_id}", json={"status": "proposed"}, headers=auth_headers()
    )
    assert resp.status_code == 409


async def test_update_case_status_rejects_unknown_status_value(client, monkeypatch):
    case_id = await _register_real_case(client, monkeypatch)

    resp = await client.patch(
        f"/v1/regression-cases/{case_id}", json={"status": "not-a-real-status"}, headers=auth_headers()
    )
    assert resp.status_code == 400


async def test_update_case_status_not_found(client):
    resp = await client.patch(
        "/v1/regression-cases/does-not-exist", json={"status": "active"}, headers=auth_headers()
    )
    assert resp.status_code == 404


# --- POST/GET /v1/regression-cases/{case_id}/results --------------------------


async def test_register_and_list_results(client, monkeypatch):
    case_id = await _register_real_case(client, monkeypatch)

    resp = await client.post(
        f"/v1/regression-cases/{case_id}/results",
        json={
            "agent_version": "sha1",
            "trials": 3,
            "passes": 2,
            "verdict": "warn",
            "details": [
                {"trial": 0, "passed": True, "error": None, "duration_ms": 1.0},
                {"trial": 1, "passed": True, "error": None, "duration_ms": 1.0},
                {"trial": 2, "passed": False, "error": "boom", "duration_ms": 1.0},
            ],
        },
        headers=auth_headers(),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["case_id"] == case_id
    assert body["pass_rate"] == 2 / 3
    assert body["verdict"] == "warn"
    assert len(body["details"]) == 3

    resp = await client.get(f"/v1/regression-cases/{case_id}/results", headers=auth_headers())
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 1


async def test_register_result_case_not_found(client):
    resp = await client.post(
        "/v1/regression-cases/does-not-exist/results",
        json={"trials": 1, "passes": 1, "verdict": "pass"},
        headers=auth_headers(),
    )
    assert resp.status_code == 404


async def test_list_results_case_not_found(client):
    resp = await client.get(
        "/v1/regression-cases/does-not-exist/results", headers=auth_headers()
    )
    assert resp.status_code == 404
