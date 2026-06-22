from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import app.routers.spans as spans_router

from .conftest import TEST_PROJECT_ID, auth_headers


def _fail_span(*, run_id: str = "run-1", span_id: Optional[str] = None) -> dict:
    return {
        "id": span_id or str(uuid.uuid4()),
        "run_id": run_id,
        "parent_id": None,
        "type": "checkpoint",
        "name": "agentreplay.fail",
        "input": {"reason": "boom"},
        "output": None,
        "error": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": 0.0,
        "fingerprint": "fp-fail",
    }


def _ok_span(*, run_id: str = "run-1") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "run_id": run_id,
        "parent_id": None,
        "type": "llm",
        "name": "anthropic.messages.create",
        "input": {"model": "claude-3"},
        "output": {"id": "msg_1"},
        "error": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": 5.0,
        "fingerprint": "fp-ok",
    }


async def test_fail_span_enqueues_classification_when_backend_configured(client, monkeypatch):
    monkeypatch.setenv("AGENTREPLAY_INGEST_ANTHROPIC_API_KEY", "fake-key-for-test")
    enqueued = []
    monkeypatch.setattr(spans_router, "enqueue_classification", lambda run_id: enqueued.append(run_id))

    resp = await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_fail_span(run_id="run-enqueue-1")]},
        headers=auth_headers(),
    )
    assert resp.status_code == 202
    assert enqueued == ["run-enqueue-1"]


async def test_normal_batch_does_not_enqueue_classification(client, monkeypatch):
    monkeypatch.setenv("AGENTREPLAY_INGEST_ANTHROPIC_API_KEY", "fake-key-for-test")
    enqueued = []
    monkeypatch.setattr(spans_router, "enqueue_classification", lambda run_id: enqueued.append(run_id))

    resp = await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_ok_span(run_id="run-no-fail")]},
        headers=auth_headers(),
    )
    assert resp.status_code == 202
    assert enqueued == []


async def test_fail_span_does_not_enqueue_when_classifier_not_configured(client, monkeypatch):
    monkeypatch.delenv("AGENTREPLAY_INGEST_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AGENTREPLAY_INGEST_NIM_API_KEY", raising=False)
    enqueued = []
    monkeypatch.setattr(spans_router, "enqueue_classification", lambda run_id: enqueued.append(run_id))

    resp = await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_fail_span(run_id="run-no-key")]},
        headers=auth_headers(),
    )
    assert resp.status_code == 202
    assert enqueued == []


async def test_enqueue_failure_does_not_break_ingestion(client, monkeypatch):
    monkeypatch.setenv("AGENTREPLAY_INGEST_ANTHROPIC_API_KEY", "fake-key-for-test")

    def boom(run_id: str) -> None:
        raise RuntimeError("redis is down")

    monkeypatch.setattr(spans_router, "enqueue_classification", boom)

    resp = await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [_fail_span(run_id="run-redis-down")]},
        headers=auth_headers(),
    )
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 1}


async def test_multiple_failed_runs_in_one_batch_each_enqueued(client, monkeypatch):
    monkeypatch.setenv("AGENTREPLAY_INGEST_ANTHROPIC_API_KEY", "fake-key-for-test")
    enqueued = []
    monkeypatch.setattr(spans_router, "enqueue_classification", lambda run_id: enqueued.append(run_id))

    spans = [_fail_span(run_id="run-multi-a"), _fail_span(run_id="run-multi-b")]
    resp = await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": spans}, headers=auth_headers()
    )
    assert resp.status_code == 202
    assert set(enqueued) == {"run-multi-a", "run-multi-b"}
