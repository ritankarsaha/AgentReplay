"""Phase 3 checkpoint: one incident yields classification, causation, a data finding, a dispute,
a claim, a failing-then-passing regression case, scoreboard rows, and a trust score that moves
down then up. Also produces the walkthrough, the SAM 3.1 overlay and a read-only share link.

Starts a throwaway local ingest on SQLite, so run it with the ingest virtualenv:

    ingest/.venv/bin/python -m controlplane.scripts.phase3_check            # live Muse Spark
    ingest/.venv/bin/python -m controlplane.scripts.phase3_check --no-llm   # deterministic parts only
    ingest/.venv/bin/python -m controlplane.scripts.phase3_check --serve    # then keep the ingest up for the viewer
"""



from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv

import agentreplay
from agentreplay import ScopeViolation, _state
from controlplane.blobs import BlobStore
from controlplane.client import ControlPlaneClient, trust_refresher
from controlplane.govern import Monitor, ScopeGuard, generate_keypair
from controlplane.incidents import IncidentPipeline
from controlplane.learn import scoreboard
from controlplane.learn.walkthrough import meta_captioner
from controlplane.learn.incident_case import run_and_report, write_pytest_files
from controlplane.narration import meta_narrator
from controlplane.scripts._local_ingest import LocalIngest
from controlplane.scripts.seed_trust import STAGES
from controlplane.govern.trust import TrustResult, compute_trust
from controlplane.transact import travelbot as tb

API_KEY = "ar_phase3_check_key"
PROJECT_ID = "proj_phase3"
SMS = "Book BLR→CCU Friday morning, under ₹6000."


def _check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'ok' if ok else 'FAIL'}] {label}{': ' + detail if detail else ''}")
    return ok


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-llm", action="store_true", help="skip classification, narration and the scoreboard")
    parser.add_argument("--serve", action="store_true", help="keep the local ingest running afterwards for the viewer")
    parser.add_argument("--owner", default="demo@example.com", help="viewer email that owns the project (with --serve)")
    parser.add_argument("--viewer-token", default="local-viewer-token", help="service token the viewer presents (with --serve)")
    args = parser.parse_args()
    use_llm = not args.no_llm and bool(os.environ.get("META_API_KEY"))
    if not args.no_llm and not use_llm:
        print("META_API_KEY not set; running with --no-llm")

    env = {"AGENTREPLAY_INGEST_VIEWER_SERVICE_TOKEN": args.viewer_token}
    if use_llm:
        env = {
            **env,
            "AGENTREPLAY_INGEST_CLASSIFIER_BACKEND": "meta",
            "AGENTREPLAY_INGEST_META_API_KEY": os.environ["META_API_KEY"],
        }
    ok = []
    with LocalIngest(API_KEY, PROJECT_ID, env, owner_email=args.owner) as ingest:
        client = ControlPlaneClient(API_KEY, ingest.endpoint)
        keypair = generate_keypair()
        manifest = tb.travelbot_manifest(keypair)
        client.register_agent("travelbot", keypair.public_key)
        client.publish_manifest(manifest)
        name, inputs = STAGES[0]
        seeded = compute_trust(**inputs)
        client.record_trust(
            keypair.agent_id,
            TrustResult(seeded.score, seeded.band, seeded.cap_inr, {**seeded.components, "seeded": True}),
            trigger_run_id="seed:pre-demo",
        )
        print(f"trust (seeded, illustrative): {seeded.score} {seeded.band}")

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
        agentreplay.set_tool_guard(guard)
        agentreplay.init(api_key=API_KEY, project_id=PROJECT_ID, endpoint=ingest.endpoint, flush_interval=3600)

        blobs = BlobStore(tempfile.mkdtemp(prefix="phase3_blobs_"))
        bot = tb.TravelBot(blobs=blobs)
        try:
            bot.run(SMS, attempt_fix=True)
        except ScopeViolation as exc:
            print(f"halted: {exc}")
        agentreplay.flush()
        agentreplay.set_tool_guard(None)
        agentreplay.shutdown()
        _state.reset()

        incident = client.list_incidents(agent_id=keypair.agent_id)[0]
        after_incident = client.latest_trust(keypair.agent_id)
        ok.append(_check("trust dropped after the incident", after_incident["score"] < seeded.score, f"{seeded.score} -> {after_incident['score']} ({after_incident['band']})"))

        report = IncidentPipeline(
            client,
            narrator=meta_narrator() if use_llm else None,
            classify=use_llm,
            captioner=meta_captioner() if use_llm else None,
            blobs=blobs,
            annotate=use_llm,
        ).process(incident["id"])

        tags = {c["tag"] for c in report.causation}
        ok.append(_check("causation tags", tags == {"intent_drift", "sponsored", "stale_data"}, ", ".join(sorted(tags))))
        ok.append(_check("data findings", {f["kind"] for f in report.data_findings} == {"stale_doc", "contradiction"}, str(len(report.data_findings))))
        if use_llm:
            c = report.classification or {}
            ok.append(_check("classified by Muse Spark", bool(c.get("failure_class")), f"{c.get('failure_class')} culprit={c.get('culprit_span_id')} usage={c.get('usage')}"))
        dispute, claim = report.dispute, report.claim
        ok.append(_check("dispute packet", bool(dispute) and dispute["transaction"]["amount_inr"] == 5200 and dispute["simulated"], f"{dispute['discrepancy']}" if dispute else ""))
        ok.append(_check("dispute evidence covers intent/sponsored/data_read/purchase", {e["role"] for e in dispute["evidence"]} >= {"intent", "sponsored", "data_read", "purchase"}))
        ok.append(_check("claim premium reflects the trust band", claim["policy"]["trust_band"] == after_incident["band"], f"{claim['policy']['trust_band']} premium INR {claim['policy']['premium_inr']}, payable INR {claim['loss']['payable_inr']}"))
        ok.append(_check("filings stored", {f["type"] for f in client.list_filings(incident["id"])} == {"dispute", "claim"}))
        print("narrative:", dispute["narrative"])

        stored = client.get_incident(incident["id"])["details"]
        ok.append(_check("incident details persisted", {"causation", "data_findings", "classification", "walkthrough"} <= set(stored)))
        walk = report.walkthrough
        ok.append(_check("walkthrough beats", len(walk["beats"]) == 7, f"{walk['captions_by_model']} captions by model; {walk['note'] or 'no note'}"))
        ok.append(_check("screenshot uploaded", len(report.assets) == 1, report.assets[0][:12] if report.assets else ""))
        if use_llm:
            boxes = [b for a in report.annotations for b in a["boxes"]]
            ok.append(_check("SAM 3.1 boxed the departure chip", len(boxes) == 1, str(boxes[0]) if boxes else "; ".join(report.notes)))
        share = client.share_incident(incident["id"])
        ok.append(_check("read-only share link", bool(share), f"/share/{share}"))

        generated = write_pytest_files(incident, report.spans, report.facts, Path(tempfile.mkdtemp(prefix="phase3_tests_")), report.run_id)
        ok.append(_check("pytest file generated", generated.test_path.exists(), str(generated.test_path)))

        case = report.case
        ok.append(_check("regression case registered and active", bool(case) and case["status"] == "active", case["title"] if case else ""))
        red = run_and_report(client, case, version="v1", endpoint=ingest.endpoint, api_key=API_KEY, agent_id=keypair.agent_id)
        green = run_and_report(client, case, version="v2", endpoint=ingest.endpoint, api_key=API_KEY, agent_id=keypair.agent_id)
        ok.append(_check("RED on the broken agent", red["passes"] == 0 and red["blocking"], f"{red['passes']}/{red['trials']} | {red['errors'][:1]}"))
        ok.append(_check("GREEN on the fixed agent", green["passes"] == green["trials"] and not green["blocking"], f"{green['passes']}/{green['trials']}"))
        ok.append(_check("trust moves down on RED and up on GREEN", green["trust"]["score"] > red["trust"]["score"], f"{after_incident['score']} -> {red['trust']['score']} -> {green['trust']['score']} ({green['trust']['band']})"))

        if use_llm:
            task = scoreboard.task_from_facts(report.facts)
            rows = scoreboard.fan_out(task, trials=3)
            runs = client.record_model_runs(scoreboard.to_model_runs(rows, source_run_id=report.run_id, span_id=report.facts.decision["id"]))
            table = scoreboard.aggregate(client.list_model_runs(report.run_id))
            print(scoreboard.render_table(table))
            ok.append(_check("scoreboard rows persisted", len(runs) == len(rows) and len(table) >= 2, f"{len(runs)} model_runs, {sum(r['cost_usd'] or 0 for r in rows):.4f} USD"))

        print("PASS" if all(ok) else "FAIL")
        if args.serve:
            print(f"\nviewer env: INGEST_API_URL={ingest.endpoint} INGEST_SERVICE_TOKEN={args.viewer_token}")
            print(f"owner: {args.owner}  project: {PROJECT_ID}  incident: {incident['id']}  share: /share/{share}")
            print("Ctrl-C to stop.")
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                pass
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
