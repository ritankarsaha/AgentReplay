from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from controlplane.client import ControlPlaneClient, ControlPlaneError, HttpTokenStore, recompute_trust, trust_refresher
from controlplane.govern import ScopeGuard, generate_keypair, sign_manifest
from controlplane.govern.broker import Broker, token_id_for

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def make_client(handler):
    http = httpx.Client(base_url="http://ingest.test", transport=httpx.MockTransport(handler))
    return ControlPlaneClient("key", http=http)


def test_recompute_trust_reads_inputs_and_posts_result():
    posted = []

    def handler(request):
        if request.url.path.endswith("/trust-inputs"):
            return httpx.Response(
                200,
                json={
                    "runs_count": 30,
                    "recent_failure_rate": 0.2,
                    "regression_pass_rate": 0.8,
                    "violation_times": [NOW.isoformat()],
                },
            )
        posted.append(json.loads(request.content))
        return httpx.Response(201, json={})

    result = recompute_trust(make_client(handler), "agt_1", trigger_run_id="run-9", now=NOW)
    assert posted[0]["score"] == result.score
    assert posted[0]["trigger_run_id"] == "run-9"
    assert posted[0]["components"]["cap_inr"] == result.cap_inr
    assert result.components["scope_violation_penalty"] == 0.5


def test_revocation_check_caches_and_keeps_last_known_on_error():
    calls = {"n": 0, "revoked": None, "fail": False}

    def handler(request):
        calls["n"] += 1
        if calls["fail"]:
            raise httpx.ConnectError("down")
        return httpx.Response(200, json={"revoked_at": calls["revoked"]})

    check = make_client(handler).revocation_check("agt_1", 1, ttl_s=3600)
    assert check() is False and check() is False
    assert calls["n"] == 1

    fresh = make_client(handler).revocation_check("agt_1", 1, ttl_s=0)
    assert fresh() is False
    calls["revoked"] = NOW.isoformat()
    assert fresh() is True
    calls["fail"] = True
    assert fresh() is True


def test_client_raises_on_error_status_and_returns_none_on_ok_404():
    client = make_client(lambda request: httpx.Response(500, text="boom"))
    with pytest.raises(ControlPlaneError):
        client.list_incidents()
    client = make_client(lambda request: httpx.Response(404))
    assert client.current_manifest("agt_1") is None
    assert client.latest_trust("agt_1") is None


def test_trust_refresher_lowers_guard_cap():
    kp = generate_keypair()
    manifest = sign_manifest(kp, allowed_tools=["t"], constraints={"max_spend_inr": 6000})
    guard = ScopeGuard(manifest, kp.public_key)

    def handler(request):
        if request.url.path.endswith("/trust-inputs"):
            return httpx.Response(
                200,
                json={"runs_count": 0, "recent_failure_rate": 1.0, "regression_pass_rate": 0.0, "violation_times": []},
            )
        return httpx.Response(201, json={})

    refresh = trust_refresher(make_client(handler), guard, lambda: "run-1")
    refresh({"agent_id": None})
    assert guard.effective_cap_inr() == 6000
    refresh({"agent_id": kp.agent_id})
    assert guard.effective_cap_inr() == 0


def test_http_token_store_roundtrip_through_broker():
    rows = {}

    def handler(request):
        path = request.url.path
        if request.method == "POST" and path.endswith("/tokens"):
            body = json.loads(request.content)
            rows[body["id"]] = {
                **body,
                "agent_id": "agt_1",
                "issued_at": NOW.isoformat(),
                "revoked_at": None,
            }
            return httpx.Response(201, json=rows[body["id"]])
        token_id = path.split("/")[3]
        row = rows.get(token_id)
        if row is None:
            return httpx.Response(404)
        if path.endswith("/revoke"):
            row["revoked_at"] = NOW.isoformat()
        return httpx.Response(200, json=row)

    broker = Broker(HttpTokenStore(make_client(handler)), clock=lambda: NOW)
    issued = broker.issue("agt_1", "airline", ["search"], ttl=timedelta(hours=1))
    assert token_id_for(issued.token) in rows
    assert issued.token not in json.dumps(rows)
    broker.authorize(issued.token, "airline", "search")
    assert broker.revoke(issued.token) is True
    with pytest.raises(Exception, match="token_revoked"):
        broker.authorize(issued.token, "airline", "search")
    assert broker.revoke("atk_missing") is False
