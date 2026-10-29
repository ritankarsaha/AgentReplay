"""Scope enforcement and spend gate: a `ToolGuard` for `@agentreplay.tool`.

Every decision is deterministic code. Checks run in a fixed order and the
first failing check denies the call:

  halted -> signature/expiry -> revocation -> tool allowlist -> geography
  -> bookings per task -> spend (effective cap = min(manifest cap, trust cap))

Counters reserve on allow and are not rolled back if the tool later fails
(conservative: a failed booking still counts against the task).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Sequence

from agentreplay.guard import GuardDecision

from .identity import ManifestError, ScopeManifest, verify_manifest

DEFAULT_HOME_REGIONS = ("IN",)


@dataclass(frozen=True)
class ToolBinding:
    """How a tool's arguments map onto manifest constraints."""

    amount_arg: Optional[str] = None
    region_arg: Optional[str] = None
    counts_as_booking: bool = False


def _lookup(name: Optional[str], args: tuple, kwargs: dict, positional: Sequence[str]) -> Any:
    if name is None:
        return None
    if name in kwargs:
        return kwargs[name]
    if name in positional:
        index = list(positional).index(name)
        if index < len(args):
            return args[index]
    return None


class ScopeGuard:
    def __init__(
        self,
        manifest: ScopeManifest,
        public_key: str,
        *,
        bindings: Optional[Dict[str, ToolBinding]] = None,
        arg_names: Optional[Dict[str, Sequence[str]]] = None,
        trust_cap_inr: Optional[int] = None,
        is_revoked: Optional[Callable[[], bool]] = None,
        home_regions: Sequence[str] = DEFAULT_HOME_REGIONS,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monitor: Any = None,
    ) -> None:
        self.manifest = manifest
        self._public_key = public_key
        self._bindings = bindings or {}
        self._arg_names = arg_names or {}
        self._trust_cap_inr = trust_cap_inr
        self._is_revoked = is_revoked
        self._home_regions = {r.upper() for r in home_regions}
        self._clock = clock
        self.monitor = monitor
        self._lock = threading.Lock()
        self._halted = False
        self.bookings = 0
        self.spent_inr = 0.0
        if monitor is not None:
            monitor.attach(self)

    def set_trust_cap(self, cap_inr: Optional[int]) -> None:
        self._trust_cap_inr = cap_inr

    def effective_cap_inr(self) -> Optional[float]:
        manifest_cap = self.manifest.constraints.get("max_spend_inr")
        caps = [c for c in (manifest_cap, self._trust_cap_inr) if c is not None]
        return min(caps) if caps else None

    def reset(self) -> None:
        with self._lock:
            self.bookings = 0
            self.spent_inr = 0.0

    def is_halted(self) -> bool:
        return self._halted

    def halt(self) -> None:
        self._halted = True

    def _counters(self) -> dict:
        return {"bookings": self.bookings, "spent_inr": self.spent_inr}

    def _decide(self, allowed: bool, rule: str, reason: str, **details: Any) -> GuardDecision:
        base = {
            "agent_id": self.manifest.agent_id,
            "manifest_version": self.manifest.version,
            "effective_cap_inr": self.effective_cap_inr(),
            "counters": self._counters(),
        }
        base.update(details)
        return GuardDecision(allowed, rule, reason, base)

    def check(self, tool_name: str, args: tuple, kwargs: dict) -> GuardDecision:
        with self._lock:
            return self._check_locked(tool_name, args, kwargs)

    def _check_locked(self, tool_name: str, args: tuple, kwargs: dict) -> GuardDecision:
        deny = lambda rule, reason, **d: self._decide(False, rule, reason, **d)  # noqa: E731

        if self._halted:
            return deny("run_halted", "run was halted by the monitor")

        try:
            verify_manifest(self.manifest, self._public_key, now=self._clock())
        except ManifestError as exc:
            return deny("manifest_invalid", str(exc))

        if self._is_revoked is not None and self._is_revoked():
            return deny("manifest_revoked", "scope manifest was revoked")

        if tool_name not in self.manifest.allowed_tools:
            return deny("tool_not_allowed", f"'{tool_name}' is not in the manifest allowlist")

        binding = self._bindings.get(tool_name, ToolBinding())
        positional = self._arg_names.get(tool_name, ())
        constraints = self.manifest.constraints

        if constraints.get("geography") == "domestic" and binding.region_arg:
            region = _lookup(binding.region_arg, args, kwargs, positional)
            if region is None or str(region).upper() not in self._home_regions:
                return deny("geography", f"destination {region!r} is outside the domestic scope")

        if binding.counts_as_booking:
            limit = constraints.get("max_bookings_per_task")
            if limit is not None and self.bookings + 1 > limit:
                return deny("max_bookings", f"booking limit of {limit} per task reached")

        amount = _lookup(binding.amount_arg, args, kwargs, positional)
        if binding.amount_arg is not None and amount is not None:
            try:
                amount = float(amount)
            except (TypeError, ValueError):
                return deny("invalid_amount", f"amount {amount!r} is not numeric")
            if amount < 0:
                return deny("invalid_amount", "amount must be non-negative")
            cap = self.effective_cap_inr()
            if cap is not None:
                if cap == 0:
                    return deny("approval_required", "trust band requires human approval for spend", amount_inr=amount)
                if self.spent_inr + amount > cap:
                    return deny(
                        "spend_cap",
                        f"{self.spent_inr + amount:.0f} INR exceeds the effective cap of {cap:.0f} INR",
                        amount_inr=amount,
                    )
            self.spent_inr += amount

        if binding.counts_as_booking:
            self.bookings += 1

        return self._decide(True, "allowed", "within scope", amount_inr=amount if binding.amount_arg else None)

    def on_violation(self, tool_name: str, decision: GuardDecision, span_id: Optional[str]) -> None:
        if self.monitor is not None and decision.rule != "run_halted":
            self.monitor.on_violation(tool_name, decision, span_id)
