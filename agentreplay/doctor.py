"""`agentreplay doctor` -- verify an install end to end in one command.

Checks the three things that break first-run setups: no/placeholder API key,
an unreachable or wrong endpoint, and a rejected key. Then sends one real
test span so the user sees a run appear in the dashboard (the north-star
"pip install -> first trace" moment).
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import httpx

from .config import DEFAULT_ENDPOINT
from .fingerprint import compute_fingerprint


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def run_doctor(
    *,
    endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: float = 10.0,
    client: Optional[httpx.Client] = None,
) -> List[Check]:
    endpoint = (endpoint or os.environ.get("AGENTREPLAY_ENDPOINT") or DEFAULT_ENDPOINT).rstrip("/")
    api_key = api_key or os.environ.get("AGENTREPLAY_API_KEY")
    checks: List[Check] = []

    if not api_key:
        checks.append(Check("API key", False, "AGENTREPLAY_API_KEY is not set (create one in the dashboard)"))
        return checks
    shown = f"{api_key[:7]}..." if len(api_key) > 10 else "(short)"
    checks.append(Check("API key", True, f"found {shown}"))

    http = client or httpx.Client(timeout=timeout)
    try:
        try:
            health = http.get(f"{endpoint}/healthz")
        except httpx.HTTPError as exc:
            checks.append(Check("Endpoint reachable", False, f"{endpoint}: {exc}"))
            return checks
        if health.status_code != 200:
            checks.append(Check("Endpoint reachable", False, f"{endpoint}/healthz -> {health.status_code}"))
            return checks
        checks.append(Check("Endpoint reachable", True, endpoint))

        headers = {"Authorization": f"Bearer {api_key}"}
        auth = http.get(f"{endpoint}/v1/runs", params={"limit": 1}, headers=headers)
        if auth.status_code == 401:
            checks.append(Check("API key accepted", False, "the server rejected this key (rotated or mistyped?)"))
            return checks
        if auth.status_code != 200:
            checks.append(Check("API key accepted", False, f"/v1/runs -> {auth.status_code}: {auth.text[:120]}"))
            return checks
        checks.append(Check("API key accepted", True, "authenticated"))

        run_id = f"doctor-{uuid.uuid4()}"
        now = datetime.now(timezone.utc).isoformat()
        span = {
            "id": str(uuid.uuid4()),
            "run_id": run_id,
            "parent_id": None,
            "type": "checkpoint",
            "name": "agentreplay.doctor",
            "input": {"note": "connectivity check from `agentreplay doctor`"},
            "output": {"ok": True},
            "error": None,
            "started_at": now,
            "duration_ms": 0.0,
            "fingerprint": compute_fingerprint({"doctor": run_id}),
        }
        sent = http.post(f"{endpoint}/v1/spans", json={"spans": [span]}, headers=headers)
        if sent.status_code != 202:
            checks.append(Check("Test span ingested", False, f"/v1/spans -> {sent.status_code}: {sent.text[:120]}"))
            return checks
        checks.append(Check("Test span ingested", True, f"run {run_id} should now be in your dashboard"))
    finally:
        if client is None:
            http.close()
    return checks
