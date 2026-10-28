"""CI gate orchestration: `agentreplay/gate@v1`.

Fetches active regression cases, runs each against this checkout's agent
code (Mode B), evaluates the gate verdict, and renders a Markdown report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..replay.exceptions import TraceFetchError
from .client import fetch_active_cases, report_result
from .gate import DEFAULT_THRESHOLDS, GateReport, Verdict, evaluate_gate
from .runner import CaseRunResult, run_case

_VERDICT_ICON = {
    Verdict.PASS: "✅",
    Verdict.WARN: "⚠️",
    Verdict.FAIL: "❌",
    Verdict.INSUFFICIENT_EVIDENCE: "❔",
}


@dataclass
class GateRunOutcome:
    case_results: List[CaseRunResult]
    report: GateReport
    report_errors: List[str]


def run_gate(
    *,
    endpoint: str,
    api_key: str,
    trials: int = 3,
    agent_version: Optional[str] = None,
    thresholds: Optional[dict] = None,
) -> GateRunOutcome:
    """Raises `TraceFetchError` only if fetching the case list itself fails.
    Reporting each result back is best-effort — failures land in `report_errors`
    rather than affecting the already-decided verdict.
    """
    cases = fetch_active_cases(endpoint=endpoint, api_key=api_key, status="active")

    case_results = [run_case(case, trials=trials) for case in cases]
    report = evaluate_gate(case_results, thresholds=thresholds or DEFAULT_THRESHOLDS)

    report_errors: List[str] = []
    verdict_by_case = {cv.case_id: cv.verdict.value for cv in report.case_verdicts}
    for result in case_results:
        try:
            report_result(
                result,
                endpoint=endpoint,
                api_key=api_key,
                agent_version=agent_version,
                verdict=verdict_by_case.get(result.case_id),
            )
        except TraceFetchError as exc:
            report_errors.append(str(exc))

    return GateRunOutcome(case_results=case_results, report=report, report_errors=report_errors)


def render_markdown_report(outcome: GateRunOutcome) -> str:
    lines = [
        f"## AgentReplay regression gate — {_VERDICT_ICON[outcome.report.overall]} `{outcome.report.overall.value}`",
        "",
        "| Priority | Case | Pass rate | Verdict | Reason |",
        "|---|---|---|---|---|",
    ]
    for cv in outcome.report.case_verdicts:
        lines.append(
            f"| {cv.priority} | {cv.title} | {cv.passes}/{cv.trials} | "
            f"{_VERDICT_ICON[cv.verdict]} {cv.verdict.value} | {cv.reason} |"
        )

    if not outcome.report.case_verdicts:
        lines.append("| — | *(no active regression cases registered)* | — | — | — |")

    if outcome.report_errors:
        lines.append("")
        lines.append("<details><summary>Result-reporting warnings (non-blocking)</summary>")
        lines.append("")
        for err in outcome.report_errors:
            lines.append(f"- {err}")
        lines.append("")
        lines.append("</details>")

    return "\n".join(lines)
