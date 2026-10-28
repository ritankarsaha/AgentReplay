from __future__ import annotations

import httpx

from agentreplay.cli import main
from agentreplay.doctor import run_doctor


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _happy(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/healthz":
        return httpx.Response(200, json={"status": "ok"})
    if request.url.path == "/v1/runs":
        return httpx.Response(200, json={"runs": []})
    if request.url.path == "/v1/spans":
        assert request.headers["authorization"] == "Bearer ar_testkey_12345"
        return httpx.Response(202, json={"accepted": 1})
    return httpx.Response(404)


def test_doctor_all_green():
    checks = run_doctor(endpoint="http://x", api_key="ar_testkey_12345", client=_client(_happy))
    assert [c.ok for c in checks] == [True, True, True, True]


def test_doctor_without_key(monkeypatch):
    monkeypatch.delenv("AGENTREPLAY_API_KEY", raising=False)
    checks = run_doctor(endpoint="http://x")
    assert len(checks) == 1 and not checks[0].ok


def test_doctor_rejected_key_stops_before_sending():
    def handler(request):
        if request.url.path == "/healthz":
            return httpx.Response(200)
        return httpx.Response(401)

    checks = run_doctor(endpoint="http://x", api_key="ar_bad_key_12345", client=_client(handler))
    assert [c.name for c in checks][-1] == "API key accepted"
    assert not checks[-1].ok


def test_doctor_unreachable_endpoint():
    def handler(request):
        raise httpx.ConnectError("boom")

    checks = run_doctor(endpoint="http://x", api_key="ar_testkey_12345", client=_client(handler))
    assert not checks[-1].ok and "boom" in checks[-1].detail


def test_cli_doctor_exit_code(monkeypatch, capsys):
    monkeypatch.delenv("AGENTREPLAY_API_KEY", raising=False)
    assert main(["doctor"]) == 1
    assert "AGENTREPLAY_API_KEY" in capsys.readouterr().out
