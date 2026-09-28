from __future__ import annotations

import app.routers.runs as runs_router
from app.assertion_spec import AssertionSpec, AssertionSpecNotConfigured, RunNotClassifiedError
from app.testgen import EntrypointFormatError, GeneratedTestFiles

from .conftest import OTHER_API_KEY, TEST_PROJECT_ID, auth_headers
from .test_spans import _span


async def test_list_runs_empty(client):
    resp = await client.get("/v1/runs", headers=auth_headers())
    assert resp.status_code == 200
    assert resp.json() == {"runs": []}


async def test_list_runs_after_ingest(client):
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="run-1")]},
        headers=auth_headers(),
    )
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="run-2")]},
        headers=auth_headers(),
    )

    resp = await client.get("/v1/runs", headers=auth_headers())
    assert resp.status_code == 200
    run_ids = {r["id"] for r in resp.json()["runs"]}
    assert run_ids == {"run-1", "run-2"}


async def test_list_runs_scoped_to_project(client):
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="run-1")]},
        headers=auth_headers(),
    )

    resp = await client.get("/v1/runs", headers=auth_headers(OTHER_API_KEY))
    assert resp.status_code == 200
    assert resp.json() == {"runs": []}


async def test_get_run_not_found(client):
    resp = await client.get("/v1/runs/does-not-exist", headers=auth_headers())
    assert resp.status_code == 404


async def test_healthz(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def _fake_spec(**overrides) -> AssertionSpec:
    defaults = dict(
        must_call_tools=["validate_output"],
        must_not_call_tools=["risky_tool"],
        max_steps=None,
        no_exception=True,
        rationale="because X",
        model="test-model",
    )
    defaults.update(overrides)
    return AssertionSpec(**defaults)


async def test_create_assertion_spec_run_not_found(client):
    resp = await client.post("/v1/runs/does-not-exist/assertion-spec", headers=auth_headers())
    assert resp.status_code == 404


async def test_create_assertion_spec_scoped_to_project(client):
    # A run that exists, but for a different project -- must 404, not leak
    # cross-tenant existence (same posture as GET /v1/runs/{run_id}).
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="run-1")]},
        headers=auth_headers(),
    )

    resp = await client.post(
        "/v1/runs/run-1/assertion-spec", headers=auth_headers(OTHER_API_KEY)
    )
    assert resp.status_code == 404


async def test_create_assertion_spec_returns_409_when_not_classified(client):
    # A real, unclassified run (classification_status defaults to "none") --
    # no monkeypatching, this exercises the real generate_assertion_spec_for_run().
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="run-1")]},
        headers=auth_headers(),
    )

    resp = await client.post("/v1/runs/run-1/assertion-spec", headers=auth_headers())
    assert resp.status_code == 409
    assert "not been classified" in resp.json()["detail"]


async def test_create_assertion_spec_returns_503_when_not_configured(client, monkeypatch):
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="run-1")]},
        headers=auth_headers(),
    )

    async def fake_generate(run, db, settings):
        raise AssertionSpecNotConfigured("AGENTREPLAY_INGEST_ANTHROPIC_API_KEY is not set")

    monkeypatch.setattr(runs_router, "generate_assertion_spec_for_run", fake_generate)

    resp = await client.post("/v1/runs/run-1/assertion-spec", headers=auth_headers())
    assert resp.status_code == 503
    assert "ANTHROPIC_API_KEY" in resp.json()["detail"]


async def test_create_assertion_spec_happy_path(client, monkeypatch):
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="run-1")]},
        headers=auth_headers(),
    )

    async def fake_generate(run, db, settings):
        assert run.id == "run-1"
        return _fake_spec()

    monkeypatch.setattr(runs_router, "generate_assertion_spec_for_run", fake_generate)

    resp = await client.post("/v1/runs/run-1/assertion-spec", headers=auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["must_call_tools"] == ["validate_output"]
    assert body["must_not_call_tools"] == ["risky_tool"]
    assert body["max_steps"] is None
    assert body["no_exception"] is True
    assert body["rationale"] == "because X"
    assert body["model"] == "test-model"
    assert body["semantic_rubric"] is None


async def test_create_assertion_spec_happy_path_with_semantic_rubric(client, monkeypatch):
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="run-1")]},
        headers=auth_headers(),
    )

    async def fake_generate(run, db, settings):
        return _fake_spec(semantic_rubric="Output must not contain markdown artifacts like '**'.")

    monkeypatch.setattr(runs_router, "generate_assertion_spec_for_run", fake_generate)

    resp = await client.post("/v1/runs/run-1/assertion-spec", headers=auth_headers())
    assert resp.status_code == 200
    assert resp.json()["semantic_rubric"] == "Output must not contain markdown artifacts like '**'."


async def test_create_assertion_spec_propagates_run_not_classified_from_real_flow(client, monkeypatch):
    # Belt-and-suspenders: even if generate_assertion_spec_for_run is NOT
    # monkeypatched, a real RunNotClassifiedError raised deeper still maps
    # to 409 (covers the route's except clause directly, not just via the
    # always-unclassified-by-default path above).
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="run-1")]},
        headers=auth_headers(),
    )

    async def fake_generate(run, db, settings):
        raise RunNotClassifiedError(run.id)

    monkeypatch.setattr(runs_router, "generate_assertion_spec_for_run", fake_generate)

    resp = await client.post("/v1/runs/run-1/assertion-spec", headers=auth_headers())
    assert resp.status_code == 409


# --- POST /v1/runs/{run_id}/generate-test (chunk 4.5) ------------------------
#
# `generate_test_files_for_run()` itself is fully unit-tested in
# test_testgen.py against a real in-memory DB; same monkeypatch-the-one-seam
# pattern as the assertion-spec tests above for the route's exception-to-
# HTTP-status mapping, since there's no public HTTP way to mark a run
# "classified" or pre-seed a real Sonnet-authored spec.


def _fake_generated_files(**overrides) -> GeneratedTestFiles:
    defaults = dict(
        run_id="run-1",
        fixture_filename="fixture_run_1.py",
        fixture_source="RUN_ID = 'run-1'\n",
        test_filename="test_run_1.py",
        test_source="def test_run_1(): assert True\n",
        assertion_spec={"must_call_tools": ["search"]},
    )
    defaults.update(overrides)
    return GeneratedTestFiles(**defaults)


async def test_generate_test_run_not_found(client):
    resp = await client.post(
        "/v1/runs/does-not-exist/generate-test",
        json={"entrypoint": "mod.path:fn"},
        headers=auth_headers(),
    )
    assert resp.status_code == 404


async def test_generate_test_scoped_to_project(client):
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="run-1")]},
        headers=auth_headers(),
    )

    resp = await client.post(
        "/v1/runs/run-1/generate-test",
        json={"entrypoint": "mod.path:fn"},
        headers=auth_headers(OTHER_API_KEY),
    )
    assert resp.status_code == 404


async def test_generate_test_returns_400_for_malformed_entrypoint(client, monkeypatch):
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="run-1")]},
        headers=auth_headers(),
    )

    async def fake_generate(run, entrypoint, db, settings):
        raise EntrypointFormatError(entrypoint)

    monkeypatch.setattr(runs_router, "generate_test_files_for_run", fake_generate)

    resp = await client.post(
        "/v1/runs/run-1/generate-test", json={"entrypoint": "no-colon"}, headers=auth_headers()
    )
    assert resp.status_code == 400
    assert "module.path:function_name" in resp.json()["detail"]


async def test_generate_test_returns_409_when_not_classified(client):
    # A real, unclassified run -- exercises the real generate_test_files_for_run().
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="run-1")]},
        headers=auth_headers(),
    )

    resp = await client.post(
        "/v1/runs/run-1/generate-test",
        json={"entrypoint": "mod.path:fn"},
        headers=auth_headers(),
    )
    assert resp.status_code == 409
    assert "not been classified" in resp.json()["detail"]


async def test_generate_test_returns_503_when_not_configured(client, monkeypatch):
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="run-1")]},
        headers=auth_headers(),
    )

    async def fake_generate(run, entrypoint, db, settings):
        raise AssertionSpecNotConfigured("AGENTREPLAY_INGEST_ANTHROPIC_API_KEY is not set")

    monkeypatch.setattr(runs_router, "generate_test_files_for_run", fake_generate)

    resp = await client.post(
        "/v1/runs/run-1/generate-test", json={"entrypoint": "mod.path:fn"}, headers=auth_headers()
    )
    assert resp.status_code == 503
    assert "ANTHROPIC_API_KEY" in resp.json()["detail"]


async def test_generate_test_happy_path(client, monkeypatch):
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="run-1")]},
        headers=auth_headers(),
    )

    async def fake_generate(run, entrypoint, db, settings):
        assert run.id == "run-1"
        assert entrypoint == "mod.path:fn"
        return _fake_generated_files()

    monkeypatch.setattr(runs_router, "generate_test_files_for_run", fake_generate)

    resp = await client.post(
        "/v1/runs/run-1/generate-test", json={"entrypoint": "mod.path:fn"}, headers=auth_headers()
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "run-1"
    assert body["fixture_filename"] == "fixture_run_1.py"
    assert body["test_filename"] == "test_run_1.py"
    assert "def test_run_1" in body["test_source"]
    assert body["assertion_spec"] == {"must_call_tools": ["search"]}


async def test_generate_test_happy_path_with_no_assertion_spec_in_response(client, monkeypatch):
    # GeneratedTestFiles.assertion_spec can legitimately be falsy-but-present
    # is not a case here (it's always populated once generation succeeds —
    # either reused or freshly generated) but the schema field is Optional;
    # confirm None round-trips through the response cleanly regardless.
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="run-1")]},
        headers=auth_headers(),
    )

    async def fake_generate(run, entrypoint, db, settings):
        return _fake_generated_files(assertion_spec=None)

    monkeypatch.setattr(runs_router, "generate_test_files_for_run", fake_generate)

    resp = await client.post(
        "/v1/runs/run-1/generate-test", json={"entrypoint": "mod.path:fn"}, headers=auth_headers()
    )
    assert resp.status_code == 200
    assert resp.json()["assertion_spec"] is None
