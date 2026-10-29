"""Deterministic trust score No LLM involvement.

composite = 0.35*(1 - recent_failure_rate)
          + 0.30*regression_pass_rate
          + 0.25*(1 - scope_violation_penalty)
          + 0.10*history_factor
score = round(300 + 550*composite)   # 300-850
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

WEIGHTS = {"failure": 0.35, "regression": 0.30, "violation": 0.25, "history": 0.10}
VIOLATION_WEIGHT = 0.5
VIOLATION_HALF_LIFE_DAYS = 14.0
HISTORY_SATURATION_RUNS = 20.0

# (minimum score, band label, spend cap in INR). Cap 0 means human approval.
DEFAULT_BANDS: Tuple[Tuple[int, str, int], ...] = (
    (700, "trusted", 15_000),
    (600, "standard", 6_000),
    (500, "probation", 2_000),
    (0, "restricted", 0),
)


@dataclass(frozen=True)
class TrustResult:
    score: int
    band: str
    cap_inr: int
    components: Dict[str, float]

    def to_dict(self) -> dict:
        return asdict(self)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def violation_penalty(
    violation_times: Iterable[datetime], now: datetime, half_life_days: float = VIOLATION_HALF_LIFE_DAYS
) -> float:
    total = 0.0
    for when in violation_times:
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (now - when).total_seconds() / 86400.0)
        total += VIOLATION_WEIGHT * 0.5 ** (age_days / half_life_days)
    return _clamp(total)


def history_factor(runs_count: int) -> float:
    return _clamp(1.0 - math.exp(-max(0, runs_count) / HISTORY_SATURATION_RUNS))


def band_for(score: int, bands: Iterable[Tuple[int, str, int]] = DEFAULT_BANDS) -> Tuple[str, int]:
    for minimum, label, cap in sorted(bands, reverse=True):
        if score >= minimum:
            return label, cap
    raise ValueError("no band matches score")


def compute_trust(
    *,
    recent_failure_rate: float,
    regression_pass_rate: float,
    violation_times: Optional[List[datetime]] = None,
    runs_count: int = 0,
    now: Optional[datetime] = None,
    bands: Iterable[Tuple[int, str, int]] = DEFAULT_BANDS,
    penalty_override: Optional[float] = None,
) -> TrustResult:
    now = now or datetime.now(timezone.utc)
    failure = _clamp(recent_failure_rate)
    regression = _clamp(regression_pass_rate)
    penalty = (
        _clamp(penalty_override)
        if penalty_override is not None
        else violation_penalty(violation_times or [], now)
    )
    history = history_factor(runs_count)
    composite = (
        WEIGHTS["failure"] * (1 - failure)
        + WEIGHTS["regression"] * regression
        + WEIGHTS["violation"] * (1 - penalty)
        + WEIGHTS["history"] * history
    )
    score = round(300 + 550 * composite)
    band, cap = band_for(score, bands)
    return TrustResult(
        score=score,
        band=band,
        cap_inr=cap,
        components={
            "recent_failure_rate": round(failure, 4),
            "regression_pass_rate": round(regression, 4),
            "scope_violation_penalty": round(penalty, 4),
            "history_factor": round(history, 4),
            "composite": round(composite, 4),
        },
    )
