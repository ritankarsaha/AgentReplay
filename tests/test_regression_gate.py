from __future__ import annotations

from agentreplay.regression.gate import (
    DEFAULT_THRESHOLDS,
    PriorityThreshold,
    Verdict,
    evaluate_gate,
)
from agentreplay.regression.runner import CaseRunResult, TrialResult


def _result(case_id, priority, trials, passes) -> CaseRunResult:
    trial_results = [TrialResult(trial=i, passed=i < passes) for i in range(trials)]
    return CaseRunResult(
        case_id=case_id, title=case_id, priority=priority, trials=trials, passes=passes,
        trial_results=trial_results,
    )


def test_p0_case_fails_on_any_miss():
    report = evaluate_gate([_result("c0", "P0", 3, 2)])
    assert report.case_verdicts[0].verdict is Verdict.FAIL
    assert report.overall is Verdict.FAIL
    assert report.blocking is True


def test_p0_case_passes_on_clean_sweep():
    report = evaluate_gate([_result("c0", "P0", 3, 3)])
    assert report.case_verdicts[0].verdict is Verdict.PASS
    assert report.overall is Verdict.PASS
    assert report.blocking is False


def test_p1_case_warns_below_clean_sweep_but_above_fail_threshold():
    # 2/3 = 0.666..., at the P1 fail_below threshold (2/3) -> not below it -> not FAIL.
    report = evaluate_gate([_result("c1", "P1", 3, 2)])
    assert report.case_verdicts[0].verdict is Verdict.WARN
    assert report.overall is Verdict.WARN
    assert report.blocking is False


def test_p1_case_fails_below_two_thirds():
    report = evaluate_gate([_result("c1", "P1", 3, 1)])
    assert report.case_verdicts[0].verdict is Verdict.FAIL
    assert report.overall is Verdict.FAIL


def test_p2_case_never_blocks_but_warns_if_imperfect():
    report = evaluate_gate([_result("c2", "P2", 3, 0)])
    assert report.case_verdicts[0].verdict is Verdict.WARN
    assert report.overall is Verdict.WARN
    assert report.blocking is False


def test_zero_trials_is_insufficient_evidence_not_pass():
    report = evaluate_gate([_result("c3", "P0", 0, 0)])
    assert report.case_verdicts[0].verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert report.overall is Verdict.INSUFFICIENT_EVIDENCE
    assert report.blocking is False


def test_overall_verdict_is_the_worst_of_any_case_fail_beats_warn():
    report = evaluate_gate([
        _result("c0", "P0", 3, 3),  # PASS
        _result("c1", "P1", 3, 2),  # WARN
        _result("c2", "P0", 3, 2),  # FAIL
    ])
    assert report.overall is Verdict.FAIL


def test_overall_verdict_warn_beats_insufficient_evidence():
    report = evaluate_gate([
        _result("c0", "P0", 0, 0),  # INSUFFICIENT_EVIDENCE
        _result("c1", "P1", 3, 2),  # WARN
    ])
    assert report.overall is Verdict.WARN


def test_empty_results_list_is_overall_pass():
    report = evaluate_gate([])
    assert report.overall is Verdict.PASS
    assert report.case_verdicts == []


def test_custom_thresholds_override_defaults():
    strict = {"P2": PriorityThreshold(fail_below=1.0, warn_below=1.0)}
    report = evaluate_gate([_result("c2", "P2", 3, 2)], thresholds=strict)
    assert report.case_verdicts[0].verdict is Verdict.FAIL


def test_default_thresholds_cover_p0_p1_p2():
    assert set(DEFAULT_THRESHOLDS.keys()) == {"P0", "P1", "P2"}
