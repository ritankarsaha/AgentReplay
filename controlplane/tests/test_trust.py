from __future__ import annotations

from datetime import datetime, timedelta, timezone

from controlplane.govern import trust

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def test_perfect_agent_hits_ceiling():
    result = trust.compute_trust(
        recent_failure_rate=0, regression_pass_rate=1, violation_times=[], runs_count=10_000, now=NOW
    )
    assert result.score == 850
    assert (result.band, result.cap_inr) == ("trusted", 15_000)


def test_worst_agent_hits_floor():
    result = trust.compute_trust(
        recent_failure_rate=1, regression_pass_rate=0, violation_times=[NOW] * 10, runs_count=0, now=NOW
    )
    assert result.score == 300
    assert (result.band, result.cap_inr) == ("restricted", 0)


def test_inputs_are_clamped():
    result = trust.compute_trust(recent_failure_rate=-5, regression_pass_rate=9, runs_count=-3, now=NOW)
    assert 300 <= result.score <= 850


def test_band_boundaries():
    assert trust.band_for(499) == ("restricted", 0)
    assert trust.band_for(500) == ("probation", 2_000)
    assert trust.band_for(599) == ("probation", 2_000)
    assert trust.band_for(600) == ("standard", 6_000)
    assert trust.band_for(699) == ("standard", 6_000)
    assert trust.band_for(700) == ("trusted", 15_000)


def test_violation_penalty_decays_with_half_life():
    fresh = trust.violation_penalty([NOW], NOW)
    later = trust.violation_penalty([NOW - timedelta(days=trust.VIOLATION_HALF_LIFE_DAYS)], NOW)
    assert fresh == trust.VIOLATION_WEIGHT
    assert abs(later - fresh / 2) < 1e-9
    assert trust.violation_penalty([NOW - timedelta(days=365)], NOW) < 0.001


def test_violation_penalty_saturates_and_accepts_naive_datetimes():
    assert trust.violation_penalty([NOW] * 50, NOW) == 1.0
    assert trust.violation_penalty([datetime(2026, 11, 1)], NOW) == trust.VIOLATION_WEIGHT


def test_history_factor_saturates():
    assert trust.history_factor(0) == 0
    assert trust.history_factor(20) < trust.history_factor(100) < 1.0


def test_deterministic_and_components_exposed():
    kwargs = dict(recent_failure_rate=0.2, regression_pass_rate=0.8, violation_times=[NOW], runs_count=30, now=NOW)
    a, b = trust.compute_trust(**kwargs), trust.compute_trust(**kwargs)
    assert a == b
    assert set(a.components) == {
        "recent_failure_rate", "regression_pass_rate", "scope_violation_penalty", "history_factor", "composite"
    }


def test_new_violation_lowers_score():
    base = dict(recent_failure_rate=0.2, regression_pass_rate=0.8, runs_count=30, now=NOW)
    clean = trust.compute_trust(violation_times=[], **base)
    dirty = trust.compute_trust(violation_times=[NOW], **base)
    assert dirty.score < clean.score
