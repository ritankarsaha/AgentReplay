"""Ingest API client for regression cases — the CI gate's only network dependency."""

from __future__ import annotations

from typing import List, Optional

import httpx

from ..replay.exceptions import TraceFetchError
from .runner import CaseRunResult, RegressionCase

CASES_PATH = "/v1/regression-cases"


def _build_client(timeout: float) -> httpx.Client:
    return httpx.Client(timeout=timeout)


def _case_from_dict(data: dict) -> RegressionCase:
    return RegressionCase(
        case_id=data["id"],
        title=data.get("title") or data["id"],
        entrypoint=data["entrypoint"],
        recorded_input=data.get("recorded_input"),
        tool_spans=data.get("tool_spans") or [],
        assertion_spec=data.get("assertion_spec"),
        priority=data.get("priority") or "P1",
    )


def fetch_active_cases(
    *, endpoint: str, api_key: str, status: str = "active", timeout: float = 30.0
) -> List[RegressionCase]:
    url = f"{endpoint.rstrip('/')}{CASES_PATH}"
    client = _build_client(timeout)
    try:
        response = client.get(
            url,
            params={"status": status},
            headers={"Authorization": f"Bearer {api_key}"},
        )
    except httpx.RequestError as exc:
        raise TraceFetchError("regression-cases", f"network error contacting {endpoint}: {exc}") from exc
    finally:
        client.close()

    if response.status_code == 401:
        raise TraceFetchError("regression-cases", "401 Unauthorized — check the API key")
    if response.status_code >= 400:
        raise TraceFetchError(
            "regression-cases", f"ingest API returned {response.status_code}: {response.text[:200]}"
        )

    body = response.json()
    return [_case_from_dict(c) for c in body.get("cases", [])]


def report_result(
    result: CaseRunResult,
    *,
    endpoint: str,
    api_key: str,
    agent_version: Optional[str] = None,
    verdict: Optional[str] = None,
    timeout: float = 30.0,
) -> None:
    """Best-effort: callers should catch `TraceFetchError` and warn rather than
    fail the gate run, since the verdict is already decided locally by this point.
    """
    url = f"{endpoint.rstrip('/')}{CASES_PATH}/{result.case_id}/results"
    body = {
        "agent_version": agent_version,
        "trials": result.trials,
        "passes": result.passes,
        "verdict": verdict,
        "details": [
            {
                "trial": t.trial,
                "passed": t.passed,
                "error": t.error,
                "duration_ms": t.duration_ms,
            }
            for t in result.trial_results
        ],
    }
    client = _build_client(timeout)
    try:
        response = client.post(url, json=body, headers={"Authorization": f"Bearer {api_key}"})
    except httpx.RequestError as exc:
        raise TraceFetchError(result.case_id, f"network error contacting {endpoint}: {exc}") from exc
    finally:
        client.close()

    if response.status_code >= 400:
        raise TraceFetchError(
            result.case_id, f"ingest API returned {response.status_code}: {response.text[:200]}"
        )
