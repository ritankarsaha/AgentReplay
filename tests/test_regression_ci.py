from __future__ import annotations

import pytest

from agentreplay.regression import ci as ci_module
from agentreplay.regression.gate import Verdict
from agentreplay.regression.runner import RegressionCase
from agentreplay.replay.exceptions import TraceFetchError


def _case(case_id="case-1", priority="P1") -> RegressionCase:
    return RegressionCase(
        case_id=case_id,
        title="a case",
        entrypoint="_regression_runner_fixture:main",
        recorded_input={"query": "hello"},
        tool_spans=[],
        assertion_spec=None,  # no spec -> every trial trivially passes
        priority=priority,
    )


def test_run_gate_fetches_runs_and_reports_results(monkeypatch):
    reported = []

    monkeypatch.setattr(ci_module, "fetch_active_cases", lambda **kw: [_case()])
    monkeypatch.setattr(
        ci_module, "report_result", lambda result, **kw: reported.append((result.case_id, kw))
    )

    outcome = ci_module.run_gate(endpoint="http://x", api_key="k", trials=2, agent_version="sha1")

    assert len(outcome.case_results) == 1
    assert outcome.case_results[0].trials == 2
    assert outcome.report.overall is Verdict.PASS
    assert outcome.report_errors == []
    assert reported[0][0] == "case-1"
    assert reported[0][1]["agent_version"] == "sha1"
    assert reported[0][1]["verdict"] == "pass"


def test_run_gate_propagates_fetch_failure(monkeypatch):
    def _raise(**kw):
        raise TraceFetchError("regression-cases", "boom")

    monkeypatch.setattr(ci_module, "fetch_active_cases", _raise)

    with pytest.raises(TraceFetchError):
        ci_module.run_gate(endpoint="http://x", api_key="k")


def test_run_gate_collects_report_errors_without_failing(monkeypatch):
    monkeypatch.setattr(ci_module, "fetch_active_cases", lambda **kw: [_case()])

    def _raise(result, **kw):
        raise TraceFetchError(result.case_id, "network hiccup")

    monkeypatch.setattr(ci_module, "report_result", _raise)

    outcome = ci_module.run_gate(endpoint="http://x", api_key="k")

    assert outcome.report.overall is Verdict.PASS  # local verdict unaffected
    assert len(outcome.report_errors) == 1
    assert "network hiccup" in outcome.report_errors[0]


def test_render_markdown_report_includes_overall_verdict_and_case_rows(monkeypatch):
    monkeypatch.setattr(ci_module, "fetch_active_cases", lambda **kw: [_case(priority="P0")])
    monkeypatch.setattr(ci_module, "report_result", lambda result, **kw: None)

    outcome = ci_module.run_gate(endpoint="http://x", api_key="k", trials=1)
    report_md = ci_module.render_markdown_report(outcome)

    assert "`pass`" in report_md
    assert "a case" in report_md
    assert "P0" in report_md


def test_render_markdown_report_handles_no_active_cases():
    outcome = ci_module.GateRunOutcome(
        case_results=[], report=ci_module.evaluate_gate([]), report_errors=[]
    )
    report_md = ci_module.render_markdown_report(outcome)
    assert "no active regression cases" in report_md
