"""Self-serve / multi-tenant behavior: account endpoints, viewer delegation,
hashed keys, tenancy guard, and abuse limits."""
from __future__ import annotations

from sqlalchemy import select

from app.config import Settings
from app.db import get_db
from app.main import app
from app.models import Project
from app.security import hash_api_key

from .conftest import (
    OTHER_API_KEY,
    OTHER_PROJECT_ID,
    OWNER_EMAIL,
    TEST_API_KEY,
    TEST_PROJECT_ID,
    auth_headers,
    viewer_headers,
)
from .test_spans import _span


async def _create(client, name="My Agent", email="new@example.com"):
    return await client.post(
        "/v1/account/projects", json={"name": name}, headers=viewer_headers(email)
    )


# --- account endpoints -----------------------------------------------------

async def test_create_project_returns_key_once_and_it_works(client):
    resp = await _create(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"].startswith("proj_")
    assert body["api_key"].startswith("ar_")
    assert body["api_key_prefix"] == body["api_key"][:11]

    listed = await client.get("/v1/account/projects", headers=viewer_headers("new@example.com"))
    assert [p["id"] for p in listed.json()["projects"]] == [body["id"]]
    assert "api_key" not in listed.json()["projects"][0]

    ingest = await client.post(
        "/v1/spans",
        json={"project_id": body["id"], "spans": [_span(run_id="r-new")]},
        headers=auth_headers(body["api_key"]),
    )
    assert ingest.status_code == 202


async def test_api_key_is_stored_hashed(client):
    body = (await _create(client)).json()
    override = app.dependency_overrides[get_db]
    async for db in override():
        project = await db.scalar(select(Project).where(Project.id == body["id"]))
        assert project.api_key_hash == hash_api_key(body["api_key"])
        assert body["api_key"] not in (project.api_key_hash, project.api_key_prefix)


async def test_account_endpoints_reject_project_keys_and_bad_tokens(client):
    assert (await client.get("/v1/account/projects", headers=auth_headers())).status_code == 401
    bad = {"Authorization": "Bearer nope", "X-Viewer-Email": OWNER_EMAIL}
    assert (await client.get("/v1/account/projects", headers=bad)).status_code == 401
    no_email = {"Authorization": viewer_headers()["Authorization"]}
    assert (await client.get("/v1/account/projects", headers=no_email)).status_code == 400


async def test_viewer_token_disabled_when_unset(client, monkeypatch):
    monkeypatch.delenv("AGENTREPLAY_INGEST_VIEWER_SERVICE_TOKEN")
    resp = await client.get("/v1/account/projects", headers=viewer_headers())
    assert resp.status_code == 401


async def test_project_limit_enforced(client, monkeypatch):
    monkeypatch.setenv("AGENTREPLAY_INGEST_MAX_PROJECTS_PER_USER", "2")
    assert (await _create(client, "a")).status_code == 201
    assert (await _create(client, "b")).status_code == 201
    assert (await _create(client, "c")).status_code == 409


async def test_rotate_key_invalidates_old_key(client):
    created = (await _create(client)).json()
    rotated = await client.post(
        f"/v1/account/projects/{created['id']}/rotate-key", headers=viewer_headers("new@example.com")
    )
    assert rotated.status_code == 200
    new_key = rotated.json()["api_key"]
    assert new_key != created["api_key"]

    old = await client.get("/v1/runs", headers=auth_headers(created["api_key"]))
    new = await client.get("/v1/runs", headers=auth_headers(new_key))
    assert (old.status_code, new.status_code) == (401, 200)


async def test_cannot_rotate_someone_elses_project(client):
    resp = await client.post(
        f"/v1/account/projects/{OTHER_PROJECT_ID}/rotate-key", headers=viewer_headers()
    )
    assert resp.status_code == 404


# --- viewer delegation -----------------------------------------------------

async def test_viewer_reads_only_projects_it_owns(client):
    await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="mine")]},
        headers=auth_headers(),
    )
    own = await client.get("/v1/runs", headers=viewer_headers(project_id=TEST_PROJECT_ID))
    assert own.status_code == 200 and [r["id"] for r in own.json()["runs"]] == ["mine"]

    # same user, someone else's project -> indistinguishable from nonexistent
    other = await client.get("/v1/runs", headers=viewer_headers(project_id=OTHER_PROJECT_ID))
    assert other.status_code == 404
    ghost = await client.get("/v1/runs", headers=viewer_headers(project_id="nope"))
    assert ghost.status_code == 404

    # project id is mandatory for data routes
    assert (await client.get("/v1/runs", headers=viewer_headers())).status_code == 400


# --- tenancy + limits ------------------------------------------------------

async def test_cannot_append_spans_to_another_projects_run(client):
    await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": [_span(run_id="victim")]},
        headers=auth_headers(),
    )
    resp = await client.post(
        "/v1/spans", json={"project_id": OTHER_PROJECT_ID, "spans": [_span(run_id="victim")]},
        headers=auth_headers(OTHER_API_KEY),
    )
    assert resp.status_code == 409
    detail = await client.get("/v1/runs/victim", headers=auth_headers())
    assert len(detail.json()["spans"]) == 1


async def test_project_id_in_batch_is_optional_but_checked_if_present(client):
    ok = await client.post("/v1/spans", json={"spans": [_span()]}, headers=auth_headers())
    assert ok.status_code == 202
    bad = await client.post(
        "/v1/spans", json={"project_id": OTHER_PROJECT_ID, "spans": [_span()]}, headers=auth_headers()
    )
    assert bad.status_code == 403


async def test_batch_size_limit(client, monkeypatch):
    monkeypatch.setenv("AGENTREPLAY_INGEST_MAX_SPANS_PER_BATCH", "2")
    resp = await client.post(
        "/v1/spans", json={"spans": [_span(), _span(), _span()]}, headers=auth_headers()
    )
    assert resp.status_code == 413


async def test_ingest_rate_limit_is_per_project(client, monkeypatch):
    monkeypatch.setenv("AGENTREPLAY_INGEST_INGEST_RATE_LIMIT_PER_MIN", "2")
    for _ in range(2):
        assert (await client.post("/v1/spans", json={"spans": [_span()]}, headers=auth_headers())).status_code == 202
    limited = await client.post("/v1/spans", json={"spans": [_span()]}, headers=auth_headers())
    assert limited.status_code == 429 and "retry-after" in limited.headers
    other = await client.post("/v1/spans", json={"spans": [_span(run_id="other-run")]}, headers=auth_headers(OTHER_API_KEY))
    assert other.status_code == 202


async def test_request_body_size_limit(client):
    # The middleware is built with the cap at app-construction time, so use a
    # body larger than the 5MB default.
    big = "x" * 5_100_000
    resp = await client.post(
        "/v1/spans",
        content=('{"spans": [], "pad": "%s"}' % big).encode(),
        headers={**auth_headers(), "Content-Type": "application/json"},
    )
    assert resp.status_code == 413
