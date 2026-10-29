"""The whole demo story as one function: beats 1-10, from SMS to scoreboard, on a cold start.

Every network-dependent beat goes through the cassette, so the same flow runs live, records a
fresh cassette, replays one with no network at all, or runs live with the recording as a fallback.
"""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import agentreplay
from agentreplay import ScopeViolation, _state
from agentreplay.collector import get_collector
from controlplane import cassette as cassette_mod
from controlplane import ledger
from controlplane.blobs import BlobStore
from controlplane.client import ControlPlaneClient, HttpTokenStore, trust_refresher
from controlplane.govern import Monitor, ScopeGuard, generate_keypair
from controlplane.govern.broker import AccessDenied, Broker
from controlplane.govern.trust import TrustResult, compute_trust
from controlplane.incidents import IncidentPipeline
from controlplane.learn import scoreboard
from controlplane.learn.incident_case import run_and_report, write_pytest_files
from controlplane.learn.walkthrough import meta_captioner
from controlplane.narration import meta_narrator
from controlplane.scripts.seed_trust import STAGES
from controlplane.transact import filings
from controlplane.transact import travelbot as tb
from controlplane.transact.negotiator import MetaBuyer, ScriptedBuyer

API_KEY = "ar_demo_key"
PROJECT_ID = "proj_demo"
SMS = "Book BLR→CCU Friday morning, under ₹6000."
DEFAULT_CASSETTE = "controlplane/cassettes/demo.json"
BEATS = {
    1: "Register TravelBot: signed identity, scope, sandbox tokens",
    2: "SMS arrives: span #1",
    3: "Trust score sets the spend cap",
    4: "Search results carry a sponsored flag",
    5: "Negotiation: 5,900 to 5,200 via concessions",
    6: "Wrong purchase",
    7: "Second ticket: scope violation, halt, alert",
    8: "Incident pipeline: classification, filings, walkthrough",
    9: "Regression test RED then GREEN; trust down then up",
    10: "Model scoreboard",
}


@dataclass
class Check:
    beat: int
    label: str
    ok: bool
    detail: str = ""


@dataclass
class DemoOptions:
    mode: str = "live"
    cassette_path: str = DEFAULT_CASSETTE
    buyer: str = "scripted"
    llm: bool = True
    viewer_token: str = "local-viewer-token"
    owner: str = "demo@example.com"


@dataclass
class DemoResult:
    checks: List[Check] = field(default_factory=list)
    outcomes: Dict[str, Any] = field(default_factory=dict)
    llm_outcomes: Dict[str, Any] = field(default_factory=dict)
    timings: Dict[str, float] = field(default_factory=dict)
    spend: Dict[str, Any] = field(default_factory=dict)
    cassette: Dict[str, Any] = field(default_factory=dict)
    incident_id: Optional[str] = None
    share_token: Optional[str] = None
    narrative: str = ""
    scoreboard_table: str = ""

    @property
    def clean(self) -> bool:
        return all(c.ok for c in self.checks)


def ingest_env(options: DemoOptions) -> Dict[str, str]:
    """Env for the throwaway ingest: the viewer token, and the live classifier when a key may be used."""
    env = {"AGENTREPLAY_INGEST_VIEWER_SERVICE_TOKEN": options.viewer_token}
    if options.llm and options.mode != "replay" and os.environ.get("META_API_KEY"):
        env["AGENTREPLAY_INGEST_CLASSIFIER_BACKEND"] = "meta"
        env["AGENTREPLAY_INGEST_META_API_KEY"] = os.environ["META_API_KEY"]
    return env


def _reset_process_state() -> None:
    agentreplay.set_tool_guard(None)
    _state.reset()
    get_collector().clear()


def run_demo(
    ingest: Any, options: DemoOptions, say: Callable[[str], None] = print
) -> DemoResult:
    result = DemoResult()
    _reset_process_state()
    cas = cassette_mod.Cassette(options.cassette_path, options.mode)
    spend_before = len(ledger.LEDGER.entries)
    clock = time.perf_counter

    def check(beat: int, label: str, ok: bool, detail: str = "") -> bool:
        result.checks.append(Check(beat, label, bool(ok), detail))
        say(f"[{'ok' if ok else 'FAIL'}] beat {beat:>2} {label}{': ' + detail if detail else ''}")
        return ok

    with cassette_mod.use(cas):
        client = ControlPlaneClient(API_KEY, ingest.endpoint)

        t0 = clock()
        keypair = generate_keypair()
        manifest = tb.travelbot_manifest(keypair)
        client.register_agent("travelbot", keypair.public_key)
        published = client.publish_manifest(manifest)
        broker = Broker(HttpTokenStore(client))
        airline = broker.issue(keypair.agent_id, "airline", ["search", "book"])
        card = broker.issue(keypair.agent_id, "card", ["charge"])
        broker.revoke(card.token)
        try:
            broker.authorize(card.token, "card", "charge")
            revoked_denied = False
        except AccessDenied as exc:
            revoked_denied = exc.rule == "token_revoked"
        check(1, "manifest signature verified by ingest and tokens issued", published["version"] == 1 and bool(airline.token), f"agent {keypair.agent_id}")
        check(1, "revoked token is refused", revoked_denied)

        _, seed_inputs = STAGES[0]
        seeded = compute_trust(**seed_inputs)
        client.record_trust(
            keypair.agent_id,
            TrustResult(seeded.score, seeded.band, seeded.cap_inr, {**seeded.components, "seeded": True}),
            trigger_run_id="seed:pre-demo",
        )
        monitor = Monitor()
        guard = ScopeGuard(
            manifest,
            keypair.public_key,
            bindings=tb.BINDINGS,
            arg_names=tb.ARG_NAMES,
            is_revoked=client.revocation_check(keypair.agent_id, manifest.version),
            trust_cap_inr=seeded.cap_inr,
            monitor=monitor,
        )
        monitor.after_halt.append(trust_refresher(client, guard, agentreplay.get_run_id))
        check(3, "trust sets the spend cap", guard.effective_cap_inr() == 6000, f"{seeded.score} {seeded.band} (seeded, illustrative): cap INR {guard.effective_cap_inr():.0f}")

        agentreplay.set_tool_guard(guard)
        agentreplay.init(api_key=API_KEY, project_id=PROJECT_ID, endpoint=ingest.endpoint, flush_interval=3600)
        blobs = BlobStore(tempfile.mkdtemp(prefix="demo_blobs_"))
        buyer = MetaBuyer() if options.buyer == "meta" else ScriptedBuyer()
        bot = tb.TravelBot(buyer=buyer, blobs=blobs)
        booked, violation = None, None
        try:
            bot.run(SMS, attempt_fix=True)
        except ScopeViolation as exc:
            violation = exc
        agentreplay.flush()
        agentreplay.set_tool_guard(None)
        agentreplay.shutdown()
        _state.reset()
        result.timings["agent"] = clock() - t0

        incident = client.list_incidents(agent_id=keypair.agent_id)[0]
        run = client.get_run(incident["run_id"])
        spans = sorted(run["spans"], key=lambda s: s["started_at"])
        booking = next((s["output"] for s in spans if s["type"] == "tool" and s["name"] == "book_flight" and not s.get("error")), None)
        negotiations = [s for s in spans if s["type"] == "negotiation"]
        search = next((s for s in spans if s["type"] == "tool" and s["name"] == "search_flights"), None)
        booked = booking

        check(2, "inbound SMS is the first span", spans[0]["type"] == "message" and spans[0]["name"] == "sms.inbound")
        check(4, "sponsored flag recorded on the search span", bool(search) and any(r["sponsored"] for r in search["output"]["results"]))
        final = negotiations[-1]["output"] if negotiations else {}
        check(5, "negotiated 5,900 to 5,200 with a span per offer", final.get("list_price_inr") == 5900 and final.get("price_inr") == 5200 and len(negotiations) == 2, f"{len(negotiations)} negotiation spans, conceded {final.get('accepted_levers')}")
        check(6, "booked the wrong flight", bool(booked) and booked["depart_at"].endswith("19:30"), f"{booked['flight']} at {booked['depart_at'][-5:]} for INR {booked['price_inr']:.0f}" if booked else "no booking")
        check(7, "second ticket blocked and the run halted", violation is not None and violation.rule == "max_bookings" and run["status"] == "halted", f"rule {getattr(violation, 'rule', None)}, run {run['status']}")
        check(7, "alert span and incident recorded", any(s["type"] == "alert" for s in spans) and incident["status"] == "open")
        after_incident = client.latest_trust(keypair.agent_id)
        check(7, "trust dropped after the incident", after_incident["score"] < seeded.score, f"{seeded.score} -> {after_incident['score']} ({after_incident['band']})")

        t1 = clock()
        use_llm = options.llm
        report = IncidentPipeline(
            client,
            narrator=meta_narrator() if use_llm else None,
            classify=use_llm,
            captioner=meta_captioner() if use_llm else None,
            blobs=blobs,
            annotate=use_llm,
        ).process(incident["id"])
        result.timings["pipeline"] = clock() - t1

        tags = sorted(c["tag"] for c in report.causation)
        check(8, "causation: intent drift, sponsored influence, stale data", tags == ["intent_drift", "sponsored", "stale_data"], ", ".join(tags))
        check(8, "data findings: stale document and contradiction", sorted(f["kind"] for f in report.data_findings) == ["contradiction", "stale_doc"])
        if use_llm:
            c = report.classification or {}
            check(8, "classified (MAST)", bool(c.get("failure_class")), f"{c.get('failure_class')} by {c.get('model')}")
        dispute, claim = report.dispute, report.claim
        check(8, "dispute packet from the spans", bool(dispute) and dispute["transaction"]["amount_inr"] == 5200 and dispute["simulated"], str(dispute["discrepancy"]) if dispute else "")
        check(8, "claim premium follows the trust band", bool(claim) and claim["policy"]["trust_band"] == after_incident["band"], f"{claim['policy']['trust_band']}: premium INR {claim['policy']['premium_inr']}, payable INR {claim['loss']['payable_inr']}" if claim else "")
        check(8, "both filings stored", {f["type"] for f in client.list_filings(incident["id"])} == {"dispute", "claim"})
        check(8, "walkthrough has 7 beats", len(report.walkthrough["beats"]) == 7, f"{report.walkthrough['captions_by_model']} captions by model" + (f"; {report.walkthrough['note']}" if report.walkthrough["note"] else ""))
        if use_llm:
            written = report.walkthrough["captions_by_model"]
            check(8, "walkthrough captions written by the model", written >= len(report.walkthrough["beats"]) // 2, f"{written} of {len(report.walkthrough['beats'])}")
            check(8, "dispute narrative written by the model", bool(dispute) and dispute["narrative"] != filings.template_narrative(dispute))
        check(8, "screenshot uploaded", len(report.assets) == 1)
        boxes = [b for a in report.annotations for b in a["boxes"]]
        if use_llm:
            check(8, "SAM 3.1 boxed the departure chip", len(boxes) == 1, str(boxes[0]) if boxes else "; ".join(report.notes))
        share = client.share_incident(incident["id"])
        check(8, "read-only share link created", bool(share))
        result.share_token, result.incident_id = share, incident["id"]
        result.narrative = (dispute or {}).get("narrative", "")

        generated = write_pytest_files(incident, report.spans, report.facts, Path(tempfile.mkdtemp(prefix="demo_tests_")), report.run_id)
        case = report.case
        check(9, "regression case registered and active", bool(case) and case["status"] == "active")
        check(9, "pytest file generated", generated.test_path.exists())
        t2 = clock()
        red = run_and_report(client, case, version="v1", endpoint=ingest.endpoint, api_key=API_KEY, agent_id=keypair.agent_id)
        green = run_and_report(client, case, version="v2", endpoint=ingest.endpoint, api_key=API_KEY, agent_id=keypair.agent_id)
        result.timings["regression"] = clock() - t2
        check(9, "RED on the broken agent", red["passes"] == 0 and red["blocking"], f"{red['passes']}/{red['trials']}")
        check(9, "GREEN on the fixed agent", green["passes"] == green["trials"] and not green["blocking"], f"{green['passes']}/{green['trials']}")
        trust_path = [seeded.score, after_incident["score"], red["trust"]["score"], green["trust"]["score"]]
        check(9, "trust moves down on RED and up on GREEN", green["trust"]["score"] > red["trust"]["score"] and red["trust"]["score"] < after_incident["score"], " -> ".join(map(str, trust_path)))

        rows: List[Dict[str, Any]] = []
        if use_llm:
            t3 = clock()
            rows = scoreboard.fan_out(scoreboard.task_from_facts(report.facts), trials=3)
            saved = client.record_model_runs(scoreboard.to_model_runs(rows, source_run_id=report.run_id, span_id=report.facts.decision["id"]))
            table = scoreboard.aggregate(client.list_model_runs(report.run_id))
            result.timings["scoreboard"] = clock() - t3
            result.scoreboard_table = scoreboard.render_table(table)
            check(10, "scoreboard rows persisted", len(saved) == len(rows) and len(table) >= 2, f"{len(saved)} rows across {len(table)} models")
            result.llm_outcomes["scoreboard"] = {r["model"]: [r["repeats_mistake"], r["correct"], r["errors"]] for r in table}
        result.llm_outcomes["classification"] = (report.classification or {}).get("failure_class")
        result.llm_outcomes["boxes"] = boxes

    if options.mode == "record":
        cas.save()
    result.cassette = cas.stats()
    new_entries = ledger.LEDGER.entries[spend_before:]
    priced = [e.cost_usd for e in new_entries if e.cost_usd is not None]
    result.spend = {"calls": len(new_entries), "unpriced_calls": len(new_entries) - len(priced), "cost_usd": round(sum(priced), 6)}
    if options.mode == "replay":
        check(0, "replay made no live calls and missed no slot", not result.spend["calls"] and not cas.misses, f"{len(cas.hits)} recorded beats served" + (f"; drift in {cas.drift}" if cas.drift else ""))
    result.outcomes = {
        "flight": booked["flight"] if booked else None,
        "price_inr": booked["price_inr"] if booked else None,
        "depart_at": booked["depart_at"] if booked else None,
        "booking_ref": booked["pnr"] if booked else None,
        "halt_rule": getattr(violation, "rule", None),
        "causation": tags,
        "data_findings": len(report.data_findings),
        "premium_inr": claim["policy"]["premium_inr"] if claim else None,
        "payable_inr": claim["loss"]["payable_inr"] if claim else None,
        "regression": [red["passes"], green["passes"]],
        "trust": trust_path,
    }
    return result
