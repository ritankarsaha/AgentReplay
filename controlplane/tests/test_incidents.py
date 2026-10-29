from __future__ import annotations

import pytest

from controlplane.client import ControlPlaneError
from controlplane.incidents import IncidentPipeline


class FakeClient:
    def __init__(self, trace, *, classify=None, trust=None):
        self.trace, self._classify, self._trust = trace, classify, trust
        self.details, self.filings, self.cases, self.statuses = {}, {}, [], []

    def get_incident(self, incident_id):
        return {"id": incident_id, "run_id": "run-1", "agent_id": self.trace["agent_id"], "culprit_span_id": None}

    def get_run(self, run_id):
        return {"id": run_id, "spans": self.trace["spans"]}

    def classify_incident(self, incident_id):
        if isinstance(self._classify, Exception):
            raise self._classify
        return self._classify

    def merge_incident_details(self, incident_id, details):
        self.details.update(details)

    def manifest_version(self, agent_id, version):
        return {"agent_id": agent_id, "version": version}

    def put_filing(self, incident_id, packet):
        self.filings[packet["type"]] = packet

    def latest_trust(self, agent_id):
        return self._trust

    def capture_case(self, body):
        self.cases.append(body)
        return {"id": "case-1", "status": "proposed", **body}

    def set_case_status(self, case_id, status):
        self.statuses.append(status)
        return {"id": case_id, "status": status}


CLASSIFIED = {
    "classification_status": "done",
    "failure_class": "disobey_task_specification",
    "culprit_span_id": "abc",
    "diagnosis": {"text": "booked the wrong flight", "model": "muse-spark-1.3", "backend": "meta", "usage": {"cost_usd": 0.005}},
}


def test_full_pipeline_produces_every_artifact(travelbot_trace):
    client = FakeClient(travelbot_trace, classify=CLASSIFIED, trust={"band": "probation", "score": 536})
    report = IncidentPipeline(client).process("inc-1")

    assert report.classification["failure_class"] == "disobey_task_specification"
    assert report.culprit_span_id == "abc"
    assert {c["tag"] for c in report.causation} == {"intent_drift", "sponsored", "stale_data"}
    assert {f["kind"] for f in report.data_findings} == {"stale_doc", "contradiction"}
    assert set(client.filings) == {"dispute", "claim"}
    assert client.filings["claim"]["policy"]["trust_band"] == "probation"
    assert client.filings["claim"]["policy"]["premium_inr"] == 300.0
    assert client.filings["dispute"]["scope_manifest_hash"]
    assert set(client.details) >= {"classification", "causation", "data_findings", "culprit_span_id"}
    assert client.statuses == ["active"] and client.cases[0]["incident_id"] == "inc-1"
    assert client.cases[0]["failure_class"] == "disobey_task_specification"
    assert report.case["status"] == "active"


def test_classification_failure_is_recorded_and_the_rest_still_runs(travelbot_trace):
    client = FakeClient(travelbot_trace, classify=ControlPlaneError("503 no classifier"))
    report = IncidentPipeline(client).process("inc-1")
    assert report.classification is None and "classification unavailable" in report.notes[0]
    assert report.culprit_span_id == report.facts.purchase["id"]
    assert set(client.filings) == {"dispute", "claim"}


def test_classifier_error_status_is_surfaced_not_swallowed(travelbot_trace):
    bad = {"classification_status": "error", "failure_class": None, "culprit_span_id": None, "diagnosis": {"error": "quota"}}
    report = IncidentPipeline(FakeClient(travelbot_trace, classify=bad)).process("inc-1")
    assert report.classification is None and "quota" in report.notes[0]


def test_claim_without_a_trust_score_uses_the_restricted_band(travelbot_trace):
    client = FakeClient(travelbot_trace, classify=CLASSIFIED, trust=None)
    report = IncidentPipeline(client).process("inc-1")
    assert client.filings["claim"]["policy"]["trust_band"] == "restricted"
    assert any("no trust score" in n for n in report.notes)


def test_pipeline_options_skip_classification_and_case_registration(travelbot_trace):
    client = FakeClient(travelbot_trace, classify=ControlPlaneError("must not be called"), trust={"band": "standard", "score": 640})
    report = IncidentPipeline(client, classify=False, register_regression_case=False).process("inc-1")
    assert not any("classif" in n for n in report.notes) and client.cases == [] and report.case is None


def test_trace_without_a_request_is_stored_with_a_note_and_no_filings():
    trace = {"spans": [], "agent_id": "agt_1"}
    client = FakeClient(trace, classify=CLASSIFIED)
    report = IncidentPipeline(client).process("inc-1")
    assert report.dispute is None and client.filings == {}
    assert "no purchase" in " ".join(report.notes) or "no readable request" in " ".join(report.notes)
    assert "notes" in client.details


def test_a_correct_purchase_files_a_dispute_but_registers_no_case(travelbot_trace):
    spans = [dict(s) for s in travelbot_trace["spans"]]
    for span in spans:
        if span["type"] == "tool" and span["name"] == "book_flight":
            span["output"] = {**span["output"], "depart_at": "2026-11-06T08:10"}
    client = FakeClient({"spans": spans, "agent_id": "agt_1"}, classify=CLASSIFIED)
    report = IncidentPipeline(client).process("inc-1")
    assert report.causation == [] and client.cases == []


class FlakyClassifier(FakeClient):
    def __init__(self, trace, replies, **kwargs):
        super().__init__(trace, **kwargs)
        self.replies, self.calls = list(replies), 0

    def classify_incident(self, incident_id):
        self.calls += 1
        return self.replies.pop(0)


ERROR_REPLY = {"classification_status": "error", "failure_class": None, "culprit_span_id": None, "diagnosis": {"error": "empty reply"}}


def test_classification_is_retried_once_after_a_classifier_error(travelbot_trace):
    client = FlakyClassifier(travelbot_trace, [ERROR_REPLY, CLASSIFIED])
    report = IncidentPipeline(client).process("inc-1")
    assert client.calls == 2 and report.classification["failure_class"] == "disobey_task_specification"
    assert not any("classification" in n for n in report.notes)


def test_two_classifier_errors_are_reported_and_the_rest_of_the_pipeline_still_runs(travelbot_trace):
    client = FlakyClassifier(travelbot_trace, [ERROR_REPLY, ERROR_REPLY], trust={"band": "standard", "score": 640})
    report = IncidentPipeline(client).process("inc-1")
    assert client.calls == 2 and report.classification is None and "empty reply" in report.notes[0]
    assert set(client.filings) == {"dispute", "claim"}


def test_an_unexpected_exception_in_the_classify_beat_does_not_crash_the_pipeline(travelbot_trace):
    class Broken(FakeClient):
        def classify_incident(self, incident_id):
            raise KeyError("surprise")

    report = IncidentPipeline(Broken(travelbot_trace)).process("inc-1")
    assert report.classification is None and "KeyError" in report.notes[0] and report.dispute is not None
