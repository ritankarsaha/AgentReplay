"""Spend ledger for live model calls. Cassette hits never record, so a replayed run costs nothing."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from controlplane.pricing import cost_usd

_purpose: ContextVar[str] = ContextVar("ledger_purpose", default="other")


@dataclass(frozen=True)
class Entry:
    purpose: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Optional[float]
    at: str


class Ledger:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: List[Entry] = []
        self._path: Optional[Path] = None

    def configure(self, path: Optional[str]) -> None:
        self._path = Path(path) if path else None

    def reset(self) -> None:
        with self._lock:
            self._entries.clear()

    def record(self, model: str, usage: Optional[dict], *, cost: Optional[float] = None, purpose: Optional[str] = None) -> Entry:
        usage = usage or {}
        entry = Entry(
            purpose=purpose or _purpose.get(),
            model=model,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            cost_usd=cost if cost is not None else cost_usd(model, usage),
            at=datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            self._entries.append(entry)
            if self._path is not None:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a") as handle:
                    handle.write(json.dumps(asdict(entry)) + "\n")
        return entry

    @property
    def entries(self) -> List[Entry]:
        with self._lock:
            return list(self._entries)

    def summary(self) -> Dict[str, object]:
        entries = self.entries
        priced = [e.cost_usd for e in entries if e.cost_usd is not None]
        by_purpose: Dict[str, float] = {}
        for entry in entries:
            by_purpose[entry.purpose] = by_purpose.get(entry.purpose, 0.0) + (entry.cost_usd or 0.0)
        return {
            "calls": len(entries),
            "unpriced_calls": len(entries) - len(priced),
            "cost_usd": round(sum(priced), 6),
            "by_purpose": {k: round(v, 6) for k, v in sorted(by_purpose.items())},
        }


LEDGER = Ledger()


@contextmanager
def purpose(name: str) -> Iterator[None]:
    token = _purpose.set(name)
    try:
        yield
    finally:
        _purpose.reset(token)


def load(path: str) -> List[Entry]:
    file = Path(path)
    if not file.exists():
        return []
    return [Entry(**json.loads(line)) for line in file.read_text().splitlines() if line.strip()]
