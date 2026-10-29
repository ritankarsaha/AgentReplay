from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone

from .conftest import OTHER_API_KEY, auth_headers

PUBLIC_KEY = "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg"
AGENT_ID = "agt_56475aa75463474c"
MANIFEST = {
    "agent_id": AGENT_ID,
    "version": 1,
    "allowed_tools": ["book_flight", "search_flights"],
    "constraints": {"max_spend_inr": 6000, "max_bookings_per_task": 1, "geography": "domestic"},
    "issued_at": "2026-11-01T00:00:00Z",
    "expires_at": "2036-10-29T00:00:00Z",
    "signature": "rzVL3tI4gmRl_Tq9XKGmv59TzL1_WF6VAgHbRvI9z3kUkgx2Dnha4TqD_wosQBmjy2w6W-Q2EfVaWfDBoTanDw",
}


async def _register(client, headers=None):
    return await client.post(
        "/v1/agents", json={"name": "flight-bot", "public_key": PUBLIC_KEY}, headers=headers or auth_headers()
    )


def _span(run_id, type_, name, *, input_=None, output=None, span_id=None):
    return {
        "id": span_id or str(uuid.uuid4()),
        "run_id": run_id,
        "parent_id": None,
        "type": type_,
        "name": name,
        "input": input_ or {},
        "output": output,
        "error": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": 1.0,
        "fingerprint": "fp",
    }


async def test_register_agent_derives_id_and_is_idempotent(client):
    first = await _register(client)
    assert first.status_code == 201 and first.json()["id"] == AGENT_ID
    again = await _register(client)
    assert again.status_code == 201 and again.json()["id"] == AGENT_ID
    assert len((await client.get("/v1/agents", headers=auth_headers())).json()) == 1


async def test_register_rejects_bad_key_and_cross_tenant_reuse(client):
    bad = await client.post("/v1/agents", json={"name": "x", "public_key": "AAAA"}, headers=auth_headers())
    assert bad.status_code == 422
    await _register(client)
    assert (await _register(client, auth_headers(OTHER_API_KEY))).status_code == 409


async def test_agents_are_tenant_scoped(client):
    await _register(client)
    other = auth_headers(OTHER_API_KEY)
    assert (await client.get("/v1/agents", headers=other)).json() == []
    assert (await client.get(f"/v1/agents/{AGENT_ID}", headers=other)).status_code == 404
    assert (await client.get("/v1/agents")).status_code == 401


async def test_manifest_publish_verify_current_and_revoke(client):
    await _register(client)
    h = auth_headers()
    ok = await client.post(f"/v1/agents/{AGENT_ID}/manifests", json={"manifest": MANIFEST}, headers=h)
    assert ok.status_code == 201 and ok.json()["version"] == 1

    cur = await client.get(f"/v1/agents/{AGENT_ID}/manifest", headers=h)
    assert cur.json()["manifest"]["signature"] == MANIFEST["signature"]

    dup = await client.post(f"/v1/agents/{AGENT_ID}/manifests", json={"manifest": MANIFEST}, headers=h)
    assert dup.status_code == 409

    assert (await client.get(f"/v1/agents/{AGENT_ID}/manifests/1", headers=h)).json()["revoked_at"] is None
    revoked = await client.post(f"/v1/agents/{AGENT_ID}/manifests/1/revoke", headers=h)
    assert revoked.json()["revoked_at"] is not None
    assert (await client.get(f"/v1/agents/{AGENT_ID}/manifest", headers=h)).status_code == 404
    assert (await client.get(f"/v1/agents/{AGENT_ID}/manifests/1", headers=h)).json()["revoked_at"] is not None


async def test_tampered_or_mismatched_manifest_rejected(client):
    await _register(client)
    h = auth_headers()
    tampered = copy.deepcopy(MANIFEST)
    tampered["constraints"]["max_spend_inr"] = 600000
    r = await client.post(f"/v1/agents/{AGENT_ID}/manifests", json={"manifest": tampered}, headers=h)
    assert r.status_code == 422
    wrong_agent = {**MANIFEST, "agent_id": "agt_other"}
    r = await client.post(f"/v1/agents/{AGENT_ID}/manifests", json={"manifest": wrong_agent}, headers=h)
    assert r.status_code == 422
    unsigned = {k: v for k, v in MANIFEST.items() if k != "signature"}
    r = await client.post(f"/v1/agents/{AGENT_ID}/manifests", json={"manifest": unsigned}, headers=h)
    assert r.status_code == 422


async def test_halt_alert_marks_run_halted_and_opens_incident(client):
    await _register(client)
    h = auth_headers()
    violation_id = str(uuid.uuid4())
    alert_id = str(uuid.uuid4())
    batch = [
        _span("run-h", "policy", "wire_money", output={"decision": "deny"}),
        _span("run-h", "scope_violation", "wire_money", span_id=violation_id),
        _span(
            "run-h",
            "alert",
            "agentreplay.halt",
            span_id=alert_id,
            input_={"kind": "scope_violation", "severity": "high", "agent_id": AGENT_ID, "culprit_span_id": violation_id},
        ),
    ]
    assert (await client.post("/v1/spans", json={"spans": batch}, headers=h)).status_code == 202

    run = (await client.get("/v1/runs/run-h", headers=h)).json()
    assert run["status"] == "halted"
    incidents = (await client.get("/v1/incidents", headers=h)).json()
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident["id"] == alert_id and incident["run_id"] == "run-h"
    assert incident["agent_id"] == AGENT_ID and incident["culprit_span_id"] == violation_id
    assert incident["kind"] == "scope_violation" and incident["status"] == "open"

    await client.post("/v1/spans", json={"spans": batch}, headers=h)
    assert len((await client.get("/v1/incidents", headers=h)).json()) == 1

    late = [_span("run-h", "tool", "x")]
    await client.post("/v1/spans", json={"spans": late}, headers=h)
    assert (await client.get("/v1/runs/run-h", headers=h)).json()["status"] == "halted"

    resolved = await client.post(f"/v1/incidents/{alert_id}/resolve", headers=h)
    assert resolved.json()["status"] == "resolved"
    assert (await client.get("/v1/incidents?status=open", headers=h)).json() == []


async def test_spend_gate_alert_maps_to_spend_breach_and_unknown_agent_is_nullable(client):
    h = auth_headers()
    batch = [
        _span(
            "run-s",
            "alert",
            "agentreplay.halt",
            input_={"kind": "spend_gate", "agent_id": "agt_unregistered", "culprit_span_id": "c"},
        )
    ]
    await client.post("/v1/spans", json={"spans": batch}, headers=h)
    incident = (await client.get("/v1/incidents", headers=h)).json()[0]
    assert incident["kind"] == "spend_breach" and incident["agent_id"] is None


async def test_incidents_are_tenant_scoped(client):
    h = auth_headers()
    await client.post(
        "/v1/spans",
        json={"spans": [_span("run-t", "alert", "agentreplay.halt", input_={"kind": "scope_violation"})]},
        headers=h,
    )
    other = auth_headers(OTHER_API_KEY)
    assert (await client.get("/v1/incidents", headers=other)).json() == []
    incident_id = (await client.get("/v1/incidents", headers=h)).json()[0]["id"]
    assert (await client.get(f"/v1/incidents/{incident_id}", headers=other)).status_code == 404
    assert (await client.post(f"/v1/incidents/{incident_id}/resolve", headers=other)).status_code == 404


async def test_trust_record_latest_history_and_validation(client):
    await _register(client)
    h = auth_headers()
    assert (await client.get(f"/v1/agents/{AGENT_ID}/trust", headers=h)).status_code == 404
    for score, band in ((640, "standard"), (571, "probation")):
        r = await client.post(
            f"/v1/agents/{AGENT_ID}/trust", json={"score": score, "band": band, "components": {"c": 1}}, headers=h
        )
        assert r.status_code == 201
    assert (await client.get(f"/v1/agents/{AGENT_ID}/trust", headers=h)).json()["score"] == 571
    assert len((await client.get(f"/v1/agents/{AGENT_ID}/trust/history", headers=h)).json()) == 2
    bad = await client.post(f"/v1/agents/{AGENT_ID}/trust", json={"score": 900, "band": "x"}, headers=h)
    assert bad.status_code == 422


async def test_trust_inputs_reflect_runs_and_violations(client):
    await _register(client)
    h = auth_headers()
    empty = (await client.get(f"/v1/agents/{AGENT_ID}/trust-inputs", headers=h)).json()
    assert empty["runs_count"] == 0 and empty["violation_times"] == []

    allow = {"decision": "allow", "details": {"agent_id": AGENT_ID}}
    await client.post("/v1/spans", json={"spans": [_span("ok-run", "policy", "search_flights", output=allow)]}, headers=h)
    await client.post(
        "/v1/spans",
        json={
            "spans": [
                _span("bad-run", "policy", "wire_money", output={"decision": "deny", "details": {"agent_id": AGENT_ID}}),
                _span("bad-run", "alert", "agentreplay.halt", input_={"kind": "scope_violation", "agent_id": AGENT_ID}),
            ]
        },
        headers=h,
    )
    inputs = (await client.get(f"/v1/agents/{AGENT_ID}/trust-inputs", headers=h)).json()
    assert inputs["runs_count"] == 2
    assert inputs["recent_failure_rate"] == 0.5
    assert len(inputs["violation_times"]) == 1
    assert inputs["regression_pass_rate"] == 1.0


async def test_token_lifecycle_and_tenancy(client):
    await _register(client)
    h = auth_headers()
    token_id = "a" * 64
    body = {"id": token_id, "connector": "airline", "scopes": ["search", "book", "search"]}
    created = await client.post(f"/v1/agents/{AGENT_ID}/tokens", json=body, headers=h)
    assert created.status_code == 201 and created.json()["scopes"] == ["book", "search"]
    assert (await client.post(f"/v1/agents/{AGENT_ID}/tokens", json=body, headers=h)).status_code == 409

    other = auth_headers(OTHER_API_KEY)
    assert (await client.get(f"/v1/tokens/{token_id}", headers=other)).status_code == 404
    assert (await client.post(f"/v1/tokens/{token_id}/revoke", headers=other)).status_code == 404

    assert (await client.get(f"/v1/tokens/{token_id}", headers=h)).json()["revoked_at"] is None
    revoked = await client.post(f"/v1/tokens/{token_id}/revoke", headers=h)
    assert revoked.json()["revoked_at"] is not None
    assert (await client.get(f"/v1/tokens/{token_id}", headers=h)).json()["revoked_at"] is not None


async def _halted_incident(client, run_id="run-i"):
    h = auth_headers()
    await client.post(
        "/v1/spans",
        json={"spans": [_span(run_id, "alert", "agentreplay.halt", input_={"kind": "scope_violation"})]},
        headers=h,
    )
    return (await client.get("/v1/incidents", headers=h)).json()[0]["id"]


async def test_incident_details_merge_is_shallow_and_tenant_scoped(client):
    incident_id = await _halted_incident(client)
    h = auth_headers()
    assert (await client.get(f"/v1/incidents/{incident_id}", headers=h)).json()["details"] == {}
    await client.post(f"/v1/incidents/{incident_id}/details", json={"details": {"causation": ["a"], "x": 1}}, headers=h)
    merged = await client.post(f"/v1/incidents/{incident_id}/details", json={"details": {"x": 2}}, headers=h)
    assert merged.json()["details"] == {"causation": ["a"], "x": 2}
    other = auth_headers(OTHER_API_KEY)
    assert (await client.post(f"/v1/incidents/{incident_id}/details", json={"details": {}}, headers=other)).status_code == 404


async def test_filings_are_replaced_per_type_and_validated(client):
    incident_id = await _halted_incident(client)
    h = auth_headers()
    body = {"type": "dispute", "packet": {"v": 1}, "trace_hash": "a" * 64}
    assert (await client.post(f"/v1/incidents/{incident_id}/filings", json=body, headers=h)).status_code == 201
    await client.post(f"/v1/incidents/{incident_id}/filings", json={**body, "packet": {"v": 2}}, headers=h)
    await client.post(f"/v1/incidents/{incident_id}/filings", json={**body, "type": "claim"}, headers=h)
    filings = (await client.get(f"/v1/incidents/{incident_id}/filings", headers=h)).json()
    assert [(f["type"], f["packet"]) for f in filings] == [("claim", {"v": 1}), ("dispute", {"v": 2})]
    assert all(f["simulated"] for f in filings)
    bad = await client.post(f"/v1/incidents/{incident_id}/filings", json={**body, "type": "refund"}, headers=h)
    assert bad.status_code == 422
    other = auth_headers(OTHER_API_KEY)
    assert (await client.get(f"/v1/incidents/{incident_id}/filings", headers=other)).status_code == 404


async def test_model_runs_roundtrip_and_source_run_must_belong_to_project(client):
    h = auth_headers()
    await client.post("/v1/spans", json={"spans": [_span("run-m", "tool", "x")]}, headers=h)
    runs = [
        {"source_run_id": "run-m", "span_id": "s1", "model": "muse-spark-1.3", "output": {"flight": "6E-871"}, "verdict": "repeats_mistake", "cost_usd": 0.01},
        {"source_run_id": "run-m", "span_id": "s1", "model": "muse-spark-1.1", "verdict": "ok"},
    ]
    created = await client.post("/v1/model-runs", json={"runs": runs}, headers=h)
    assert created.status_code == 201 and len(created.json()) == 2
    listed = (await client.get("/v1/model-runs?source_run_id=run-m", headers=h)).json()
    assert {r["model"] for r in listed} == {"muse-spark-1.3", "muse-spark-1.1"}

    other = auth_headers(OTHER_API_KEY)
    assert (await client.post("/v1/model-runs", json={"runs": runs}, headers=other)).status_code == 404
    assert (await client.get("/v1/model-runs", headers=other)).json() == []


async def test_classify_incident_run(client, monkeypatch):
    incident_id = await _halted_incident(client, "run-c")
    h = auth_headers()

    from app.routers import govern

    async def fake_classify(run_id, session, settings):
        run = await govern.crud.get_run_with_spans_by_id(session, run_id=run_id)
        run.failure_class = "disobey_task_specification"
        run.classification_status = "done"
        run.diagnosis = {"text": "wrong flight"}
        await session.commit()

    monkeypatch.setattr(govern, "classify_run_async", fake_classify)
    unconfigured = await client.post(f"/v1/incidents/{incident_id}/classify", headers=h)
    assert unconfigured.status_code == 503

    monkeypatch.setenv("AGENTREPLAY_INGEST_CLASSIFIER_BACKEND", "meta")
    monkeypatch.setenv("AGENTREPLAY_INGEST_META_API_KEY", "k")
    done = await client.post(f"/v1/incidents/{incident_id}/classify", headers=h)
    assert done.status_code == 200
    assert done.json()["failure_class"] == "disobey_task_specification"
    assert done.json()["classification_status"] == "done"
    assert (await client.post(f"/v1/incidents/{incident_id}/classify", headers=auth_headers(OTHER_API_KEY))).status_code == 404


async def test_incidents_can_be_filtered_by_run(client):
    await _halted_incident(client, "run-a")
    await _halted_incident(client, "run-b")
    h = auth_headers()
    assert len((await client.get("/v1/incidents", headers=h)).json()) == 2
    only = (await client.get("/v1/incidents?run_id=run-b", headers=h)).json()
    assert [i["run_id"] for i in only] == ["run-b"]
    assert (await client.get("/v1/incidents?run_id=nope", headers=h)).json() == []
