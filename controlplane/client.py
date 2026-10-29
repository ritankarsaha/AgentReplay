"""HTTP client for the control-plane endpoints of the ingest API."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional

import httpx

from .govern.broker import TokenRecord
from .govern.identity import ScopeManifest
from .govern.trust import TrustResult, compute_trust

DEFAULT_ENDPOINT = "https://agentreplay-ingest.fly.dev"
REVOCATION_TTL_S = 5.0


class ControlPlaneError(Exception):
    pass


def _ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class ControlPlaneClient:
    def __init__(
        self,
        api_key: str,
        endpoint: str = DEFAULT_ENDPOINT,
        *,
        timeout: float = 10.0,
        http: Optional[httpx.Client] = None,
    ) -> None:
        self._http = http or httpx.Client(
            base_url=endpoint.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def _request(
        self, method: str, path: str, *, ok_404: bool = False, timeout: Optional[float] = None, **kwargs: Any
    ) -> Optional[Any]:
        if timeout is not None:
            kwargs["timeout"] = timeout
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise ControlPlaneError(f"{method} {path}: {exc}") from exc
        if response.status_code == 404 and ok_404:
            return None
        if response.status_code >= 400:
            raise ControlPlaneError(f"{method} {path}: {response.status_code} {response.text[:200]}")
        return response.json()

    def register_agent(self, name: str, public_key: str) -> dict:
        return self._request("POST", "/v1/agents", json={"name": name, "public_key": public_key})

    def publish_manifest(self, manifest: ScopeManifest) -> dict:
        return self._request("POST", f"/v1/agents/{manifest.agent_id}/manifests", json={"manifest": manifest.to_dict()})

    def current_manifest(self, agent_id: str) -> Optional[ScopeManifest]:
        data = self._request("GET", f"/v1/agents/{agent_id}/manifest", ok_404=True)
        return ScopeManifest.from_dict(data["manifest"]) if data else None

    def revoke_manifest(self, agent_id: str, version: int) -> dict:
        return self._request("POST", f"/v1/agents/{agent_id}/manifests/{version}/revoke")

    def revocation_check(self, agent_id: str, version: int, ttl_s: float = REVOCATION_TTL_S) -> Callable[[], bool]:
        """A cached `ScopeGuard(is_revoked=...)` callable. Network errors keep the last known answer."""
        state = {"value": False, "checked": float("-inf")}

        def check() -> bool:
            now = time.monotonic()
            if now - state["checked"] >= ttl_s:
                state["checked"] = now
                try:
                    data = self._request("GET", f"/v1/agents/{agent_id}/manifests/{version}")
                    state["value"] = bool(data and data.get("revoked_at"))
                except ControlPlaneError:
                    pass
            return state["value"]

        return check

    def trust_inputs(self, agent_id: str) -> dict:
        return self._request("GET", f"/v1/agents/{agent_id}/trust-inputs")

    def record_trust(self, agent_id: str, result: TrustResult, trigger_run_id: Optional[str] = None) -> dict:
        return self._request(
            "POST",
            f"/v1/agents/{agent_id}/trust",
            json={
                "score": result.score,
                "band": result.band,
                "components": {**result.components, "cap_inr": result.cap_inr},
                "trigger_run_id": trigger_run_id,
            },
        )

    def latest_trust(self, agent_id: str) -> Optional[dict]:
        return self._request("GET", f"/v1/agents/{agent_id}/trust", ok_404=True)

    def list_incidents(self, agent_id: Optional[str] = None, status: Optional[str] = None) -> List[dict]:
        params = {k: v for k, v in (("agent_id", agent_id), ("status", status)) if v}
        return self._request("GET", "/v1/incidents", params=params)

    def get_incident(self, incident_id: str) -> dict:
        return self._request("GET", f"/v1/incidents/{incident_id}")

    def get_run(self, run_id: str) -> dict:
        return self._request("GET", f"/v1/runs/{run_id}")

    def classify_incident(self, incident_id: str) -> dict:
        return self._request("POST", f"/v1/incidents/{incident_id}/classify", timeout=120.0)

    def merge_incident_details(self, incident_id: str, details: dict) -> dict:
        return self._request("POST", f"/v1/incidents/{incident_id}/details", json={"details": details})

    def resolve_incident(self, incident_id: str) -> dict:
        return self._request("POST", f"/v1/incidents/{incident_id}/resolve")

    def put_filing(self, incident_id: str, packet: dict) -> dict:
        return self._request(
            "POST",
            f"/v1/incidents/{incident_id}/filings",
            json={"type": packet["type"], "packet": packet, "trace_hash": packet["trace_hash"], "simulated": packet["simulated"]},
        )

    def list_filings(self, incident_id: str) -> List[dict]:
        return self._request("GET", f"/v1/incidents/{incident_id}/filings")

    def manifest_version(self, agent_id: str, version: int) -> Optional[dict]:
        data = self._request("GET", f"/v1/agents/{agent_id}/manifests/{version}", ok_404=True)
        return data["manifest"] if data else None

    def put_blob(self, payload: bytes, mime: str) -> dict:
        try:
            response = self._http.post("/v1/blobs", content=payload, headers={"Content-Type": mime})
        except httpx.RequestError as exc:
            raise ControlPlaneError(f"POST /v1/blobs: {exc}") from exc
        if response.status_code >= 400:
            raise ControlPlaneError(f"POST /v1/blobs: {response.status_code} {response.text[:200]}")
        return response.json()

    def share_incident(self, incident_id: str) -> Optional[str]:
        return self._request("POST", f"/v1/incidents/{incident_id}/share")["share_token"]

    def capture_case(self, body: dict) -> dict:
        return self._request("POST", "/v1/regression-cases/capture-production", json=body)

    def set_case_status(self, case_id: str, status: str) -> dict:
        return self._request("PATCH", f"/v1/regression-cases/{case_id}", json={"status": status})

    def record_model_runs(self, runs: List[dict]) -> List[dict]:
        out: List[dict] = []
        for start in range(0, len(runs), 500):
            out += self._request("POST", "/v1/model-runs", json={"runs": runs[start : start + 500]})
        return out

    def list_model_runs(self, source_run_id: Optional[str] = None) -> List[dict]:
        params = {"source_run_id": source_run_id} if source_run_id else {}
        return self._request("GET", "/v1/model-runs", params=params)


def recompute_trust(
    client: ControlPlaneClient,
    agent_id: str,
    *,
    trigger_run_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> TrustResult:
    inputs = client.trust_inputs(agent_id)
    result = compute_trust(
        recent_failure_rate=inputs["recent_failure_rate"],
        regression_pass_rate=inputs["regression_pass_rate"],
        violation_times=[_ts(v) for v in inputs["violation_times"]],
        runs_count=inputs["runs_count"],
        now=now,
    )
    client.record_trust(agent_id, result, trigger_run_id)
    return result


def trust_refresher(client: ControlPlaneClient, guard: Any, run_id_provider: Callable[[], str]) -> Callable[[dict], None]:
    """An `after_halt` callback: recompute the agent's score and lower the guard's trust cap."""

    def refresh(alert: dict) -> None:
        agent_id = alert.get("agent_id")
        if not agent_id:
            return
        result = recompute_trust(client, agent_id, trigger_run_id=run_id_provider())
        guard.set_trust_cap(result.cap_inr)

    return refresh


class HttpTokenStore:
    """Persists broker tokens (hash only) through the ingest API."""

    def __init__(self, client: ControlPlaneClient) -> None:
        self._client = client

    def put(self, record: TokenRecord) -> None:
        self._client._request(
            "POST",
            f"/v1/agents/{record.agent_id}/tokens",
            json={
                "id": record.id,
                "connector": record.connector,
                "scopes": record.scopes,
                "expires_at": record.expires_at.isoformat() if record.expires_at else None,
            },
        )

    def get(self, token_id: str) -> Optional[TokenRecord]:
        data = self._client._request("GET", f"/v1/tokens/{token_id}", ok_404=True)
        if data is None:
            return None
        return TokenRecord(
            id=data["id"],
            agent_id=data["agent_id"],
            connector=data["connector"],
            scopes=data["scopes"],
            issued_at=_ts(data["issued_at"]),
            expires_at=_ts(data["expires_at"]),
            revoked_at=_ts(data["revoked_at"]),
        )

    def revoke(self, token_id: str, at: datetime) -> bool:
        return self._client._request("POST", f"/v1/tokens/{token_id}/revoke", ok_404=True) is not None
