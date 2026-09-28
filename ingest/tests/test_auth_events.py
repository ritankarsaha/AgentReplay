from __future__ import annotations

import asyncio

from .conftest import OTHER_API_KEY, auth_headers


def _login_body(**overrides) -> dict:
    defaults = dict(
        email="founder@example.com",
        name="Ritankar Saha",
        image="https://lh3.googleusercontent.com/a/abc123",
        provider="google",
    )
    defaults.update(overrides)
    return defaults


async def test_create_login_event(client):
    resp = await client.post("/v1/auth-events", json=_login_body(), headers=auth_headers())
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "founder@example.com"
    assert body["name"] == "Ritankar Saha"
    assert body["provider"] == "google"
    assert body["project_id"] == "test-project"
    assert body["id"]
    assert body["created_at"]


async def test_create_login_event_optional_fields(client):
    resp = await client.post(
        "/v1/auth-events",
        json=_login_body(name=None, image=None),
        headers=auth_headers(),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] is None
    assert body["image"] is None


async def test_create_login_event_requires_auth(client):
    resp = await client.post("/v1/auth-events", json=_login_body())
    assert resp.status_code == 401


async def test_create_login_event_missing_email(client):
    body = _login_body()
    del body["email"]
    resp = await client.post("/v1/auth-events", json=body, headers=auth_headers())
    assert resp.status_code == 422


async def test_list_login_events_empty(client):
    resp = await client.get("/v1/auth-events", headers=auth_headers())
    assert resp.status_code == 200
    assert resp.json() == {"events": []}


async def test_list_login_events_newest_first(client):
    # `created_at` is server-set (func.now()) with no client override, by
    # design (an audit log shouldn't trust a client-supplied timestamp).
    # SQLite's CURRENT_TIMESTAMP is second-resolution, so a real (short)
    # delay is needed here to get two distinct timestamps to order by --
    # Postgres's `now()` is microsecond-resolution, so this is a test-double
    # artifact, not a production concern.
    await client.post(
        "/v1/auth-events", json=_login_body(email="first@example.com"), headers=auth_headers()
    )
    await asyncio.sleep(1.1)
    await client.post(
        "/v1/auth-events", json=_login_body(email="second@example.com"), headers=auth_headers()
    )

    resp = await client.get("/v1/auth-events", headers=auth_headers())
    assert resp.status_code == 200
    emails = [e["email"] for e in resp.json()["events"]]
    assert emails == ["second@example.com", "first@example.com"]


async def test_list_login_events_scoped_to_project(client):
    await client.post("/v1/auth-events", json=_login_body(), headers=auth_headers())

    resp = await client.get("/v1/auth-events", headers=auth_headers(OTHER_API_KEY))
    assert resp.status_code == 200
    assert resp.json() == {"events": []}


async def test_list_login_events_requires_auth(client):
    resp = await client.get("/v1/auth-events")
    assert resp.status_code == 401


async def test_list_login_events_respects_limit(client):
    for i in range(3):
        await client.post(
            "/v1/auth-events", json=_login_body(email=f"user{i}@example.com"), headers=auth_headers()
        )

    resp = await client.get("/v1/auth-events?limit=2", headers=auth_headers())
    assert resp.status_code == 200
    assert len(resp.json()["events"]) == 2
