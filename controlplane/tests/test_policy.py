from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import agentreplay
from agentreplay import ScopeViolation
from controlplane.govern import Monitor, ScopeGuard, ToolBinding, generate_keypair, sign_manifest

BINDINGS = {
    "search_flights": ToolBinding(region_arg="country"),
    "book_flight": ToolBinding(amount_arg="price_inr", region_arg="country", counts_as_booking=True),
}
ARG_NAMES = {"book_flight": ["flight", "price_inr", "country"], "search_flights": ["query", "country"]}


def make_guard(constraints=None, tools=None, **kwargs):
    kp = generate_keypair()
    manifest = sign_manifest(
        kp,
        allowed_tools=tools or ["search_flights", "book_flight"],
        constraints=constraints
        if constraints is not None
        else {"max_spend_inr": 6000, "max_bookings_per_task": 1, "geography": "domestic"},
    )
    return ScopeGuard(manifest, kp.public_key, bindings=BINDINGS, arg_names=ARG_NAMES, **kwargs), kp


def check(guard, tool, *args, **kwargs):
    return guard.check(tool, args, kwargs)


def test_allows_in_scope_call():
    guard, _ = make_guard()
    decision = check(guard, "book_flight", "F1", 5200, "IN")
    assert decision.allowed and decision.rule == "allowed"
    assert guard.bookings == 1 and guard.spent_inr == 5200


def test_tool_outside_allowlist_denied():
    guard, _ = make_guard()
    decision = check(guard, "wire_money", 100)
    assert (decision.allowed, decision.rule) == (False, "tool_not_allowed")


def test_second_booking_denied_by_counter():
    guard, _ = make_guard({"max_bookings_per_task": 1})
    assert check(guard, "book_flight", "F1", 100, "IN").allowed
    assert check(guard, "book_flight", "F2", 100, "IN").rule == "max_bookings"
    guard.reset()
    assert check(guard, "book_flight", "F2", 100, "IN").allowed


def test_spend_cap_cumulative_and_denied_call_does_not_count():
    guard, _ = make_guard({"max_spend_inr": 6000})
    assert check(guard, "book_flight", "F1", 4000, "IN").allowed
    denied = check(guard, "book_flight", "F2", 2500, "IN")
    assert denied.rule == "spend_cap"
    assert guard.spent_inr == 4000 and guard.bookings == 1


def test_amount_taken_from_kwargs_or_positional():
    guard, _ = make_guard({"max_spend_inr": 1000})
    assert check(guard, "book_flight", flight="F", price_inr=5000, country="IN").rule == "spend_cap"
    assert check(guard, "book_flight", "F", 5000, "IN").rule == "spend_cap"


@pytest.mark.parametrize("amount", ["abc", -5])
def test_invalid_amount_denied(amount):
    guard, _ = make_guard()
    assert check(guard, "book_flight", "F", amount, "IN").rule == "invalid_amount"


def test_geography_domestic_only():
    guard, _ = make_guard()
    assert check(guard, "book_flight", "F", 100, "US").rule == "geography"
    assert check(guard, "book_flight", "F", 100, None).rule == "geography"
    assert check(guard, "search_flights", "q", "in").allowed


def test_trust_cap_lowers_effective_cap_but_never_raises_it():
    guard, _ = make_guard({"max_spend_inr": 6000}, trust_cap_inr=2000)
    assert guard.effective_cap_inr() == 2000
    assert check(guard, "book_flight", "F", 2500, "IN").rule == "spend_cap"
    guard.set_trust_cap(15_000)
    assert guard.effective_cap_inr() == 6000


def test_zero_trust_cap_requires_approval():
    guard, _ = make_guard(trust_cap_inr=0)
    assert check(guard, "book_flight", "F", 1, "IN").rule == "approval_required"
    assert check(guard, "search_flights", "q", "IN").allowed


def test_no_spend_constraint_means_no_cap():
    guard, _ = make_guard({})
    assert check(guard, "book_flight", "F", 10**9, "IN").allowed


def test_expired_manifest_denied():
    kp = generate_keypair()
    manifest = sign_manifest(kp, allowed_tools=["search_flights"], ttl=timedelta(days=1))
    later = datetime.now(timezone.utc) + timedelta(days=2)
    guard = ScopeGuard(manifest, kp.public_key, clock=lambda: later)
    assert guard.check("search_flights", (), {}).rule == "manifest_invalid"


def test_tampered_manifest_denied():
    guard, _ = make_guard()
    guard.manifest.constraints["max_spend_inr"] = 10**6
    assert check(guard, "search_flights", "q", "IN").rule == "manifest_invalid"


def test_revocation_denied_live():
    revoked = {"value": False}
    guard, _ = make_guard(is_revoked=lambda: revoked["value"])
    assert check(guard, "search_flights", "q", "IN").allowed
    revoked["value"] = True
    assert check(guard, "search_flights", "q", "IN").rule == "manifest_revoked"


def test_decision_is_deterministic_and_carries_context():
    a, _ = make_guard()
    decision = check(a, "wire_money")
    payload = decision.to_dict()
    assert payload["decision"] == "deny"
    assert payload["details"]["agent_id"] == a.manifest.agent_id
    assert payload["details"]["manifest_version"] == 1


def test_guard_error_fails_closed_through_tool_wrapper():
    class Broken:
        def check(self, *a):
            raise RuntimeError("boom")

    agentreplay.set_tool_guard(Broken())
    called = []

    @agentreplay.tool(name="ping")
    def ping():
        called.append(1)

    with pytest.raises(ScopeViolation) as exc:
        ping()
    assert exc.value.rule == "guard_error" and not called


def test_no_guard_means_no_behavior_change_and_no_policy_spans():
    @agentreplay.tool(name="ping")
    def ping():
        return "pong"

    agentreplay.init(api_key="k", project_id="p")
    assert ping() == "pong"
    assert [s.type for s in agentreplay.get_recorded_spans()] == ["tool"]


def test_wrapper_records_policy_span_then_tool_span_when_allowed():
    guard, _ = make_guard()
    agentreplay.set_tool_guard(guard)

    @agentreplay.tool(name="search_flights")
    def search_flights(query, country):
        return ["F1"]

    agentreplay.init(api_key="k", project_id="p")
    assert search_flights("del-bom", "IN") == ["F1"]
    spans = agentreplay.get_recorded_spans()
    assert [s.type for s in spans] == ["policy", "tool"]
    assert spans[0].output["decision"] == "allow"
    assert spans[0].fingerprint == spans[1].fingerprint


def test_denied_call_never_runs_body_and_records_violation():
    guard, _ = make_guard()
    agentreplay.set_tool_guard(guard)
    ran = []

    @agentreplay.tool(name="wire_money")
    def wire_money(amount):
        ran.append(amount)

    agentreplay.init(api_key="k", project_id="p")
    with pytest.raises(ScopeViolation) as exc:
        wire_money(100)
    assert not ran
    assert exc.value.rule == "tool_not_allowed"
    assert [s.type for s in agentreplay.get_recorded_spans()] == ["policy", "scope_violation"]
    assert agentreplay.get_recorded_spans()[1].error["type"] == "ScopeViolation"


def test_enforcement_applies_even_when_recording_disabled():
    guard, _ = make_guard()
    agentreplay.set_tool_guard(guard)

    @agentreplay.tool(name="wire_money")
    def wire_money(amount):
        return "sent"

    agentreplay.init(enabled=False)
    with pytest.raises(ScopeViolation):
        wire_money(1)
    assert agentreplay.get_recorded_spans() == []


async def test_async_tool_enforced():
    guard, _ = make_guard()
    agentreplay.set_tool_guard(guard)

    @agentreplay.tool(name="wire_money")
    async def wire_money(amount):
        return "sent"

    @agentreplay.tool(name="search_flights")
    async def search_flights(query, country):
        return "ok"

    agentreplay.init(api_key="k", project_id="p")
    assert await search_flights("q", "IN") == "ok"
    with pytest.raises(ScopeViolation):
        await wire_money(1)


async def test_halt_cancels_in_flight_async_tool():
    import asyncio

    guard, _ = make_guard()
    agentreplay.set_tool_guard(guard)
    finished = []

    @agentreplay.tool(name="search_flights")
    async def search_flights(query, country):
        await asyncio.sleep(5)
        finished.append(1)

    agentreplay.init(api_key="k", project_id="p")
    task = asyncio.ensure_future(search_flights("q", "IN"))
    await asyncio.sleep(0.1)
    guard.halt()
    with pytest.raises(ScopeViolation) as exc:
        await asyncio.wait_for(task, timeout=2)
    assert exc.value.rule == "run_halted" and not finished


def test_halted_guard_denies_everything_without_new_alerts():
    alerts = []
    monitor = Monitor(sinks=[alerts.append])
    guard, _ = make_guard(monitor=monitor)
    agentreplay.set_tool_guard(guard)

    @agentreplay.tool(name="wire_money")
    def wire_money(amount):
        pass

    @agentreplay.tool(name="search_flights")
    def search_flights(query, country):
        return 1

    agentreplay.init(api_key="k", project_id="p")
    with pytest.raises(ScopeViolation):
        wire_money(1)
    with pytest.raises(ScopeViolation) as exc:
        search_flights("q", "IN")
    assert exc.value.rule == "run_halted"
    assert len(alerts) == 1
