"""Record and replay of every network-dependent beat (LLM calls, SAM, the browser capture).

Entries are keyed by a named slot, not by request hash: span ids and timestamps differ on every
cold start, so a request hash would never hit across runs. The request hash is stored only to
report drift. Modes:

  live      call out, touch nothing
  record    call out and save every response
  replay    serve only from the recording; never call out, a missing slot is an error
  fallback  call out; on an exception or an unusable result serve the recording instead
"""

from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from controlplane import ledger

MODES = ("live", "record", "replay", "fallback")


class CassetteMiss(Exception):
    """Replay mode asked for a slot that was never recorded."""


def _hash(request: Any) -> str:
    return hashlib.sha256(json.dumps(request, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


class Cassette:
    def __init__(self, path: Optional[str] = None, mode: str = "live") -> None:
        if mode not in MODES:
            raise ValueError(f"unknown cassette mode {mode!r}")
        self.path = Path(path) if path else None
        self.mode = mode
        self._lock = threading.Lock()
        self.entries: Dict[str, Dict[str, Any]] = {}
        self.hits: List[str] = []
        self.live_calls: List[str] = []
        self.misses: List[str] = []
        self.drift: List[str] = []
        self.fallbacks: List[Tuple[str, str]] = []
        if mode in ("replay", "fallback"):
            self.entries = self._load()

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if self.path is None or not self.path.exists():
            return {}
        return json.loads(self.path.read_text()).get("entries", {})

    def save(self) -> None:
        if self.path is None:
            raise ValueError("cassette has no path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "entries": dict(sorted(self.entries.items()))}
        self.path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")

    def run(
        self,
        slot: str,
        request: Any,
        fn: Callable[[], Any],
        *,
        valid: Callable[[Any], bool] = lambda result: result is not None,
    ) -> Any:
        digest = _hash(request)
        if self.mode == "replay":
            return self._serve(slot, digest)
        try:
            with ledger.purpose(slot.split(".")[0]):
                result = fn()
            if not valid(result):
                raise ValueError(f"unusable result for slot {slot!r}")
        except Exception as exc:
            if self.mode == "fallback" and slot in self.entries:
                with self._lock:
                    self.fallbacks.append((slot, f"{type(exc).__name__}: {exc}"[:160]))
                return self.entries[slot]["response"]
            raise
        with self._lock:
            self.live_calls.append(slot)
            if self.mode == "record":
                self.entries[slot] = {
                    "request_hash": digest,
                    "response": json.loads(json.dumps(result, default=str)),
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                }
        return result

    def _serve(self, slot: str, digest: str) -> Any:
        with self._lock:
            entry = self.entries.get(slot)
            if entry is None:
                self.misses.append(slot)
                raise CassetteMiss(f"no recording for slot {slot!r} in {self.path}")
            self.hits.append(slot)
            if entry["request_hash"] != digest:
                self.drift.append(slot)
            return entry["response"]

    def stats(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "hits": len(self.hits),
            "live_calls": len(self.live_calls),
            "misses": list(self.misses),
            "drift": list(self.drift),
            "fallbacks": list(self.fallbacks),
        }


_active: Optional[Cassette] = None


def active() -> Optional[Cassette]:
    return _active


@contextmanager
def use(cassette: Optional[Cassette]) -> Iterator[Optional[Cassette]]:
    global _active
    previous, _active = _active, cassette
    try:
        yield cassette
    finally:
        _active = previous


def run(
    slot: str,
    request: Any,
    fn: Callable[[], Any],
    *,
    valid: Callable[[Any], bool] = lambda result: result is not None,
) -> Any:
    """The seam call sites use: cassette-aware when one is active, a plain call otherwise."""
    if _active is None:
        with ledger.purpose(slot.split(".")[0]):
            return fn()
    return _active.run(slot, request, fn, valid=valid)
