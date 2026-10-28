from __future__ import annotations

import pytest

from app.models import RegressionCase
from app.regression import InvalidStatusTransition, apply_status_transition, can_transition


@pytest.mark.parametrize(
    "current,target,expected",
    [
        ("proposed", "active", True),
        ("proposed", "rejected", True),
        ("proposed", "muted", False),
        ("proposed", "archived", False),
        ("active", "muted", True),
        ("active", "archived", True),
        ("active", "proposed", False),
        ("active", "rejected", False),
        ("muted", "active", True),
        ("muted", "archived", True),
        ("muted", "proposed", False),
        ("archived", "active", False),
        ("rejected", "active", False),
    ],
)
def test_can_transition_matrix(current, target, expected):
    assert can_transition(current, target) is expected


def _case(status: str) -> RegressionCase:
    return RegressionCase(
        id="c1",
        project_id="p1",
        title="t",
        entrypoint="mod:fn",
        tool_spans=[],
        priority="P1",
        status=status,
        evidence_level="native_structured",
    )


def test_apply_status_transition_mutates_on_success():
    case = _case("proposed")
    apply_status_transition(case, "active")
    assert case.status == "active"


def test_apply_status_transition_raises_on_invalid_edge():
    case = _case("archived")
    with pytest.raises(InvalidStatusTransition):
        apply_status_transition(case, "active")
    assert case.status == "archived"  # unchanged on failure


def test_apply_status_transition_rejects_unknown_status_value():
    case = _case("proposed")
    with pytest.raises(ValueError, match="not a valid status"):
        apply_status_transition(case, "not-a-real-status")
