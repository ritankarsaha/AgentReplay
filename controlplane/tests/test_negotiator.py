from __future__ import annotations

import json

import pytest

from controlplane.transact.negotiator import BuyerError, MetaBuyer, ScriptedBuyer, run_negotiation
from world import AirlineSite

CTX = {
    "intent_text": "Book BLR→CCU Friday morning, under ₹6000.",
    "list_price_inr": 5900,
    "goal_price_inr": 5200,
    "round": 1,
}


def negotiate_against(site):
    session = site.open_negotiation("6E-871")
    return session, (lambda sid, levers, target: site.negotiate(sid, levers, target).to_dict())


def test_scripted_buyer_ladder_skips_accepted_and_rejected():
    buyer = ScriptedBuyer()
    assert buyer.propose(CTX).levers == ["flex_window", "non_refundable"]
    later = {**CTX, "round": 2, "accepted_levers": ["flex_window", "non_refundable"]}
    assert buyer.propose(later).levers == ["fee_waiver"]
    exhausted = {**CTX, "round": 3, "accepted_levers": ["flex_window"], "rejected_levers": ["non_refundable", "fee_waiver", "no_checked_bag"]}
    assert buyer.propose(exhausted).levers == ["partner_wallet"]


def test_run_negotiation_with_scripted_buyer_lands_at_5200(recorded):
    import agentreplay

    agentreplay.init(api_key="k", project_id="p")
    session, call = negotiate_against(AirlineSite())
    reply = run_negotiation(call, session, ScriptedBuyer(), intent_text=CTX["intent_text"], goal_price_inr=5200)
    assert (reply["status"], reply["price_inr"], reply["round"]) == ("accepted", 5200, 2)
    spans = [s for s in recorded if s.type == "negotiation"]
    assert [s.name for s in spans] == ["negotiate.round1", "negotiate.round2"]
    assert spans[0].input["offered_levers"] == ["flex_window", "non_refundable"]
    assert spans[0].output["simulated_seller"] is True
    assert spans[1].output["new_concessions"] == [{"lever": "fee_waiver", "amount_inr": 100}]


def meta_buyer(payload):
    return MetaBuyer(chat=lambda prompt, system=None, max_tokens=None: payload if isinstance(payload, str) else json.dumps(payload))


def test_meta_buyer_parses_json_even_with_prose():
    move = meta_buyer('Sure! {"levers": ["flex_window"], "target_price_inr": 5200, "rationale": "r"} done').propose(CTX)
    assert move.levers == ["flex_window"] and move.target_price_inr == 5200


@pytest.mark.parametrize(
    "payload",
    [
        "no json here",
        '{"levers": "flex_window", "target_price_inr": 5200}',
        {"levers": ["free_upgrade"], "target_price_inr": 5200},
        {"levers": ["flex_window"], "target_price_inr": -1},
        {"levers": ["flex_window"]},
    ],
)
def test_meta_buyer_rejects_invalid_output(payload):
    with pytest.raises(BuyerError):
        meta_buyer(payload).propose(CTX)


def test_invalid_meta_move_falls_back_to_scripted_and_is_marked(recorded):
    import agentreplay

    agentreplay.init(api_key="k", project_id="p")
    session, call = negotiate_against(AirlineSite())
    reply = run_negotiation(call, session, meta_buyer("garbage"), intent_text="x", goal_price_inr=5200)
    assert reply["status"] == "accepted"
    inputs = [s.input for s in recorded if s.type == "negotiation"]
    assert all(i["buyer_fallback"] and i["buyer"] == "scripted" for i in inputs)


def test_meta_buyer_valid_move_is_used_and_marked_meta(recorded):
    import agentreplay

    agentreplay.init(api_key="k", project_id="p")
    session, call = negotiate_against(AirlineSite())
    buyer = meta_buyer({"levers": ["flex_window", "non_refundable", "fee_waiver"], "target_price_inr": 5200, "rationale": "r"})
    reply = run_negotiation(call, session, buyer, intent_text="x", goal_price_inr=5200)
    assert (reply["status"], reply["price_inr"], reply["round"]) == ("accepted", 5200, 1)
    first = next(s for s in recorded if s.type == "negotiation")
    assert first.input["buyer"] == "meta" and first.input["buyer_fallback"] is False


def test_negotiation_terminates_with_a_stubborn_buyer():
    session, call = negotiate_against(AirlineSite())
    stubborn = type("B", (), {"name": "stub", "propose": lambda self, ctx: __import__("controlplane.transact.negotiator", fromlist=["BuyerMove"]).BuyerMove([], 1)})()
    reply = run_negotiation(call, session, stubborn, intent_text="x", goal_price_inr=1)
    assert reply["status"] == "final" and reply["round"] == 4
