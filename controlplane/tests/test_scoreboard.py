from __future__ import annotations

import json

from controlplane.learn import scoreboard as sb
from controlplane.transact.choosers import ChoiceTask
from controlplane.transact.travelbot import parse_sms
from world import AirlineSite, data

MODELS = (
    sb.ModelSpec("good", "meta", "http://x", ("K",)),
    sb.ModelSpec("bad", "meta", "http://x", ("K",)),
    sb.ModelSpec("flaky", "nim", "http://x", ("K",)),
)


def make_task():
    site = AirlineSite()
    return ChoiceTask(
        parse_sms("Book BLR→CCU Friday morning, under ₹6000."),
        site.search("BLR", "CCU", data.TRAVEL_DATE)["results"],
        site.read_doc(data.FARE_RULES_DOC_ID),
    )


def reply(flight, believed="07:30"):
    return json.dumps({"flight": flight, "believed_depart": believed, "reason": "r"})


def ask_by_model(spec, prompt):
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 0}
    if spec.name == "good":
        return reply(None, ""), {**usage}
    if spec.name == "bad":
        return reply("6E-871"), usage
    raise RuntimeError("model unavailable")


def test_fan_out_scores_each_model_deterministically():
    rows = sb.fan_out(make_task(), models=MODELS, trials=3, ask=ask_by_model)
    assert len(rows) == 9
    by_model = {m: [r for r in rows if r["model"] == m] for m in ("good", "bad", "flaky")}
    assert {r["verdict"] for r in by_model["good"]} == {sb.CORRECT}
    assert {r["verdict"] for r in by_model["bad"]} == {sb.REPEATS}
    assert by_model["bad"][0]["flight"] == "6E-871" and "19:30" in by_model["bad"][0]["reason"]
    assert {r["verdict"] for r in by_model["flaky"]} == {sb.ERROR}
    assert "RuntimeError" in by_model["flaky"][0]["error"]


def test_empty_output_is_retried_once_then_reported_as_an_error():
    calls = {"n": 0}

    def ask(spec, prompt):
        calls["n"] += 1
        return ("" if calls["n"] == 1 else reply(None, "")), None

    rows = sb.fan_out(make_task(), models=MODELS[:1], trials=1, ask=ask)
    assert rows[0]["verdict"] == sb.CORRECT and rows[0]["attempts"] == 2

    rows = sb.fan_out(make_task(), models=MODELS[:1], trials=1, ask=lambda s, p: ("no json", None))
    assert rows[0]["verdict"] == sb.ERROR and "2 attempts" in rows[0]["error"]


def test_cost_is_only_reported_for_priced_models():
    assert sb.cost_usd("muse-spark-1.3", {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}) == 5.5
    assert sb.cost_usd("meta/muse-glimmer-30b", {"prompt_tokens": 10, "completion_tokens": 10}) is None
    assert sb.cost_usd("muse-spark-1.3", None) is None


def test_aggregate_counts_errors_instead_of_hiding_them():
    rows = sb.fan_out(make_task(), models=MODELS, trials=3, ask=ask_by_model)
    runs = sb.to_model_runs(rows, source_run_id="run-1", span_id="span-1")
    assert all(r["source_run_id"] == "run-1" and r["verdict"] in (sb.CORRECT, sb.REPEATS, sb.ERROR) for r in runs)
    table = {r["model"]: r for r in sb.aggregate(runs)}
    assert table["good"]["repeats_the_mistake"] is False and table["good"]["correct_rate"] == 1.0
    assert table["bad"]["repeats_the_mistake"] is True and table["bad"]["correct_rate"] == 0.0
    assert table["flaky"]["errors"] == 3 and table["flaky"]["repeats_the_mistake"] is None
    assert table["flaky"]["correct_rate"] is None


def test_render_table_marks_repeaters():
    rows = sb.fan_out(make_task(), models=MODELS, trials=1, ask=ask_by_model)
    text = sb.render_table(sb.aggregate(sb.to_model_runs(rows, source_run_id="r", span_id="s")))
    lines = {line.split()[0]: line for line in text.splitlines()[2:]}
    assert "YES" in lines["bad"] and "no" in lines["good"] and "n/a" in lines["flaky"]


def test_task_from_facts_requires_the_evidence(travelbot_trace):
    from controlplane.learn.causation import TraceFacts, extract_facts

    task = sb.task_from_facts(extract_facts(travelbot_trace["spans"]))
    assert task.intent.budget_inr == 6000 and task.doc["source_version"] == 5 and len(task.results) == 4
    import pytest

    with pytest.raises(ValueError):
        sb.task_from_facts(TraceFacts())


def test_model_spec_api_key_lookup(monkeypatch):
    spec = sb.ModelSpec("m", "meta", "http://x", ("FIRST", "SECOND"))
    assert spec.api_key() is None
    monkeypatch.setenv("SECOND", "b")
    assert spec.api_key() == "b"
    monkeypatch.setenv("FIRST", "a")
    assert spec.api_key() == "a"
