from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import agentreplay
from controlplane.govern.broker import (
    AccessDenied,
    AirlineConnector,
    Broker,
    CardConnector,
    InMemoryTokenStore,
    token_id_for,
)


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 1, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


def test_issue_stores_only_the_hash_and_authorizes():
    store = InMemoryTokenStore()
    broker = Broker(store)
    issued = broker.issue("agt_1", "airline", ["search", "book"])
    assert issued.token.startswith("atk_")
    assert store.get(issued.token) is None
    assert store.get(token_id_for(issued.token)) is issued.record
    assert broker.authorize(issued.token, "airline", "search").agent_id == "agt_1"


@pytest.mark.parametrize(
    "token_kwargs,use,rule",
    [
        ({}, ("card", "search"), "connector_mismatch"),
        ({}, ("airline", "charge"), "scope_missing"),
    ],
)
def test_denials(token_kwargs, use, rule):
    broker = Broker()
    issued = broker.issue("agt_1", "airline", ["search"], **token_kwargs)
    with pytest.raises(AccessDenied) as exc:
        broker.authorize(issued.token, *use)
    assert exc.value.rule == rule


def test_unknown_token_denied():
    with pytest.raises(AccessDenied) as exc:
        Broker().authorize("atk_nope", "airline", "search")
    assert exc.value.rule == "token_unknown"


def test_expiry():
    clock = Clock()
    broker = Broker(clock=clock)
    issued = broker.issue("agt_1", "airline", ["search"], ttl=timedelta(minutes=5))
    broker.authorize(issued.token, "airline", "search")
    clock.now += timedelta(minutes=5)
    with pytest.raises(AccessDenied) as exc:
        broker.authorize(issued.token, "airline", "search")
    assert exc.value.rule == "token_expired"


def test_revocation_takes_effect_immediately_and_is_idempotent():
    broker = Broker()
    issued = broker.issue("agt_1", "airline", ["search"])
    assert broker.revoke(issued.token) is True
    assert broker.revoke(issued.token) is True
    with pytest.raises(AccessDenied) as exc:
        broker.authorize(issued.token, "airline", "search")
    assert exc.value.rule == "token_revoked"
    assert broker.revoke("atk_unknown") is False


def test_connectors_are_labeled_simulated_and_audited():
    broker = Broker()
    airline = broker.issue("agt_1", "airline", ["search", "book"])
    card = broker.issue("agt_1", "card", ["charge"])
    agentreplay.init(api_key="k", project_id="p")

    flights = AirlineConnector(broker, airline.token).search_flights("DEL", "BOM", "2026-11-07")
    booking = AirlineConnector(broker, airline.token).book_flight(flights[0]["flight"], flights[0]["price_inr"])
    charge = CardConnector(broker, card.token).charge(5900, "flight")
    assert booking["simulated"] and charge["simulated"]
    assert AirlineConnector.simulated and CardConnector.simulated

    spans = agentreplay.get_recorded_spans()
    assert [s.type for s in spans] == ["policy"] * 3
    assert spans[0].name == "broker.airline.search"
    assert "token" not in str(spans[0].input) and airline.token not in str(spans[0].output)


def test_denied_use_is_audited_before_raising():
    broker = Broker()
    issued = broker.issue("agt_1", "airline", ["search"])
    broker.revoke(issued.token)
    agentreplay.init(api_key="k", project_id="p")
    with pytest.raises(AccessDenied):
        AirlineConnector(broker, issued.token).search_flights("DEL", "BOM", "d")
    span = agentreplay.get_recorded_spans()[0]
    assert span.output["decision"] == "deny" and span.output["rule"] == "token_revoked"
