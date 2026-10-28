"""Regression gate policy/verdict.

Turns a batch of `CaseRunResult`s into a per-case verdict and one overall
verdict the CI gate blocks (or doesn't) on, using per-priority pass-rate
thresholds. A case with zero trials is `INSUFFICIENT_EVIDENCE`, never a
silent pass. Baseline-vs-candidate delta comparison is not implemented —
there's no stored "last known-good" result per case to diff against yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from .runner import CaseRunResult


class Verdict(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class PriorityThreshold:
    """`fail_below`: a pass rate strictly below this blocks the gate.
    `warn_below`: below this (but >= `fail_below`) is a non-blocking warning.
    """

    fail_below: float
    warn_below: float = 1.0


DEFAULT_THRESHOLDS: Dict[str, PriorityThreshold] = {
    "P0": PriorityThreshold(fail_below=1.0, warn_below=1.0),
    "P1": PriorityThreshold(fail_below=2 / 3, warn_below=1.0),
    "P2": PriorityThreshold(fail_below=0.0, warn_below=1.0),
}


@dataclass
class CaseVerdict:
    case_id: str
    title: str
    priority: str
    trials: int
    passes: int
    pass_rate: float
    verdict: Verdict
    reason: str


@dataclass
class GateReport:
    case_verdicts: List[CaseVerdict]
    overall: Verdict

    @property
    def blocking(self) -> bool:
        return self.overall is Verdict.FAIL


def _verdict_for_case(
    result: CaseRunResult, thresholds: Dict[str, PriorityThreshold]
) -> CaseVerdict:
    if result.trials == 0:
        return CaseVerdict(
            case_id=result.case_id,
            title=result.title,
            priority=result.priority,
            trials=0,
            passes=0,
            pass_rate=0.0,
            verdict=Verdict.INSUFFICIENT_EVIDENCE,
            reason="0 trials were run for this case — treat as unproven, not passing",
        )

    threshold = thresholds.get(result.priority, DEFAULT_THRESHOLDS.get(result.priority, PriorityThreshold(fail_below=1.0)))
    rate = result.pass_rate

    if rate < threshold.fail_below:
        verdict = Verdict.FAIL
        reason = (
            f"pass rate {result.passes}/{result.trials} is below the "
            f"{threshold.fail_below:.0%} {result.priority} blocking threshold"
        )
    elif rate < threshold.warn_below:
        verdict = Verdict.WARN
        reason = (
            f"pass rate {result.passes}/{result.trials} is below a clean sweep "
            f"({threshold.warn_below:.0%}) but at/above the {result.priority} blocking threshold"
        )
    else:
        verdict = Verdict.PASS
        reason = f"pass rate {result.passes}/{result.trials} meets the {result.priority} threshold"

    return CaseVerdict(
        case_id=result.case_id,
        title=result.title,
        priority=result.priority,
        trials=result.trials,
        passes=result.passes,
        pass_rate=rate,
        verdict=verdict,
        reason=reason,
    )


def evaluate_gate(
    results: List[CaseRunResult],
    *,
    thresholds: Optional[Dict[str, PriorityThreshold]] = None,
) -> GateReport:
    """Overall verdict is the worst of any case's verdict: FAIL > WARN >
    INSUFFICIENT_EVIDENCE > PASS.
    """
    active_thresholds = thresholds or DEFAULT_THRESHOLDS
    case_verdicts = [_verdict_for_case(r, active_thresholds) for r in results]

    if any(cv.verdict is Verdict.FAIL for cv in case_verdicts):
        overall = Verdict.FAIL
    elif any(cv.verdict is Verdict.WARN for cv in case_verdicts):
        overall = Verdict.WARN
    elif any(cv.verdict is Verdict.INSUFFICIENT_EVIDENCE for cv in case_verdicts):
        overall = Verdict.INSUFFICIENT_EVIDENCE
    else:
        overall = Verdict.PASS

    return GateReport(case_verdicts=case_verdicts, overall=overall)
