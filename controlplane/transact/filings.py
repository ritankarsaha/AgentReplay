"""Dispute and insurance-claim packets. Every number and field comes from spans; the model only
writes the narrative. Both are simulated filings and are labeled as such."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, Dict, List, Optional

from agentreplay.redaction import redact_pii
from controlplane.govern.identity import canonical_json
from controlplane.learn.causation import TraceFacts, ordered, span_hash, trace_hash

MERCHANT = "Simulated airline (sandbox)"
COVERAGE_LIMIT_INR = 10_000
DEDUCTIBLE_INR = 500
BASE_RATE = 0.02
BAND_MULTIPLIER = {"trusted": 0.8, "standard": 1.0, "probation": 1.5, "restricted": 2.5}

_PHONE = re.compile(r"(?<![\w.:-])(?:\+\d[\d\s-]{8,}\d|\d{10,15})(?![\w])")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")

Narrator = Callable[[Dict[str, Any]], str]
Redactor = Callable[[dict], dict]


def scrub_strings(value: Any) -> Any:
    if isinstance(value, str):
        return _EMAIL.sub("[REDACTED]", _PHONE.sub("[REDACTED]", value))
    if isinstance(value, dict):
        return {k: scrub_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_strings(v) for v in value]
    return value


def default_redact(packet: dict) -> dict:
    return scrub_strings(redact_pii(packet))


def premium_inr(trust_band: str) -> float:
    multiplier = BAND_MULTIPLIER.get(trust_band, BAND_MULTIPLIER["restricted"])
    return round(COVERAGE_LIMIT_INR * BASE_RATE * multiplier, 2)


def _summary(span: dict) -> str:
    out, inp = span.get("output") or {}, span.get("input") or {}
    kind = span["type"]
    if kind == "message":
        return f"{out.get('direction', '')} SMS: {out.get('body', '')}"
    if kind == "tool" and span["name"] == "book_flight":
        return f"booked {out.get('flight')} departing {str(out.get('depart_at', ''))[-5:]} for INR {out.get('price_inr')}"
    if kind == "tool":
        return f"tool {span['name']}"
    if kind == "data_read":
        return f"read {out.get('doc_id')} (schedule v{out.get('source_version')}, live v{out.get('live_schedule_version')})"
    if kind == "decision":
        chosen = out.get("chosen") or {}
        return f"chose {chosen.get('flight')} (sponsored={chosen.get('sponsored')}, believed departure {chosen.get('believed_depart')})"
    if kind == "negotiation":
        return f"round {inp.get('round')}: {out.get('status')} at INR {out.get('price_inr')} with {out.get('accepted_levers')}"
    if kind == "scope_violation":
        return f"blocked {span['name']}: {(out.get('rule'))}"
    if kind == "alert":
        return f"run halted: {inp.get('reason', inp.get('rule', ''))}"
    return span["name"]


_TIMELINE_TYPES = {"message", "data_read", "decision", "negotiation", "screenshot", "scope_violation", "alert"}


def build_timeline(spans: List[dict]) -> List[Dict[str, Any]]:
    keep = [s for s in ordered(spans) if s["type"] in _TIMELINE_TYPES or (s["type"] == "tool" and s["name"] in ("search_flights", "book_flight"))]
    return [{"at": s.get("started_at"), "span_id": s["id"], "type": s["type"], "name": s["name"], "summary": _summary(s)} for s in keep]


def _evidence(facts: TraceFacts, spans: List[dict]) -> List[Dict[str, Any]]:
    roles = [
        ("intent", facts.message),
        ("sponsored", facts.search),
        ("data_read", facts.data_read),
        ("decision", facts.decision),
        ("purchase", facts.purchase),
    ]
    rows = [{"span_id": s["id"], "hash": span_hash(s), "role": role} for role, s in roles if s]
    rows += [{"span_id": s["id"], "hash": span_hash(s), "role": "negotiation"} for s in facts.negotiations]
    return rows


def template_narrative(facts: Dict[str, Any]) -> str:
    tx, disc = facts["transaction"], facts["discrepancy"]
    causes = "; ".join(c["summary"] for c in facts["causation"]) or "no contributing factor was identified"
    return (
        f"The principal asked for {disc['expected']} (\"{facts['principal_intent']['text']}\"). The agent booked "
        f"{tx['flight']} departing {disc['actual']} for INR {tx['amount_inr']:,.0f} (booking {tx['booking_ref']}). "
        f"Contributing factors: {causes} The principal requests a {facts['requested_remedy']}."
    )


def _narrate(facts: Dict[str, Any], narrator: Optional[Narrator]) -> str:
    fallback = template_narrative(facts)
    if narrator is None:
        return fallback
    try:
        text = narrator(facts)
    except Exception:
        return fallback
    amount = f"{facts['transaction']['amount_inr']:,.0f}"
    required = (amount, str(facts["transaction"]["booking_ref"]))
    return text if text and all(item in text.replace("₹", "") for item in required) else fallback


def build_dispute(
    *,
    incident_id: str,
    run_id: str,
    agent_id: Optional[str],
    spans: List[dict],
    facts: TraceFacts,
    causation: List[Dict[str, Any]],
    manifest: Optional[dict],
    replay_url: str,
    narrator: Optional[Narrator] = None,
    redact: Redactor = default_redact,
) -> dict:
    if facts.purchase is None or facts.message is None:
        raise ValueError("trace has no purchase or no inbound request to dispute")
    out = facts.purchase["output"]
    wanted = facts.intent.part_of_day or "any time"
    packet: Dict[str, Any] = {
        "type": "dispute",
        "simulated": True,
        "incident_id": incident_id,
        "run_id": run_id,
        "agent_id": agent_id,
        "principal_intent": {"text": facts.message["output"]["body"], "span_id": facts.message["id"]},
        "scope_manifest_hash": hashlib.sha256(canonical_json(manifest)).hexdigest() if manifest else None,
        "transaction": {
            "merchant": MERCHANT,
            "flight": out["flight"],
            "amount_inr": out["price_inr"],
            "booking_ref": out["pnr"],
        },
        "discrepancy": {
            "expected": f"{facts.intent.weekday} {wanted}",
            "actual": f"{facts.intent.weekday} {out['depart_at'][-5:]}",
        },
        "evidence": _evidence(facts, spans),
        "timeline": build_timeline(spans),
        "causation": causation,
        "requested_remedy": "refund",
        "trace_hash": trace_hash(spans),
        "replay_url": replay_url,
    }
    packet["narrative"] = _narrate(packet, narrator)
    return redact(packet)


def build_claim(
    dispute: dict,
    *,
    trust_band: str,
    trust_score: Optional[int],
    redact: Redactor = default_redact,
) -> dict:
    amount = float(dispute["transaction"]["amount_inr"])
    payable = round(min(max(amount - DEDUCTIBLE_INR, 0.0), COVERAGE_LIMIT_INR), 2)
    claim = {
        **{k: v for k, v in dispute.items() if k not in ("type", "narrative", "requested_remedy")},
        "type": "claim",
        "policy": {
            "coverage_limit": COVERAGE_LIMIT_INR,
            "deductible": DEDUCTIBLE_INR,
            "base_rate": BASE_RATE,
            "trust_band": trust_band,
            "trust_score": trust_score,
            "band_multiplier": BAND_MULTIPLIER.get(trust_band, BAND_MULTIPLIER["restricted"]),
            "premium_inr": premium_inr(trust_band),
        },
        "loss": {"amount_inr": amount, "deductible_inr": DEDUCTIBLE_INR, "payable_inr": payable},
        "dispute_narrative": dispute.get("narrative"),
    }
    return redact(claim)
