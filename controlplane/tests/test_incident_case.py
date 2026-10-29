from __future__ import annotations

import os

from controlplane.learn import incident_case as ic
from controlplane.learn.causation import extract_facts
from agentreplay.regression.client import _case_from_dict
from agentreplay.regression.runner import run_case


def case_dict(trace, facts):
    return {
        "id": "case-1",
        "title": "t",
        "entrypoint": ic.ENTRYPOINT,
        "recorded_input": facts.intent.text,
        "tool_spans": ic.tool_spans_of(trace["spans"]),
        "assertion_spec": ic.build_assertion_spec(facts),
        "priority": "P0",
    }


def test_assertion_spec_forbids_booking_outside_the_requested_window(travelbot_trace):
    spec = ic.build_assertion_spec(extract_facts(travelbot_trace["spans"]))
    window, budget = spec["output_checks"]
    assert (window["start"], window["end"], window["allow_missing"]) == ("05:00", "12:00", True)
    assert budget["op"] == "lte" and budget["value"] == 6000
    assert spec["no_exception"] is True


def test_assertion_spec_without_a_part_of_day_checks_budget_only():
    from controlplane.learn.causation import TraceFacts
    from controlplane.transact.choosers import Intent

    facts = TraceFacts(intent=Intent("BLR", "CCU", "Friday", None, 6000, "x"))
    assert [c["path"] for c in ic.build_assertion_spec(facts)["output_checks"]] == ["booking.price_inr"]


def test_case_is_red_on_the_broken_agent_and_green_on_the_fix(travelbot_trace):
    case = _case_from_dict(case_dict(travelbot_trace, extract_facts(travelbot_trace["spans"])))
    with ic.agent_version("v1"):
        red = run_case(case, trials=3)
    with ic.agent_version("v2"):
        green = run_case(case, trials=3)
    assert (red.passes, red.trials) == (0, 3)
    assert "outside the requested morning window" in red.trial_results[0].error
    assert (green.passes, green.trials) == (3, 3)


def test_agent_version_restores_the_environment():
    os.environ.pop(ic.VERSION_ENV, None)
    with ic.agent_version("v2"):
        assert os.environ[ic.VERSION_ENV] == "v2"
    assert ic.VERSION_ENV not in os.environ
    os.environ[ic.VERSION_ENV] = "v1"
    with ic.agent_version("v2"):
        pass
    assert os.environ[ic.VERSION_ENV] == "v1"
    del os.environ[ic.VERSION_ENV]


def test_run_and_report_reports_results_and_refreshes_trust(travelbot_trace, monkeypatch):
    facts = extract_facts(travelbot_trace["spans"])
    reported, refreshed = [], []
    monkeypatch.setattr(ic, "report_result", lambda result, **kw: reported.append((result.passes, kw["verdict"], kw["agent_version"])))
    monkeypatch.setattr(
        ic, "recompute_trust", lambda client, agent_id, trigger_run_id=None: refreshed.append(trigger_run_id) or type("T", (), {"to_dict": lambda self: {"score": 1}})()
    )
    case = case_dict(travelbot_trace, facts)
    red = ic.run_and_report(None, case, version="v1", endpoint="x", api_key="k", agent_id="agt_1")
    green = ic.run_and_report(None, case, version="v2", endpoint="x", api_key="k", agent_id="agt_1")
    assert red["blocking"] is True and red["verdict"] == "fail"
    assert green["blocking"] is False and green["verdict"] == "pass"
    assert reported == [(0, "fail", "travelbot-v1"), (3, "pass", "travelbot-v2")]
    assert refreshed == ["regression:case-1", "regression:case-1"]


def test_generated_pytest_file_is_red_then_green(travelbot_trace, tmp_path):
    import subprocess
    import sys

    facts = extract_facts(travelbot_trace["spans"])
    generated = ic.write_pytest_files({"id": "inc"}, travelbot_trace["spans"], facts, tmp_path, "run-x")
    source = generated.test_path.read_text()
    assert "OUTPUT_CHECKS" in source and ic.ENTRYPOINT in source

    def run(version):
        env = {**os.environ, ic.VERSION_ENV: version, "PYTHONPATH": os.pathsep.join([os.getcwd(), str(tmp_path)])}
        return subprocess.run(
            [sys.executable, "-m", "pytest", str(generated.test_path), "-q", "-p", "no:cacheprovider", "--rootdir", str(tmp_path)],
            capture_output=True, text=True, env=env, cwd=str(tmp_path),
        )

    assert run("v1").returncode == 1
    assert run("v2").returncode == 0
