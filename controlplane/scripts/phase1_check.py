"""Phase 1 checkpoint: an out-of-scope call is blocked, the run is halted, an incident and
alert are recorded, and `agentreplay replay` reproduces it with zero live tool calls.

Starts a throwaway local ingest API on SQLite (never touches a configured database), so run it
with the ingest virtualenv (it needs FastAPI/uvicorn):

    ingest/.venv/bin/python -m controlplane.scripts.phase1_check
"""

from __future__ import annotations

import hashlib
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

import agentreplay
from agentreplay import ScopeViolation
from controlplane.client import ControlPlaneClient, trust_refresher
from controlplane.govern import Monitor, ScopeGuard, ToolBinding, generate_keypair, sign_manifest
from controlplane.govern.trust import compute_trust

ROOT = Path(__file__).resolve().parents[2]
API_KEY = "ar_phase1_check_key"
PROJECT_ID = "proj_phase1"
LIVE_TOOL_CALLS = {"count": 0}


@agentreplay.tool(name="search_flights")
def search_flights(route):
    LIVE_TOOL_CALLS["count"] += 1
    return [{"flight": "SIM-1", "price_inr": 5200}]


@agentreplay.tool(name="book_flight")
def book_flight(flight, price_inr):
    LIVE_TOOL_CALLS["count"] += 1
    return {"pnr": "SIMPNR", "flight": flight}


@agentreplay.tool(name="wire_money")
def wire_money(amount_inr):
    LIVE_TOOL_CALLS["count"] += 1
    return {"sent": amount_inr}


def scripted_agent() -> None:
    flights = search_flights("DEL-BOM")
    book_flight(flights[0]["flight"], flights[0]["price_inr"])
    wire_money(9000)


def replay_entrypoint() -> None:
    scripted_agent()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start_ingest(db_path: Path, port: int) -> subprocess.Popen:
    env = {
        **os.environ,
        "AGENTREPLAY_INGEST_DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        "AGENTREPLAY_INGEST_ENVIRONMENT": "development",
        "AGENTREPLAY_INGEST_CLASSIFIER_BACKEND": "none",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT / "ingest",
        env=env,
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/docs", timeout=1).status_code == 200:
                return proc
        except httpx.RequestError:
            time.sleep(0.3)
    proc.terminate()
    raise RuntimeError("local ingest did not start")


def _seed_project(db_path: Path) -> None:
    con = sqlite3.connect(db_path)
    con.execute(
        "INSERT INTO projects (id, name, api_key_hash) VALUES (?, ?, ?)",
        (PROJECT_ID, "phase1", hashlib.sha256(API_KEY.encode()).hexdigest()),
    )
    con.commit()
    con.close()


def _check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'ok' if ok else 'FAIL'}] {label}{': ' + detail if detail else ''}")
    return ok


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="phase1_"))
    db_path = tmp / "ingest.db"
    port = _free_port()
    endpoint = f"http://127.0.0.1:{port}"
    server = _start_ingest(db_path, port)
    results = []
    try:
        _seed_project(db_path)
        client = ControlPlaneClient(API_KEY, endpoint)

        keypair = generate_keypair()
        manifest = sign_manifest(
            keypair,
            allowed_tools=["search_flights", "book_flight"],
            constraints={"max_spend_inr": 6000, "max_bookings_per_task": 1, "geography": "domestic"},
        )
        client.register_agent("flight-bot", keypair.public_key)
        client.publish_manifest(manifest)

        baseline = compute_trust(recent_failure_rate=0, regression_pass_rate=1, runs_count=0)
        client.record_trust(keypair.agent_id, baseline)

        monitor = Monitor(sinks=[lambda alert: print(f"    ALERT -> {alert['rule']}: {alert['reason']}")])
        guard = ScopeGuard(
            manifest,
            keypair.public_key,
            bindings={"book_flight": ToolBinding(amount_arg="price_inr", counts_as_booking=True)},
            arg_names={"book_flight": ["flight", "price_inr"]},
            is_revoked=client.revocation_check(keypair.agent_id, manifest.version),
            trust_cap_inr=baseline.cap_inr,
            monitor=monitor,
        )
        monitor.after_halt.append(trust_refresher(client, guard, agentreplay.get_run_id))
        agentreplay.set_tool_guard(guard)

        agentreplay.init(api_key=API_KEY, project_id=PROJECT_ID, endpoint=endpoint, flush_interval=3600)
        run_id = agentreplay.get_run_id()
        raised = None
        try:
            scripted_agent()
        except ScopeViolation as exc:
            raised = exc
        agentreplay.flush()

        results.append(_check("out-of-scope call raised ScopeViolation", raised is not None and raised.rule == "tool_not_allowed", str(raised)))
        results.append(_check("wire_money body never ran", LIVE_TOOL_CALLS["count"] == 2, f"{LIVE_TOOL_CALLS['count']} tool bodies ran (search + book)"))

        headers = {"Authorization": f"Bearer {API_KEY}"}
        run = httpx.get(f"{endpoint}/v1/runs/{run_id}", headers=headers).json()
        types = [s["type"] for s in run["spans"]]
        results.append(_check("run status is halted", run["status"] == "halted", run["status"]))
        results.append(_check("trace has policy, scope_violation and alert spans", {"policy", "scope_violation", "alert"} <= set(types), ",".join(types)))

        incidents = client.list_incidents(agent_id=keypair.agent_id)
        results.append(_check("incident opened", len(incidents) == 1 and incidents[0]["status"] == "open", incidents[0]["kind"] if incidents else ""))

        after = client.latest_trust(keypair.agent_id)
        results.append(_check("trust score dropped after incident", after is not None and after["score"] < baseline.score, f"{baseline.score} -> {after['score'] if after else None} ({after['band'] if after else None})"))
        results.append(_check("guard cap tightened by trust band", guard.effective_cap_inr() <= 6000, f"effective cap {guard.effective_cap_inr()} INR"))

        agentreplay.set_tool_guard(None)
        agentreplay.shutdown()
        from agentreplay.replay import replay_run

        before = LIVE_TOOL_CALLS["count"]
        replayed = None
        try:
            replay_run(run_id, "controlplane.scripts.phase1_check:replay_entrypoint", endpoint=endpoint, api_key=API_KEY)
        except ScopeViolation as exc:
            replayed = exc
        results.append(_check("replay reproduces the violation", replayed is not None and replayed.rule == "tool_not_allowed"))
        results.append(_check("replay made zero live tool calls", LIVE_TOOL_CALLS["count"] == before, f"{LIVE_TOOL_CALLS['count'] - before} live calls"))
    finally:
        server.terminate()
        server.wait(timeout=10)

    print("PASS" if all(results) else "FAIL")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
