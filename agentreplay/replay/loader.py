"""Load a recorded trace for replay (chunk 3.4, + Day 3 backlog: local files).

`replay_mode()` (chunk 3.1/3.2) takes an already-loaded `spans` list — it
deliberately doesn't know how that list was obtained, so it works equally
well against a live `GET /v1/runs/{run_id}` response, a `Span.to_dict()`
list built in a test, or a local JSON dump. This module provides both:
`fetch_run()` (the ingest API path) and `load_run_from_file()` (a trace
shared offline — a redacted export for a bug report, or a design partner's
call without API access — no credentials needed at all).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Union

import httpx

from .exceptions import TraceFetchError

RUNS_PATH = "/v1/runs"


def _build_client(timeout: float) -> httpx.Client:
    return httpx.Client(timeout=timeout)


def fetch_run(run_id: str, *, endpoint: str, api_key: str, timeout: float = 30.0) -> dict:
    """`GET {endpoint}/v1/runs/{run_id}` — returns the decoded `RunDetailOut` JSON.

    Raises `TraceFetchError` on any failure (network error, timeout, 401,
    404, or any other non-2xx response) — one exception type for the CLI
    to catch regardless of which step failed.
    """
    url = f"{endpoint.rstrip('/')}{RUNS_PATH}/{run_id}"
    client = _build_client(timeout)
    try:
        response = client.get(url, headers={"Authorization": f"Bearer {api_key}"})
    except httpx.RequestError as exc:
        raise TraceFetchError(run_id, f"network error contacting {endpoint}: {exc}") from exc
    finally:
        client.close()

    if response.status_code == 401:
        raise TraceFetchError(run_id, "401 Unauthorized — check the API key")
    if response.status_code == 404:
        raise TraceFetchError(run_id, f"run not found at {endpoint}{RUNS_PATH}/{run_id}")
    if response.status_code >= 400:
        raise TraceFetchError(
            run_id, f"ingest API returned {response.status_code}: {response.text[:200]}"
        )

    return response.json()


def load_run_from_file(path: Union[str, "Path"]) -> dict:
    """Load a recorded trace from a local JSON file instead of the ingest API.

    Accepts the same shape `fetch_run()` returns — a full `GET /v1/runs/{run_id}`
    `RunDetailOut` dump, or just `{"spans": [...]}`, since that's all
    `replay_mode()` actually reads. Raises `TraceFetchError` uniformly (the
    same exception type `fetch_run()` raises) for a missing file, invalid
    JSON, or a body missing the required `spans` key — one exception type
    for the CLI to catch regardless of which loading path was used.
    """
    file_path = Path(path)
    label = str(file_path)

    try:
        text = file_path.read_text()
    except OSError as exc:
        raise TraceFetchError(label, f"could not read trace file '{file_path}': {exc}") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TraceFetchError(label, f"'{file_path}' is not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or "spans" not in data:
        raise TraceFetchError(
            label,
            f"'{file_path}' is missing the required 'spans' key "
            "(expected the same shape as GET /v1/runs/{run_id})",
        )

    return data
