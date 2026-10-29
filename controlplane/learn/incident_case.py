"""Regression test from an incident: register it as a case, run it RED/GREEN, report the results."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from agentreplay.regression.client import _case_from_dict, report_result
from agentreplay.regression.gate import evaluate_gate
from agentreplay.regression.runner import CaseRunResult, run_case
from agentreplay.testgen.generate import GeneratedTest, _write_generated_test
from controlplane.client import ControlPlaneClient, recompute_trust
from controlplane.learn.causation import TraceFacts
from controlplane.transact.choosers import daypart_window

ENTRYPOINT = "controlplane.transact.travelbot:entrypoint"
VERSION_ENV = "TRAVELBOT_VERSION"


def build_assertion_spec(facts: TraceFacts) -> Dict[str, Any]:
    intent = facts.intent
    checks: List[dict] = []
    if intent.part_of_day:
        start, end = daypart_window(intent.part_of_day)
        checks.append(
            {
                "path": "booking.depart_at",
                "op": "time_in_window",
                "start": start,
                "end": end,
                "allow_missing": True,
                "description": f"must not book a departure outside the requested {intent.part_of_day} window",
            }
        )
    checks.append(
        {
            "path": "booking.price_inr",
            "op": "lte",
            "value": intent.budget_inr,
            "allow_missing": True,
            "description": "must not book above the requested budget",
        }
    )
    return {
        "no_exception": True,
        "must_call_tools": [],
        "must_not_call_tools": [],
        "max_steps": None,
        "output_checks": checks,
        "rationale": "The agent booked a flight that contradicted the user's requested departure window.",
    }


def tool_spans_of(spans: List[dict]) -> List[dict]:
    return [s for s in spans if s["type"] == "tool"]


def register_case(
    client: ControlPlaneClient,
    *,
    incident: dict,
    facts: TraceFacts,
    spans: List[dict],
    classification: Optional[dict] = None,
    priority: str = "P0",
) -> dict:
    case = client.capture_case(
        {
            "entrypoint": ENTRYPOINT,
            "recorded_input": facts.intent.text,
            "tool_spans": tool_spans_of(spans),
            "assertion_spec": build_assertion_spec(facts),
            "title": f"Do not book outside the requested window ({incident['id'][:8]})",
            "priority": priority,
            "incident_id": incident["id"],
            "failure_class": (classification or {}).get("failure_class"),
            "created_by": "controlplane",
        }
    )
    return client.set_case_status(case["id"], "active")


@contextmanager
def agent_version(version: str) -> Iterator[None]:
    previous = os.environ.get(VERSION_ENV)
    os.environ[VERSION_ENV] = version
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(VERSION_ENV, None)
        else:
            os.environ[VERSION_ENV] = previous


def run_and_report(
    client: ControlPlaneClient,
    case: dict,
    *,
    version: str,
    endpoint: str,
    api_key: str,
    agent_id: Optional[str] = None,
    trials: int = 3,
) -> Dict[str, Any]:
    """Run the case N times on `version`, report to ingest, and refresh the agent's trust score."""
    with agent_version(version):
        result: CaseRunResult = run_case(_case_from_dict(case), trials=trials)
    report = evaluate_gate([result])
    report_result(
        result, endpoint=endpoint, api_key=api_key, agent_version=f"travelbot-{version}", verdict=report.overall.value
    )
    trust = recompute_trust(client, agent_id, trigger_run_id=f"regression:{case['id']}") if agent_id else None
    return {
        "version": version,
        "passes": result.passes,
        "trials": result.trials,
        "verdict": report.overall.value,
        "blocking": report.blocking,
        "errors": sorted({t.error for t in result.trial_results if t.error}),
        "trust": trust.to_dict() if trust else None,
    }


def write_pytest_files(
    incident: dict, spans: List[dict], facts: TraceFacts, out_dir: Path, run_id: str
) -> GeneratedTest:
    request = {
        "id": "recorded-input",
        "type": "input",
        "name": "request",
        "parent_id": None,
        "input": facts.intent.text,
        "output": None,
        "error": None,
        "started_at": "",
        "fingerprint": "recorded-input",
    }
    data = {
        "spans": [request, *tool_spans_of(spans)],
        "diagnosis": {"assertion_spec": build_assertion_spec(facts)},
    }
    return _write_generated_test(run_id, data, ENTRYPOINT, out_dir)
