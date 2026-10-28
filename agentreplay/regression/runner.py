"""N-trial regression runner: Mode B (live LLM calls, mocked tools).

Runs the same shape the generated pytest file uses — `mock_tools_mode()` +
`call_entrypoint_with_input()` + `assertions.run_assertion_spec()` — looped
`trials` times in-process and aggregated into a pass rate.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, List, Optional

from ..replay.client import mock_tools_mode
from ..replay.runner import resolve_entrypoint
from ..testgen.assertions import run_assertion_spec
from ..testgen.entrypoint import call_entrypoint_with_input


@dataclass
class RegressionCase:
    case_id: str
    title: str
    entrypoint: str
    recorded_input: Any
    tool_spans: List[dict] = field(default_factory=list)
    assertion_spec: Optional[dict] = None
    priority: str = "P1"


@dataclass
class TrialResult:
    trial: int
    passed: bool
    error: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class CaseRunResult:
    case_id: str
    title: str
    priority: str
    trials: int
    passes: int
    trial_results: List[TrialResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passes / self.trials if self.trials else 0.0


def run_trial(case: RegressionCase, trial_index: int) -> TrialResult:
    """Run `case` once. Only a `resolve_entrypoint()` setup error propagates —
    an assertion failure or agent exception is captured into the result.
    """
    func = resolve_entrypoint(case.entrypoint)
    started = time.monotonic()

    exception: Optional[BaseException] = None
    result: Any = None
    with mock_tools_mode(case.tool_spans) as tool_run:
        try:
            result = call_entrypoint_with_input(func, case.recorded_input)
        except Exception as exc:  # noqa: BLE001
            exception = exc

        try:
            run_assertion_spec(
                case.assertion_spec, tool_run=tool_run, result=result, exception=exception
            )
        except AssertionError as exc:
            passed, error = False, str(exc)
        except Exception as exc:
            passed, error = False, f"{type(exc).__name__}: {exc}"
        else:
            passed, error = True, None

    duration_ms = (time.monotonic() - started) * 1000
    return TrialResult(trial=trial_index, passed=passed, error=error, duration_ms=duration_ms)


def run_case(case: RegressionCase, trials: int = 3) -> CaseRunResult:
    trial_results = [run_trial(case, i) for i in range(trials)]
    passes = sum(1 for t in trial_results if t.passed)
    return CaseRunResult(
        case_id=case.case_id,
        title=case.title,
        priority=case.priority,
        trials=trials,
        passes=passes,
        trial_results=trial_results,
    )
