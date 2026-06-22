from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from .conftest import TEST_PROJECT_ID, auth_headers


def _span(
    *,
    run_id: str = "run-1",
    span_id: Optional[str] = None,
    type_: str = "llm",
    name: str = "anthropic.messages.create",
    started_at: Optional[datetime] = None,
    fingerprint: str = "fp-1",
    input_: Optional[dict] = None,
    error: Optional[dict] = None,
) -> dict:
    """Builds a payload matching `agentreplay.span.Span.to_dict()` — the SDK wire format."""
    return {
        "id": span_id or str(uuid.uuid4()),
        "run_id": run_id,
        "parent_id": None,
        "type": type_,
        "name": name,
        "input": input_ if input_ is not None else {"model": "claude-3", "messages": []},
        "output": {"id": "msg_1"},
        "error": error,
        "started_at": (started_at or datetime.now(timezone.utc)).isoformat(),
        "duration_ms": 5.0,
        "fingerprint": fingerprint,
    }


def _fail_span(
    *,
    run_id: str = "run-1",
    span_id: Optional[str] = None,
    started_at: Optional[datetime] = None,
    reason: str = "agent crashed",
    failure_class: Optional[str] = None,
    pointed_span_id: Optional[str] = None,
    error: Optional[dict] = None,
) -> dict:
    """Builds an `agentreplay.fail()` span — must match `agentreplay/fail.py`'s shape."""
    payload = {"reason": reason}
    if failure_class is not None:
        payload["failure_class"] = failure_class
    if pointed_span_id is not None:
        payload["span_id"] = pointed_span_id
    return _span(
        run_id=run_id,
        span_id=span_id,
        type_="checkpoint",
        name="agentreplay.fail",
        started_at=started_at,
        fingerprint="fp-fail",
        input_=payload,
        error=error,
    )


async def test_fail_span_marks_run_as_failure(client):
    spans = [_span(run_id="run-fail-1"), _fail_span(run_id="run-fail-1")]
    resp = await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": spans}, headers=auth_headers()
    )
    assert resp.status_code == 202

    resp = await client.get("/v1/runs/run-fail-1", headers=auth_headers())
    body = resp.json()
    assert body["status"] == "failure"


async def test_fail_span_sets_failure_class_and_culprit_span(client):
    fail_span = _fail_span(
        run_id="run-fail-2",
        span_id="fail-span-id",
        failure_class="tool_error_unexpected_output",
        pointed_span_id="culprit-span-id",
    )
    resp = await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [fail_span]},
        headers=auth_headers(),
    )
    assert resp.status_code == 202

    resp = await client.get("/v1/runs/run-fail-2", headers=auth_headers())
    body = resp.json()
    assert body["status"] == "failure"
    assert body["failure_class"] == "tool_error_unexpected_output"
    assert body["root_span_id"] == "culprit-span-id"


async def test_fail_span_without_explicit_span_id_uses_fail_span_itself(client):
    fail_span = _fail_span(run_id="run-fail-3", span_id="fail-span-only")
    await client.post(
        "/v1/spans",
        json={"project_id": TEST_PROJECT_ID, "spans": [fail_span]},
        headers=auth_headers(),
    )

    resp = await client.get("/v1/runs/run-fail-3", headers=auth_headers())
    body = resp.json()
    assert body["root_span_id"] == "fail-span-only"


async def test_status_escalation_is_one_way(client):
    """Once a run is `failure`, a later normal batch can never flip it back to `ok`."""
    base = datetime.now(timezone.utc)
    fail_batch = [_fail_span(run_id="run-sticky", started_at=base)]
    ok_batch = [_span(run_id="run-sticky", started_at=base + timedelta(seconds=5))]

    await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": fail_batch}, headers=auth_headers()
    )
    await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": ok_batch}, headers=auth_headers()
    )

    resp = await client.get("/v1/runs/run-sticky", headers=auth_headers())
    body = resp.json()
    assert body["status"] == "failure"
    assert len(body["spans"]) == 2


async def test_normal_batch_leaves_run_status_ok(client):
    spans = [_span(run_id="run-healthy")]
    await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": spans}, headers=auth_headers()
    )

    resp = await client.get("/v1/runs/run-healthy", headers=auth_headers())
    body = resp.json()
    assert body["status"] == "ok"
    assert body["failure_class"] is None
    assert body["root_span_id"] is None


async def test_only_checkpoint_type_with_exact_name_triggers_failure(client):
    """A span merely *named* "agentreplay.fail" but of a different type must not trigger."""
    decoy = _span(run_id="run-decoy", type_="tool", name="agentreplay.fail")
    await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": [decoy]}, headers=auth_headers()
    )

    resp = await client.get("/v1/runs/run-decoy", headers=auth_headers())
    assert resp.json()["status"] == "ok"


async def test_latest_fail_span_in_batch_wins_for_failure_class(client):
    base = datetime.now(timezone.utc)
    spans = [
        _fail_span(run_id="run-multi-fail", started_at=base, failure_class="first_class"),
        _fail_span(
            run_id="run-multi-fail",
            started_at=base + timedelta(seconds=1),
            failure_class="second_class",
        ),
    ]
    await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": spans}, headers=auth_headers()
    )

    resp = await client.get("/v1/runs/run-multi-fail", headers=auth_headers())
    assert resp.json()["failure_class"] == "second_class"


async def test_fail_span_across_two_batches_still_marks_failure(client):
    base = datetime.now(timezone.utc)
    ok_first = [_span(run_id="run-late-fail", started_at=base)]
    fail_second = [_fail_span(run_id="run-late-fail", started_at=base + timedelta(seconds=5))]

    await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": ok_first}, headers=auth_headers()
    )
    await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": fail_second}, headers=auth_headers()
    )

    resp = await client.get("/v1/runs/run-late-fail", headers=auth_headers())
    body = resp.json()
    assert body["status"] == "failure"
    assert len(body["spans"]) == 2


async def test_fail_span_with_error_payload_round_trips(client):
    fail_span = _fail_span(
        run_id="run-fail-error",
        error={"type": "ValueError", "message": "boom"},
    )
    await client.post(
        "/v1/spans", json={"project_id": TEST_PROJECT_ID, "spans": [fail_span]}, headers=auth_headers()
    )

    resp = await client.get("/v1/runs/run-fail-error", headers=auth_headers())
    body = resp.json()
    fail_span_out = next(s for s in body["spans"] if s["name"] == "agentreplay.fail")
    assert fail_span_out["error"] == {"type": "ValueError", "message": "boom"}
