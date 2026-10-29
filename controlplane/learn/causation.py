"""Deterministic reading of a recorded run: what the user asked, what was bought, and why it went wrong."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from controlplane.govern.identity import canonical_json
from controlplane.transact.choosers import part_of_day
from controlplane.transact.travelbot import parse_sms

INTENT_DRIFT = "intent_drift"
SPONSORED = "sponsored"
STALE_DATA = "stale_data"


def span_hash(span: dict) -> str:
    core = {k: span.get(k) for k in ("id", "type", "name", "input", "output", "fingerprint")}
    return hashlib.sha256(canonical_json(core)).hexdigest()


def trace_hash(spans: List[dict]) -> str:
    ordered = sorted(spans, key=lambda s: s.get("started_at") or "")
    return hashlib.sha256(canonical_json([span_hash(s) for s in ordered])).hexdigest()


def ordered(spans: List[dict]) -> List[dict]:
    return sorted(spans, key=lambda s: s.get("started_at") or "")


def _first(spans: List[dict], **match: str) -> Optional[dict]:
    return next((s for s in ordered(spans) if all(s.get(k) == v for k, v in match.items())), None)


@dataclass
class TraceFacts:
    message: Optional[dict] = None
    intent: Any = None
    search: Optional[dict] = None
    data_read: Optional[dict] = None
    decision: Optional[dict] = None
    negotiations: List[dict] = field(default_factory=list)
    purchase: Optional[dict] = None
    screenshot: Optional[dict] = None
    reference_doc: Optional[dict] = None

    @property
    def booked_depart(self) -> Optional[str]:
        return (self.purchase or {}).get("output", {}).get("depart_at")

    @property
    def mismatch(self) -> bool:
        wanted = getattr(self.intent, "part_of_day", None)
        return bool(self.booked_depart and wanted and part_of_day(self.booked_depart) != wanted)


def extract_facts(spans: List[dict]) -> TraceFacts:
    facts = TraceFacts(
        message=_first(spans, type="message", name="sms.inbound"),
        search=_first(spans, type="tool", name="search_flights"),
        data_read=_first(spans, type="data_read"),
        decision=_first(spans, type="decision"),
        purchase=next(
            (s for s in ordered(spans) if s["type"] == "tool" and s["name"] == "book_flight" and not s.get("error")),
            None,
        ),
        screenshot=_first(spans, type="screenshot"),
        reference_doc=(_first(spans, type="tool", name="read_doc") or {}).get("output"),
        negotiations=[s for s in ordered(spans) if s["type"] == "negotiation"],
    )
    if facts.message:
        facts.intent = parse_sms((facts.message.get("output") or {}).get("body", ""))
    return facts


def tag_causation(facts: TraceFacts) -> List[Dict[str, Any]]:
    """Tags only fire for a purchase that actually contradicts the request."""
    if not facts.mismatch or not facts.decision:
        return []
    chosen = ((facts.decision.get("output") or {}).get("chosen")) or {}
    tags: List[Dict[str, Any]] = []

    if chosen.get("sponsored"):
        tags.append(
            {
                "tag": SPONSORED,
                "summary": f"{chosen['flight']} was a sponsored listing ranked #{chosen.get('rank')} and was considered first.",
                "span_ids": [s["id"] for s in (facts.search, facts.decision) if s],
            }
        )

    if facts.data_read and chosen.get("believed_depart") != chosen.get("listed_depart"):
        read = facts.data_read.get("output") or {}
        if read.get("source_version", 0) < read.get("live_schedule_version", 0):
            tags.append(
                {
                    "tag": STALE_DATA,
                    "summary": (
                        f"The agent believed {chosen['flight']} departs {chosen['believed_depart']} from a document "
                        f"on schedule v{read['source_version']} (live is v{read['live_schedule_version']}); "
                        f"the live listing says {chosen['listed_depart']}."
                    ),
                    "span_ids": [facts.data_read["id"], facts.decision["id"]],
                }
            )

    flex = [
        s
        for s in facts.negotiations
        if any(c["lever"] == "flex_window" for c in (s.get("output") or {}).get("new_concessions", []))
    ]
    if flex:
        tags.append(
            {
                "tag": INTENT_DRIFT,
                "summary": (
                    f"The user asked for a {facts.intent.part_of_day} departure, but the agent conceded a "
                    "Friday 06:00-22:00 flex window, which allows any departure that day."
                ),
                "span_ids": [s["id"] for s in (facts.message, *flex) if s],
            }
        )
    return tags
