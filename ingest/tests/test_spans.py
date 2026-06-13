from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from .conftest import OTHER_API_KEY, TEST_API_KEY, TEST_PROJECT_ID, auth_headers


def _span(
    *,
    run_id: str = "run-1",
    span_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    type_: str = "llm",
    name: str = "anthropic.messages.create",
    started_at: Optional[datetime] = None,
    duration_ms: float = 12.5,
    fingerprint: str = "fp-1",
    output: Optional[dict] = None,
    error: Optional[dict] = None,
) -> dict:
    """Builds a payload matching `agentreplay.span.Span.to_dict()` — the SDK wire format."""
    return {
        "id": span_id or str(uuid.uuid4()),
        "run_id": run_id,
        "parent_id": parent_id,
        "type": type_,
        "name": name,
        "input": {"model": "claude-3", "messages": []},
        "output": output if output is not None else {"id": "msg_1"},
        "error": error,
        "started_at": (started_at or datetime.now(timezone.utc)).isoformat(),
        "duration_ms": duration_ms,
        "fingerprint": fingerprint,
    }


async def test_ingest_spans_accepted(client):
    resp = await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span()]},
        headers=auth_headers(),
    )
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 1}


async def test_ingest_empty_batch_accepted(client):
    resp = await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": []}, headers=auth_headers()
    )
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 0}


async def test_missing_auth_header_rejected(client):
    resp = await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": [_span()]}
    )
    assert resp.status_code == 401


async def test_invalid_api_key_rejected(client):
    resp = await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_span()]},
        headers=auth_headers("not-a-real-key"),
    )
    assert resp.status_code == 401


async def test_project_id_mismatch_rejected(client):
    resp = await client.post(
        "/v1/spans",
        json={"project_id": "someone-elses-project", "spans": [_span()]},
        headers=auth_headers(TEST_API_KEY),
    )
    assert resp.status_code == 403


async def test_ingest_creates_run_lazily(client):
    span = _span(run_id="run-abc")
    await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": [span]}, headers=auth_headers()
    )

    resp = await client.get("/v1/runs/run-abc", headers=auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "run-abc"
    assert body["project_id"] == TEST_PROJECT_ID
    assert body["status"] == "ok"
    assert len(body["spans"]) == 1
    assert body["spans"][0]["id"] == span["id"]
    assert body["spans"][0]["fingerprint"] == "fp-1"


async def test_ingest_is_idempotent_on_span_id(client):
    span = _span(run_id="run-dup")
    payload = {"project_id": TEST_PROJECT_ID, "spans": [span]}

    r1 = await client.post("/v1/spans", json=payload, headers=auth_headers())
    r2 = await client.post("/v1/spans", json=payload, headers=auth_headers())
    assert r1.status_code == 202
    assert r2.status_code == 202

    resp = await client.get("/v1/runs/run-dup", headers=auth_headers())
    assert len(resp.json()["spans"]) == 1


async def test_second_batch_extends_last_seen_at(client):
    base = datetime.now(timezone.utc)
    first = _span(run_id="run-multi", started_at=base)
    second = _span(run_id="run-multi", started_at=base + timedelta(seconds=5))

    await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": [first]}, headers=auth_headers()
    )
    await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": [second]}, headers=auth_headers()
    )

    resp = await client.get("/v1/runs/run-multi", headers=auth_headers())
    body = resp.json()
    assert len(body["spans"]) == 2

    # SQLite (test db) round-trips TIMESTAMP columns as naive UTC; Postgres
    # (prod) preserves tzinfo. Compare naive to be agnostic to the dialect.
    started_at = datetime.fromisoformat(body["started_at"]).replace(tzinfo=None)
    last_seen_at = datetime.fromisoformat(body["last_seen_at"]).replace(tzinfo=None)
    assert started_at == base.replace(tzinfo=None)
    assert last_seen_at == (base + timedelta(seconds=5)).replace(tzinfo=None)


async def test_run_not_visible_to_other_project(client):
    span = _span(run_id="run-private")
    await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": [span]}, headers=auth_headers()
    )

    resp = await client.get("/v1/runs/run-private", headers=auth_headers(OTHER_API_KEY))
    assert resp.status_code == 404


async def test_ingest_sets_run_lifecycle_metadata(client):
    span = _span(run_id="run-meta")
    resp = await client.post(
        "/v1/spans",
        json={
            "project_id": TEST_PROJECT_ID,
            "agent_version": "abc1234",
            "framework": "langgraph",
            "spans": [span],
        },
        headers=auth_headers(),
    )
    assert resp.status_code == 202

    resp = await client.get("/v1/runs/run-meta", headers=auth_headers())
    body = resp.json()
    assert body["agent_version"] == "abc1234"
    assert body["framework"] == "langgraph"


async def test_ingest_without_metadata_leaves_run_fields_null(client):
    span = _span(run_id="run-no-meta")
    resp = await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": [span]}, headers=auth_headers()
    )
    assert resp.status_code == 202

    resp = await client.get("/v1/runs/run-no-meta", headers=auth_headers())
    body = resp.json()
    assert body["agent_version"] is None
    assert body["framework"] is None


async def test_later_batch_without_metadata_does_not_clobber_existing(client):
    base = datetime.now(timezone.utc)
    first = _span(run_id="run-keep-meta", started_at=base)
    second = _span(run_id="run-keep-meta", started_at=base + timedelta(seconds=5))

    await client.post(
        "/v1/spans",
        json={
            "project_id": TEST_PROJECT_ID,
            "agent_version": "abc1234",
            "framework": "langgraph",
            "spans": [first],
        },
        headers=auth_headers(),
    )
    await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": [second]}, headers=auth_headers()
    )

    resp = await client.get("/v1/runs/run-keep-meta", headers=auth_headers())
    body = resp.json()
    assert body["agent_version"] == "abc1234"
    assert body["framework"] == "langgraph"
    assert len(body["spans"]) == 2


async def test_batch_with_multiple_runs_creates_both(client):
    spans = [_span(run_id="run-x"), _span(run_id="run-y")]
    resp = await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": spans}, headers=auth_headers()
    )
    assert resp.json() == {"accepted": 2}

    for run_id in ("run-x", "run-y"):
        resp = await client.get(f"/v1/runs/{run_id}", headers=auth_headers())
        assert resp.status_code == 200
        assert len(resp.json()["spans"]) == 1
