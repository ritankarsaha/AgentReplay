from __future__ import annotations

from agentreplay.fingerprint import compute_fingerprint
from agentreplay.regression.runner import RegressionCase, run_case, run_trial
from agentreplay.serialize import safe_serialize
from agentreplay.typed_serialize import to_typed_json


def _tool_span(name: str, args: tuple, kwargs: dict, output) -> dict:
    payload = safe_serialize({"args": list(args), "kwargs": kwargs})
    fingerprint = compute_fingerprint({"tool": name, "input": payload})
    return {
        "id": f"span-{name}",
        "run_id": "run-1",
        "parent_id": None,
        "type": "tool",
        "name": name,
        "input": payload,
        "output": to_typed_json(output),
        "error": None,
        "started_at": "2026-01-01T00:00:00+00:00",
        "duration_ms": 1.0,
        "fingerprint": fingerprint,
    }


_SEARCH_SPAN = _tool_span("search", ("hello",), {}, "mocked result")


def _make_case(**overrides) -> RegressionCase:
    defaults = dict(
        case_id="case-1",
        title="a regression case",
        entrypoint="_regression_runner_fixture:main",
        recorded_input={"query": "hello"},
        tool_spans=[_SEARCH_SPAN],
        assertion_spec={"must_call_tools": ["search"], "no_exception": True},
        priority="P1",
    )
    defaults.update(overrides)
    return RegressionCase(**defaults)


def test_run_trial_passes_when_tool_called_and_assertion_satisfied():
    trial = run_trial(_make_case(), 0)
    assert trial.passed is True
    assert trial.error is None
    assert trial.trial == 0
    assert trial.duration_ms >= 0.0


def test_run_trial_fails_when_must_call_tool_missing():
    case = _make_case(
        entrypoint="_regression_runner_fixture:silent",
        assertion_spec={"must_call_tools": ["search"], "no_exception": True},
    )
    trial = run_trial(case, 0)
    assert trial.passed is False
    assert "search" in trial.error


def test_run_trial_fails_on_unhandled_exception_when_no_exception_true():
    case = _make_case(
        entrypoint="_regression_runner_fixture:boom",
        tool_spans=[],
        assertion_spec={"no_exception": True},
    )
    trial = run_trial(case, 0)
    assert trial.passed is False
    assert "entrypoint exploded" in trial.error


def test_run_trial_tolerates_exception_when_no_exception_false():
    case = _make_case(
        entrypoint="_regression_runner_fixture:boom",
        tool_spans=[],
        assertion_spec={"no_exception": False},
    )
    trial = run_trial(case, 0)
    assert trial.passed is True


def test_run_trial_passes_with_no_assertion_spec_at_all():
    case = _make_case(assertion_spec=None)
    trial = run_trial(case, 0)
    assert trial.passed is True


def test_run_case_aggregates_pass_rate_across_trials():
    result = run_case(_make_case(), trials=3)
    assert result.trials == 3
    assert result.passes == 3
    assert result.pass_rate == 1.0
    assert [t.trial for t in result.trial_results] == [0, 1, 2]


def test_run_case_reports_partial_pass_rate():
    case = _make_case(
        entrypoint="_regression_runner_fixture:silent",
        assertion_spec={"must_call_tools": ["search"]},
    )
    result = run_case(case, trials=3)
    assert result.trials == 3
    assert result.passes == 0
    assert result.pass_rate == 0.0


def test_case_run_result_pass_rate_is_zero_for_zero_trials():
    from agentreplay.regression.runner import CaseRunResult

    result = CaseRunResult(case_id="c", title="t", priority="P1", trials=0, passes=0)
    assert result.pass_rate == 0.0
