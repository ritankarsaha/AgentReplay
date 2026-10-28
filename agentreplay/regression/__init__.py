"""Mode B — Regression Replay + CI Gate.

Live LLM calls, mocked tools: run a regression case `trials` times, get a
pass rate, and evaluate it against a per-priority gate policy.
"""

from __future__ import annotations

from .ci import GateRunOutcome, render_markdown_report, run_gate
from .client import fetch_active_cases, report_result
from .gate import (
    DEFAULT_THRESHOLDS,
    CaseVerdict,
    GateReport,
    PriorityThreshold,
    Verdict,
    evaluate_gate,
)
from .runner import CaseRunResult, RegressionCase, TrialResult, run_case, run_trial

__all__ = [
    "RegressionCase",
    "TrialResult",
    "CaseRunResult",
    "run_case",
    "run_trial",
    "Verdict",
    "PriorityThreshold",
    "DEFAULT_THRESHOLDS",
    "CaseVerdict",
    "GateReport",
    "evaluate_gate",
    "fetch_active_cases",
    "report_result",
    "GateRunOutcome",
    "run_gate",
    "render_markdown_report",
]
