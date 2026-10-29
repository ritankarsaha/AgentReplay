

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

import agentreplay
from agentreplay import ScopeViolation, _state
from controlplane.blobs import BlobStore
from controlplane.client import ControlPlaneClient, trust_refresher
from controlplane.govern import Monitor, ScopeGuard, generate_keypair
from controlplane.incidents import IncidentPipeline
from controlplane.learn import scoreboard
from controlplane.learn.incident_case import run_and_report, write_pytest_files
from controlplane.narration import meta_narrator
from controlplane.scripts._local_ingest import LocalIngest
from controlplane.scripts.seed_trust import STAGES
from controlplane.govern.trust import compute_trust
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
    args = parser.parse_args()
    use_llm = not args.no_llm and bool(os.environ.get("META_API_KEY"))
    if not args.no_llm and not use_llm:
        print("META_API_KEY not set; running with --no-llm")

    env = {}
    if use_llm:
        env = {
            "AGENTREPLAY_INGEST_CLASSIFIER_BACKEND": "meta",
            "AGENTREPLAY_INGEST_META_API_KEY": os.environ["META_API_KEY"],
        }
    ok = []
    with LocalIngest(API_KEY, PROJECT_ID, env) as ingest:
        client = ControlPlaneClient(API_KEY, ingest.endpoint)
        keypair = generate_keypair()
        manifest = tb.travelbot_manifest(keypair)
        client.register_agent("travelbot", keypair.public_key)
        client.publish_manifest(manifest)
        name, inputs = STAGES[0]
        seeded = compute_trust(**inputs)
        client.record_trust(keypair.agent_id, seeded, trigger_run_id="seed:pre-demo")
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

        report = IncidentPipeline(client, narrator=meta_narrator() if use_llm else None, classify=use_llm).process(incident["id"])

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
        ok.append(_check("incident details persisted", {"causation", "data_findings", "classification"} <= set(stored)))

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
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
