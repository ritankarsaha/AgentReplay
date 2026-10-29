"""Live monitor and kill switch

On a guard denial (scope violation or spend-gate breach) the monitor:
  1. halts the guard, so every later tool call is denied and in-flight async
     tools are cancelled,
  2. delivers the alert (webhook and/or callbacks; failures never block the halt),
  3. records an `alert` span named `agentreplay.halt` and flushes it,
  4. runs `after_halt` callbacks (e.g. a trust-score refresh) once the incident is ingested.

The ingest API recognizes that span, marks the run `halted` and opens an
incident row. Wire contract: ALERT_SPAN_TYPE / HALT_SPAN_NAME must match
`ingest/app/crud.py`.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx

from agentreplay import _state
from agentreplay.collector import get_collector
from agentreplay.fingerprint import compute_fingerprint
from agentreplay.guard import GuardDecision
from agentreplay.span import Span

ALERT_SPAN_TYPE = "alert"
HALT_SPAN_NAME = "agentreplay.halt"
WEBHOOK_TIMEOUT_S = 3.0

AlertSink = Callable[[dict], None]


class Monitor:
    def __init__(
        self,
        *,
        webhook_url: Optional[str] = None,
        sinks: Optional[List[AlertSink]] = None,
        after_halt: Optional[List[AlertSink]] = None,
        severity: str = "high",
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self.webhook_url = webhook_url
        self.sinks = list(sinks or [])
        self.after_halt = list(after_halt or [])
        self.severity = severity
        self._http = http_client
        self._guard: Any = None
        self.alerts: List[dict] = []

    def attach(self, guard: Any) -> None:
        self._guard = guard

    def on_violation(self, tool_name: str, decision: GuardDecision, culprit_span_id: Optional[str]) -> None:
        if self._guard is not None:
            self._guard.halt()

        agent_id = decision.details.get("agent_id")
        alert = {
            "kind": "scope_violation" if decision.rule not in ("spend_cap", "approval_required") else "spend_gate",
            "severity": self.severity,
            "agent_id": agent_id,
            "tool": tool_name,
            "rule": decision.rule,
            "reason": decision.reason,
            "culprit_span_id": culprit_span_id,
            "halted_at": datetime.now(timezone.utc).isoformat(),
        }
        delivery = self._deliver(alert)
        self.alerts.append({**alert, "delivery": delivery})
        self._record(alert, delivery)
        for callback in self.after_halt:
            try:
                callback(alert)
            except Exception:
                print("agentreplay: after_halt callback failed", file=sys.stderr)

    def _deliver(self, alert: dict) -> Dict[str, Any]:
        delivery: Dict[str, Any] = {}
        if self.webhook_url:
            try:
                client = self._http or httpx.Client(timeout=WEBHOOK_TIMEOUT_S)
                try:
                    response = client.post(self.webhook_url, json=alert)
                finally:
                    if self._http is None:
                        client.close()
                delivery["webhook"] = {"ok": response.status_code < 400, "status": response.status_code}
            except Exception as exc:
                delivery["webhook"] = {"ok": False, "error": type(exc).__name__}
        for index, sink in enumerate(self.sinks):
            try:
                sink(alert)
                delivery[f"sink_{index}"] = {"ok": True}
            except Exception as exc:
                delivery[f"sink_{index}"] = {"ok": False, "error": type(exc).__name__}
        return delivery

    def _record(self, alert: dict, delivery: dict) -> None:
        if not (_state.is_initialized() and _state.get_config().enabled):
            return
        try:
            payload = dict(alert)
            span = Span(
                id=str(uuid.uuid4()),
                run_id=_state.get_run_id(),
                parent_id=None,
                type=ALERT_SPAN_TYPE,
                name=HALT_SPAN_NAME,
                input=payload,
                output={"delivery": delivery},
                error=None,
                started_at=datetime.now(timezone.utc),
                duration_ms=0.0,
                fingerprint=compute_fingerprint({"halt": alert["culprit_span_id"], "rule": alert["rule"]}),
            )
            get_collector().add(span)
            exporter = _state.get_exporter()
            if exporter is not None:
                exporter.flush()
        except Exception:
            print("agentreplay: failed to record halt alert", file=sys.stderr)
