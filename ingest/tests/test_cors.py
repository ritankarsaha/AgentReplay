from __future__ import annotations

from .conftest import auth_headers

ALLOWED_ORIGIN = "http://localhost:3000"


async def test_cors_preflight_allows_configured_origin(client):
    resp = await client.options(
        "/v1/runs",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


async def test_cors_actual_request_echoes_allowed_origin(client):
    resp = await client.get(
        "/v1/runs", headers={**auth_headers(), "Origin": ALLOWED_ORIGIN}
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


async def test_cors_rejects_unconfigured_origin(client):
    resp = await client.get(
        "/v1/runs", headers={**auth_headers(), "Origin": "http://evil.example.com"}
    )
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers
