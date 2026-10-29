from __future__ import annotations

from controlplane.learn.causation import (
    INTENT_DRIFT,
    SPONSORED,
    STALE_DATA,
    extract_facts,
    span_hash,
    tag_causation,
    trace_hash,
)
from controlplane.learn.datahygiene import find_data_findings


def test_facts_are_read_from_the_trace(travelbot_trace):
    facts = extract_facts(travelbot_trace["spans"])
    assert facts.intent.part_of_day == "morning" and facts.intent.budget_inr == 6000
    assert facts.purchase["output"]["depart_at"].endswith("19:30")
    assert facts.mismatch is True
    assert len(facts.negotiations) == 2
    assert facts.reference_doc["source_version"] == 5


def test_all_three_causes_are_tagged_with_span_references(travelbot_trace):
    spans = travelbot_trace["spans"]
    tags = {t["tag"]: t for t in tag_causation(extract_facts(spans))}
    assert set(tags) == {INTENT_DRIFT, SPONSORED, STALE_DATA}
    ids = {s["id"] for s in spans}
    for tag in tags.values():
        assert tag["span_ids"] and set(tag["span_ids"]) <= ids
    assert "07:30" in tags[STALE_DATA]["summary"] and "19:30" in tags[STALE_DATA]["summary"]
    assert "morning" in tags[INTENT_DRIFT]["summary"]


def test_no_tags_when_the_purchase_matches_the_request(travelbot_trace):
    spans = [dict(s) for s in travelbot_trace["spans"]]
    for span in spans:
        if span["type"] == "tool" and span["name"] == "book_flight":
            span["output"] = {**span["output"], "depart_at": "2026-11-06T08:10"}
    facts = extract_facts(spans)
    assert facts.mismatch is False and tag_causation(facts) == []


def test_data_findings_report_the_stale_doc_and_the_contradiction(travelbot_trace):
    findings = find_data_findings(travelbot_trace["spans"])
    kinds = [f["kind"] for f in findings]
    assert kinds.count("stale_doc") == 1 and kinds.count("contradiction") == 1
    stale = next(f for f in findings if f["kind"] == "stale_doc")
    assert (stale["source_version"], stale["live_schedule_version"]) == (5, 7)
    contradiction = next(f for f in findings if f["kind"] == "contradiction")
    assert (contradiction["document_value"], contradiction["live_value"]) == ("07:30", "19:30")


def test_clean_trace_has_no_data_findings():
    assert find_data_findings([]) == []


def test_hashes_are_stable_order_independent_and_tamper_evident(travelbot_trace):
    spans = travelbot_trace["spans"]
    assert trace_hash(spans) == trace_hash(list(reversed(spans)))
    altered = [dict(s) for s in spans]
    altered[0]["output"] = {"body": "changed"}
    assert trace_hash(altered) != trace_hash(spans)
    assert span_hash(spans[0]) == span_hash(dict(spans[0]))
