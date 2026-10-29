"""Data-hygiene findings from `data_read` and `decision` spans: stale documents and facts that
contradict live data. Pure comparison of recorded values; no model involved."""

from __future__ import annotations

from typing import Any, Dict, List

from controlplane.learn.causation import ordered


def find_data_findings(spans: List[dict]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    reads = [s for s in ordered(spans) if s["type"] == "data_read"]
    for span in reads:
        out = span.get("output") or {}
        if out.get("source_version", 0) < out.get("live_schedule_version", 0):
            findings.append(
                {
                    "kind": "stale_doc",
                    "doc_id": out["doc_id"],
                    "doc_updated_at": out["doc_updated_at"],
                    "source_version": out["source_version"],
                    "live_schedule_version": out["live_schedule_version"],
                    "span_ids": [span["id"]],
                    "action": f"Refresh {out['doc_id']} to schedule v{out['live_schedule_version']} before the agent reads it.",
                }
            )

    for span in ordered(spans):
        if span["type"] != "decision":
            continue
        for row in (span.get("output") or {}).get("considered", []):
            if row.get("believed_depart") != row.get("listed_depart"):
                findings.append(
                    {
                        "kind": "contradiction",
                        "fact": f"departure time of {row['flight']}",
                        "document_value": row["believed_depart"],
                        "live_value": row["listed_depart"],
                        "span_ids": [span["id"]] + [r["id"] for r in reads],
                        "action": f"Reconcile the document with the live schedule for {row['flight']}.",
                    }
                )
    return findings
