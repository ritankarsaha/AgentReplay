"""Incident orchestrator: one halted or failed run in, classification + causation + data findings
+ dispute + claim + regression case out."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from controlplane import cassette, ledger
from controlplane.blobs import BlobStore
from controlplane.client import ControlPlaneClient, ControlPlaneError
from controlplane.learn.causation import TraceFacts, extract_facts, tag_causation
from controlplane.learn.datahygiene import find_data_findings
from controlplane.learn import vision
from controlplane.learn.incident_case import register_case
from controlplane.learn.walkthrough import Captioner, build_walkthrough
from controlplane.transact.filings import Narrator, Redactor, build_claim, build_dispute, default_redact

CLASSIFY_ATTEMPTS = 2


@dataclass
class IncidentReport:
    incident_id: str
    run_id: str
    agent_id: Optional[str]
    classification: Optional[Dict[str, Any]] = None
    causation: List[Dict[str, Any]] = field(default_factory=list)
    data_findings: List[Dict[str, Any]] = field(default_factory=list)
    culprit_span_id: Optional[str] = None
    dispute: Optional[dict] = None
    claim: Optional[dict] = None
    case: Optional[dict] = None
    walkthrough: Optional[Dict[str, Any]] = None
    annotations: List[Dict[str, Any]] = field(default_factory=list)
    assets: List[str] = field(default_factory=list)
    facts: Optional[TraceFacts] = None
    spans: List[dict] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def _manifest_version(spans: List[dict]) -> Optional[int]:
    for span in spans:
        if span["type"] == "policy":
            version = ((span.get("output") or {}).get("details") or {}).get("manifest_version")
            if version is not None:
                return int(version)
    return None


class IncidentPipeline:
    def __init__(
        self,
        client: ControlPlaneClient,
        *,
        viewer_url: str = "https://www.agentreplay.space",
        narrator: Optional[Narrator] = None,
        redact: Redactor = default_redact,
        classify: bool = True,
        register_regression_case: bool = True,
        captioner: Optional[Captioner] = None,
        blobs: Optional[BlobStore] = None,
        annotate: bool = False,
        segment: Callable[[bytes], Dict[str, Any]] = vision.segment,
    ) -> None:
        self.client = client
        self.viewer_url = viewer_url.rstrip("/")
        self.narrator = narrator
        self.redact = redact
        self.classify = classify
        self.register_regression_case = register_regression_case
        self.captioner = captioner
        self.blobs = blobs or BlobStore()
        self.annotate = annotate
        self.segment = segment

    def process(self, incident_id: str) -> IncidentReport:
        incident = self.client.get_incident(incident_id)
        run = self.client.get_run(incident["run_id"])
        spans = run["spans"]
        report = IncidentReport(incident_id, incident["run_id"], incident.get("agent_id"), spans=spans)

        if self.classify:
            try:
                classified = cassette.run(
                    "classify",
                    {"kind": "classify"},
                    lambda: self._classify_live(incident_id),
                    valid=lambda reply: reply.get("classification_status") == "done",
                )
                if classified["classification_status"] != "done":
                    error = (classified.get("diagnosis") or {}).get("error")
                    raise ControlPlaneError(f"classifier returned {classified['classification_status']}: {error}")
                report.classification = {
                    "failure_class": classified["failure_class"],
                    "culprit_span_id": classified["culprit_span_id"],
                    "diagnosis": (classified.get("diagnosis") or {}).get("text"),
                    "model": (classified.get("diagnosis") or {}).get("model"),
                    "backend": (classified.get("diagnosis") or {}).get("backend"),
                    "usage": (classified.get("diagnosis") or {}).get("usage"),
                }
            except Exception as exc:
                report.notes.append(f"classification unavailable: {type(exc).__name__}: {exc}")

        try:
            report.facts = extract_facts(spans)
        except ValueError as exc:
            report.notes.append(f"trace has no readable request: {exc}")
            self._store_details(report)
            return report

        facts = report.facts
        report.causation = tag_causation(facts)
        report.data_findings = find_data_findings(spans)
        report.culprit_span_id = (
            (report.classification or {}).get("culprit_span_id")
            or incident.get("culprit_span_id")
            or (facts.purchase or {}).get("id")
        )
        self._visuals(report)
        report.walkthrough = build_walkthrough(spans, facts, captioner=self.captioner)
        self._store_details(report)

        if facts.purchase and facts.message:
            self._file(report, incident)
            if self.register_regression_case and facts.mismatch:
                report.case = register_case(
                    self.client,
                    incident=incident,
                    facts=facts,
                    spans=spans,
                    classification=report.classification,
                )
        else:
            report.notes.append("no purchase in the trace; filings skipped")
        return report

    def _classify_live(self, incident_id: str) -> dict:
        """Classify, retrying once after a classifier error (ingest re-runs anything not `done`)."""
        classified: dict = {}
        for _ in range(CLASSIFY_ATTEMPTS):
            classified = self.client.classify_incident(incident_id)
            usage = (classified.get("diagnosis") or {}).get("usage")
            if usage:
                ledger.LEDGER.record("muse-spark-classifier", usage, cost=usage.get("cost_usd"))
            if classified.get("classification_status") == "done":
                break
        return classified

    def _store_details(self, report: IncidentReport) -> None:
        self.client.merge_incident_details(
            report.incident_id,
            {
                "classification": report.classification,
                "causation": report.causation,
                "data_findings": report.data_findings,
                "culprit_span_id": report.culprit_span_id,
                "walkthrough": report.walkthrough,
                "annotations": report.annotations,
                "assets": report.assets,
                "notes": report.notes,
            },
        )

    def _visuals(self, report: IncidentReport) -> None:
        """Upload the booking screenshot and, if asked, box the departure chip with SAM 3.1."""
        shot = ((report.facts.screenshot or {}).get("output") or {}).get("image")
        if not shot:
            return
        png = self.blobs.get(shot["sha256"])
        if png is None:
            report.notes.append("screenshot blob not found locally; not uploaded")
            return
        try:
            ref = self.client.put_blob(png, shot["mime"])
        except ControlPlaneError as exc:
            report.notes.append(f"screenshot upload failed: {exc}")
            return
        report.assets.append(ref["sha256"])
        if not self.annotate:
            return
        try:
            result = self.segment(png)
        except Exception as exc:
            report.notes.append(f"SAM 3.1 segmentation failed: {type(exc).__name__}: {exc}"[:200])
            return
        report.annotations.append(
            {
                "span_id": report.facts.screenshot["id"],
                "sha256": ref["sha256"],
                "model": result["model"],
                "prompt": result["prompt"],
                "boxes": result["boxes"],
            }
        )

    def _file(self, report: IncidentReport, incident: dict) -> None:
        manifest = None
        version = _manifest_version(report.spans)
        if report.agent_id and version is not None:
            manifest = self.client.manifest_version(report.agent_id, version)
        report.dispute = build_dispute(
            incident_id=report.incident_id,
            run_id=report.run_id,
            agent_id=report.agent_id,
            spans=report.spans,
            facts=report.facts,
            causation=report.causation,
            manifest=manifest,
            replay_url=f"{self.viewer_url}/runs/{report.run_id}",
            narrator=self.narrator,
            redact=self.redact,
        )
        self.client.put_filing(report.incident_id, report.dispute)

        trust = self.client.latest_trust(report.agent_id) if report.agent_id else None
        if trust is None:
            report.notes.append("no trust score on record; claim filed at the restricted band")
        report.claim = build_claim(
            report.dispute,
            trust_band=(trust or {}).get("band", "restricted"),
            trust_score=(trust or {}).get("score"),
            redact=self.redact,
        )
        self.client.put_filing(report.incident_id, report.claim)
