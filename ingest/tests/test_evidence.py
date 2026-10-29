from __future__ import annotations

import hashlib

from .conftest import OTHER_API_KEY, VIEWER_TOKEN, auth_headers
from .test_govern import _halted_incident

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64


def service_headers():
    return {"Authorization": f"Bearer {VIEWER_TOKEN}"}


async def test_blob_roundtrip_is_content_addressed_and_tenant_scoped(client):
    h = auth_headers()
    created = await client.post("/v1/blobs", content=PNG, headers={**h, "Content-Type": "image/png"})
    assert created.status_code == 201
    digest = hashlib.sha256(PNG).hexdigest()
    assert created.json() == {"sha256": digest, "mime": "image/png", "size": len(PNG), "uri": f"blob://sha256/{digest}"}
    again = await client.post("/v1/blobs", content=PNG, headers={**h, "Content-Type": "image/png"})
    assert again.status_code == 201 and again.json()["sha256"] == digest

    fetched = await client.get(f"/v1/blobs/{digest}", headers=h)
    assert fetched.content == PNG and fetched.headers["content-type"] == "image/png"
    assert fetched.headers["x-content-type-options"] == "nosniff"
    assert (await client.get(f"/v1/blobs/{digest}", headers=auth_headers(OTHER_API_KEY))).status_code == 404
    assert (await client.get(f"/v1/blobs/{digest}")).status_code == 401


async def test_blob_validation(client):
    h = auth_headers()
    assert (await client.post("/v1/blobs", content=b"x", headers={**h, "Content-Type": "application/x-sh"})).status_code == 415
    assert (await client.post("/v1/blobs", content=b"", headers={**h, "Content-Type": "image/png"})).status_code == 400
    too_big = b"x" * 2_000_001
    assert (await client.post("/v1/blobs", content=too_big, headers={**h, "Content-Type": "image/png"})).status_code == 413


async def test_html_blobs_are_served_sandboxed(client):
    h = auth_headers()
    created = await client.post("/v1/blobs", content=b"<script>1</script>", headers={**h, "Content-Type": "text/html"})
    fetched = await client.get(f"/v1/blobs/{created.json()['sha256']}", headers=h)
    assert "sandbox" in fetched.headers["content-security-policy"]


async def test_share_link_lifecycle_and_public_bundle(client):
    incident_id = await _halted_incident(client)
    h = auth_headers()
    await client.post(f"/v1/incidents/{incident_id}/filings", json={"type": "dispute", "packet": {"narrative": "n"}, "trace_hash": "a" * 64}, headers=h)
    png = await client.post("/v1/blobs", content=PNG, headers={**h, "Content-Type": "image/png"})
    digest = png.json()["sha256"]
    await client.post(f"/v1/incidents/{incident_id}/details", json={"details": {"walkthrough": {"beats": []}, "assets": [digest]}}, headers=h)

    assert (await client.get("/v1/public/incidents/nope", headers=service_headers())).status_code == 404
    token = (await client.post(f"/v1/incidents/{incident_id}/share", headers=h)).json()["share_token"]
    assert token and (await client.post(f"/v1/incidents/{incident_id}/share", headers=h)).json()["share_token"] == token
    assert (await client.get(f"/v1/incidents/{incident_id}", headers=h)).json()["share_token"] == token

    bundle = (await client.get(f"/v1/public/incidents/{token}", headers=service_headers())).json()
    assert bundle["incident"]["id"] == incident_id and bundle["incident"]["details"]["walkthrough"] == {"beats": []}
    assert [f["type"] for f in bundle["filings"]] == ["dispute"] and bundle["filings"][0]["simulated"] is True
    assert bundle["run"]["id"] == "run-i" and "spans" not in bundle["run"]
    assert "project_id" not in bundle["incident"] and bundle["case"] is None

    blob = await client.get(f"/v1/public/incidents/{token}/blobs/{digest}", headers=service_headers())
    assert blob.content == PNG
    assert (await client.get(f"/v1/public/incidents/{token}/blobs/{'0' * 64}", headers=service_headers())).status_code == 404

    assert (await client.delete(f"/v1/incidents/{incident_id}/share", headers=h)).json() == {"share_token": None}
    assert (await client.get(f"/v1/public/incidents/{token}", headers=service_headers())).status_code == 404


async def test_public_endpoints_need_the_viewer_service_token_and_blobs_must_be_listed(client):
    incident_id = await _halted_incident(client)
    h = auth_headers()
    token = (await client.post(f"/v1/incidents/{incident_id}/share", headers=h)).json()["share_token"]
    assert (await client.get(f"/v1/public/incidents/{token}")).status_code == 401
    assert (await client.get(f"/v1/public/incidents/{token}", headers=h)).status_code == 401

    png = await client.post("/v1/blobs", content=PNG, headers={**h, "Content-Type": "image/png"})
    unlisted = await client.get(f"/v1/public/incidents/{token}/blobs/{png.json()['sha256']}", headers=service_headers())
    assert unlisted.status_code == 404

    other = auth_headers(OTHER_API_KEY)
    assert (await client.post(f"/v1/incidents/{incident_id}/share", headers=other)).status_code == 404
    assert (await client.delete(f"/v1/incidents/{incident_id}/share", headers=other)).status_code == 404


async def test_regression_case_generated_test_and_incident_filter(client):
    h = auth_headers()
    body = {
        "entrypoint": "pkg.mod:run",
        "recorded_input": "Book BLR to CCU",
        "tool_spans": [],
        "assertion_spec": {"no_exception": True, "output_checks": [{"path": "n", "op": "lte", "value": 1}]},
        "title": "t",
        "incident_id": "inc-1",
    }
    case = (await client.post("/v1/regression-cases/capture-production", json=body, headers=h)).json()
    generated = (await client.get(f"/v1/regression-cases/{case['id']}/generated-test", headers=h)).json()
    assert "Book BLR to CCU" in generated["fixture_source"] and "OUTPUT_CHECKS" in generated["test_source"]
    assert "pkg.mod:run" in generated["test_source"] and generated["test_filename"].startswith("test_")
    compile(generated["test_source"], "t.py", "exec")

    assert len((await client.get("/v1/regression-cases?incident_id=inc-1", headers=h)).json()["cases"]) == 1
    assert (await client.get("/v1/regression-cases?incident_id=other", headers=h)).json()["cases"] == []
    assert (await client.get(f"/v1/regression-cases/{case['id']}/generated-test", headers=auth_headers(OTHER_API_KEY))).status_code == 404


async def test_list_manifests_and_tokens(client):
    from .test_govern import AGENT_ID, MANIFEST, _register

    await _register(client)
    h = auth_headers()
    assert (await client.get(f"/v1/agents/{AGENT_ID}/manifests", headers=h)).json() == []
    await client.post(f"/v1/agents/{AGENT_ID}/manifests", json={"manifest": MANIFEST}, headers=h)
    assert [m["version"] for m in (await client.get(f"/v1/agents/{AGENT_ID}/manifests", headers=h)).json()] == [1]
    await client.post(f"/v1/agents/{AGENT_ID}/tokens", json={"id": "b" * 64, "connector": "card", "scopes": ["charge"]}, headers=h)
    tokens = (await client.get(f"/v1/agents/{AGENT_ID}/tokens", headers=h)).json()
    assert [(t["connector"], t["scopes"]) for t in tokens] == [("card", ["charge"])]
    other = auth_headers(OTHER_API_KEY)
    assert (await client.get(f"/v1/agents/{AGENT_ID}/manifests", headers=other)).status_code == 404
    assert (await client.get(f"/v1/agents/{AGENT_ID}/tokens", headers=other)).status_code == 404
