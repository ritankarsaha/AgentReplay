from __future__ import annotations

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
