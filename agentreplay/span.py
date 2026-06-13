from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Span:
    """One recorded unit of work, matching the `spans` table schema (CLAUDE.md §3.5)."""

    id: str
    run_id: str
    parent_id: Optional[str]
    type: str  # "llm" | "tool" | "node" | "checkpoint"
    name: str
    input: dict
    output: Optional[dict]
    error: Optional[dict]
    started_at: datetime
    duration_ms: float
    fingerprint: str

    def to_dict(self) -> dict:
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        return data
