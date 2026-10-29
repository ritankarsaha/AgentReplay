from __future__ import annotations

import httpx
import pytest

import agentreplay
from agentreplay import ScopeViolation, _state
from agentreplay.replay import replay_mode
from controlplane.govern import Monitor, ScopeGuard, ToolBinding, generate_keypair, sign_manifest
from controlplane.govern.monitor import ALERT_SPAN_TYPE, HALT_SPAN_NAME


def build(monitor):
    kp = generate_keypair()
    manifest = sign_manifest(
        kp,
        allowed_tools=["search_flights", "book_flight"],
        constraints={"max_spend_inr": 6000, "max_bookings_per_task": 1, "geography": "domestic"},
    )
    return ScopeGuard(
        manifest,
        kp.public_key,
        bindings={"book_flight": ToolBinding(amount_arg="price_inr", counts_as_booking=True)},
        arg_names={"book_flight": ["flight", "price_inr"]},
        monitor=monitor,
    )


def define_tools():
    @agentreplay.tool(name="search_flights")
    def search_flights(query):
        return ["F1", "F2"]

    @agentreplay.tool(name="book_flight")
    def book_flight(flight, price_inr):
        return {"pnr": "X"}

    @agentreplay.tool(name="wire_money")
    def wire_money(amount):
        raise AssertionError("must never run")

    return search_flights, book_flight, wire_money


def scripted_agent(tools):
    search_flights, book_flight, wire_money = tools
    search_flights("del-bom")
    book_flight("F1", 5200)
    wire_money(9000)


def test_violation_halts_run_alerts_and_emits_alert_span(recorded):
    alerts = []
    monitor = Monitor(sinks=[alerts.append])
    guard = build(monitor)
    agentreplay.set_tool_guard(guard)
    tools = define_tools()
    agentreplay.init(api_key="k", project_id="p")

    with pytest.raises(ScopeViolation) as exc:
        scripted_agent(tools)

    assert exc.value.rule == "tool_not_allowed"
    assert guard.is_halted()
    assert len(alerts) == 1 and alerts[0]["rule"] == "tool_not_allowed"

    spans = recorded
    assert [s.type for s in spans] == ["policy", "tool", "policy", "tool", "policy", "scope_violation", ALERT_SPAN_TYPE]
    alert = spans[-1]
    assert alert.name == HALT_SPAN_NAME
    assert alert.input["culprit_span_id"] == spans[5].id
    assert alert.input["agent_id"] == guard.manifest.agent_id


def test_spend_gate_breach_also_halts_and_is_labeled():
    monitor = Monitor()
    guard = build(monitor)
    agentreplay.set_tool_guard(guard)
    _, book_flight, _ = define_tools()
    agentreplay.init(api_key="k", project_id="p")
    with pytest.raises(ScopeViolation):
        book_flight("F1", 9000)
    assert guard.is_halted()
    assert monitor.alerts[0]["kind"] == "spend_gate"


def test_webhook_delivery_and_failure_isolation():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200)

    ok = Monitor(webhook_url="http://hook.test/a", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    guard = build(ok)
    guard.on_violation("wire_money", guard.check("wire_money", (), {}), "span-1")
    assert len(seen) == 1
    assert ok.alerts[0]["delivery"]["webhook"] == {"ok": True, "status": 200}

    def boom(request):
        raise httpx.ConnectError("down")

    bad = Monitor(webhook_url="http://hook.test/a", http_client=httpx.Client(transport=httpx.MockTransport(boom)))
    guard2 = build(bad)
    guard2.on_violation("wire_money", guard2.check("wire_money", (), {}), "span-2")
    assert guard2.is_halted()
    assert bad.alerts[0]["delivery"]["webhook"]["ok"] is False


def test_sink_failure_does_not_prevent_halt():
    def bad_sink(alert):
        raise RuntimeError("pager down")

    monitor = Monitor(sinks=[bad_sink])
    guard = build(monitor)
    guard.on_violation("wire_money", guard.check("wire_money", (), {}), None)
    assert guard.is_halted()
    assert monitor.alerts[0]["delivery"]["sink_0"]["ok"] is False


def test_replay_reproduces_violation_with_zero_live_calls(recorded):
    agentreplay.set_tool_guard(build(Monitor()))
    tools = define_tools()
    agentreplay.init(api_key="k", project_id="p")
    with pytest.raises(ScopeViolation):
        scripted_agent(tools)
    trace = [s.to_dict() for s in recorded]

    _state.reset()
    # Replay needs no guard, no credentials, no live tool execution.
    replayed_tools = define_tools()
    with replay_mode(trace):
        with pytest.raises(ScopeViolation) as exc:
            scripted_agent(replayed_tools)
    assert exc.value.rule == "tool_not_allowed"


def test_replay_of_clean_run_is_unaffected_by_policy_spans():
    guard = build(Monitor())
    agentreplay.set_tool_guard(guard)
    search_flights, book_flight, _ = define_tools()
    agentreplay.init(api_key="k", project_id="p")
    search_flights("del-bom")
    book_flight("F1", 5200)
    recorded = [s.to_dict() for s in agentreplay.get_recorded_spans()]

    _state.reset()
    search_flights, book_flight, _ = define_tools()
    with replay_mode(recorded) as session:
        assert search_flights("del-bom") == ["F1", "F2"]
        assert book_flight("F1", 5200) == {"pnr": "X"}
    assert session.remaining_count() == 0


def test_replay_of_pre_governance_trace_still_works():
    search_flights, _, _ = define_tools()
    agentreplay.init(api_key="k", project_id="p")
    search_flights("q")
    recorded = [s.to_dict() for s in agentreplay.get_recorded_spans()]
    assert [s["type"] for s in recorded] == ["tool"]
    _state.reset()
    search_flights, _, _ = define_tools()
    with replay_mode(recorded):
        assert search_flights("q") == ["F1", "F2"]
