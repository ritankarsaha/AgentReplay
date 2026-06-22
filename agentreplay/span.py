from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass
class Span:
    """One recorded unit of work, matching the `spans` table schema (CLAUDE.md §3.5)."""

    id: str
    run_id: str
    parent_id: Optional[str]
    type: str  # "llm" | "tool" | "node" | "checkpoint"
    name: str
    input: dict
    # `output` is the serialized return value of arbitrary user code (e.g. a
    # `@agentreplay.tool`-decorated function returning a list/str/int), so
    # unlike `input`/`error` it isn't always a JSON object — matches the
    # `output jsonb` column (CLAUDE.md §3.5), which accepts any JSON value.
    output: Optional[Any]
    error: Optional[dict]
    started_at: datetime
    duration_ms: float
    fingerprint: str

    def to_dict(self) -> dict:
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        return data
