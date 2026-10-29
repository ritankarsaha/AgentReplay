from __future__ import annotations

import pytest

from controlplane.learn.causation import extract_facts, tag_causation
from controlplane.transact import filings


def dispute_for(trace, **kwargs):
    spans = trace["spans"]
    facts = extract_facts(spans)
    return filings.build_dispute(
        incident_id="inc-1",
        run_id="run-1",
        agent_id=trace["agent_id"],
        spans=spans,
        facts=facts,
        causation=tag_causation(facts),
        manifest={"agent_id": trace["agent_id"], "version": 1},
        replay_url="https://viewer.test/runs/run-1",
        **kwargs,
    )


def test_dispute_numbers_come_from_the_spans(travelbot_trace):
    packet = dispute_for(travelbot_trace)
    assert packet["type"] == "dispute" and packet["simulated"] is True
    assert packet["transaction"]["amount_inr"] == 5200 and packet["transaction"]["booking_ref"].startswith("SIM")
    assert packet["discrepancy"] == {"expected": "Friday morning", "actual": "Friday 19:30"}
    assert packet["principal_intent"]["span_id"]
    assert packet["requested_remedy"] == "refund"
    assert len(packet["scope_manifest_hash"]) == 64
    assert packet["replay_url"].endswith("/runs/run-1")


def test_dispute_evidence_hashes_match_the_spans(travelbot_trace):
    packet = dispute_for(travelbot_trace)
    by_id = {s["id"]: s for s in travelbot_trace["spans"]}
    roles = {e["role"] for e in packet["evidence"]}
    assert {"intent", "sponsored", "data_read", "decision", "purchase", "negotiation"} <= roles
    from controlplane.learn.causation import span_hash

    assert all(e["hash"] == span_hash(by_id[e["span_id"]]) for e in packet["evidence"])


def test_timeline_is_chronological_and_covers_the_halt(travelbot_trace):
    timeline = filings.build_timeline(travelbot_trace["spans"])
    assert [t["at"] for t in timeline] == sorted(t["at"] for t in timeline)
    assert timeline[0]["type"] == "message" and timeline[-1]["type"] == "alert"
    assert any(t["type"] == "scope_violation" for t in timeline)


def test_template_narrative_states_amount_booking_and_causes(travelbot_trace):
    narrative = dispute_for(travelbot_trace)["narrative"]
    assert "5,200" in narrative and "19:30" in narrative and "sponsored" in narrative and "refund" in narrative


def test_model_narrative_is_used_only_if_it_states_amount_and_booking_ref(travelbot_trace):
    plain = dispute_for(travelbot_trace)
    ref, template = plain["transaction"]["booking_ref"], plain["narrative"]
    good = dispute_for(travelbot_trace, narrator=lambda facts: f"The agent paid ₹5,200 under {ref}, which is wrong.")
    assert good["narrative"].startswith("The agent paid")
    assert dispute_for(travelbot_trace, narrator=lambda facts: "It was a bad purchase.")["narrative"] == template

    def boom(facts):
        raise RuntimeError("model down")

    assert dispute_for(travelbot_trace, narrator=boom)["narrative"] == template


def test_redaction_runs_and_does_not_corrupt_ids_dates_or_hashes(travelbot_trace):
    packet = dispute_for(travelbot_trace, redact=lambda p: filings.scrub_strings({**p, "contact": "call +91 98765 43210 or a@b.com"}))
    assert packet["contact"] == "call [REDACTED] or [REDACTED]"
    clean = filings.default_redact(dispute_for(travelbot_trace))
    assert clean["trace_hash"] == dispute_for(travelbot_trace)["trace_hash"]
    assert clean["timeline"][0]["at"] == dispute_for(travelbot_trace)["timeline"][0]["at"]


def test_default_redact_masks_pii_keys_and_phone_numbers():
    masked = filings.default_redact({"email": "a@b.com", "note": "ring 9876543210 now", "nested": [{"phone": "1"}]})
    assert masked == {"email": "[REDACTED]", "note": "ring [REDACTED] now", "nested": [{"phone": "[REDACTED]"}]}


@pytest.mark.parametrize(
    "band,premium", [("trusted", 160.0), ("standard", 200.0), ("probation", 300.0), ("restricted", 500.0), ("unknown", 500.0)]
)
def test_premium_follows_coverage_rate_and_band_multiplier(band, premium):
    assert filings.premium_inr(band) == premium


def test_claim_premium_reflects_trust_band_and_caps_payout(travelbot_trace):
    dispute = dispute_for(travelbot_trace)
    claim = filings.build_claim(dispute, trust_band="probation", trust_score=536)
    assert claim["type"] == "claim" and claim["simulated"] is True
    assert claim["policy"]["premium_inr"] == 300.0 and claim["policy"]["trust_score"] == 536
    assert claim["loss"] == {"amount_inr": 5200.0, "deductible_inr": 500, "payable_inr": 4700.0}
    assert claim["causation"] == dispute["causation"] and "narrative" not in claim
    assert claim["trace_hash"] == dispute["trace_hash"]
    cheaper = filings.build_claim(dispute, trust_band="trusted", trust_score=720)
    assert cheaper["policy"]["premium_inr"] < claim["policy"]["premium_inr"]
    huge = {**dispute, "transaction": {**dispute["transaction"], "amount_inr": 50_000}}
    assert filings.build_claim(huge, trust_band="standard", trust_score=640)["loss"]["payable_inr"] == filings.COVERAGE_LIMIT_INR


def test_dispute_requires_a_purchase_and_a_request():
    from controlplane.learn.causation import TraceFacts

    with pytest.raises(ValueError):
        filings.build_dispute(
            incident_id="i", run_id="r", agent_id=None, spans=[], facts=TraceFacts(), causation=[], manifest=None, replay_url="x"
        )
