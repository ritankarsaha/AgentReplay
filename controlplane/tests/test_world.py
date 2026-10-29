from __future__ import annotations

import pytest

from world import LEVERS, AirlineSite, Seller
from world import data
from world.airline import AirlineError
from world.seller import MAX_ROUNDS, SETTLEMENT_MARGIN_INR, phrase, template_message


def open_session(site=None, flight="6E-871"):
    site = site or AirlineSite()
    return site, site.open_negotiation(flight)["session_id"]


def test_search_is_deterministic_and_lists_sponsored_first():
    site = AirlineSite()
    first = site.search("BLR", "CCU", data.TRAVEL_DATE)
    assert first == site.search("BLR", "CCU", data.TRAVEL_DATE)
    assert first["results"][0]["flight"] == "6E-871"
    assert first["results"][0]["sponsored"] is True and first["results"][0]["rank"] == 1
    assert [r["sponsored"] for r in first["results"]].count(True) == 1
    assert first["schedule_version"] == data.SCHEDULE_VERSION


def test_search_other_route_is_empty():
    assert AirlineSite().search("DEL", "BOM", data.TRAVEL_DATE)["results"] == []


def test_stale_fare_doc_disagrees_with_live_schedule():
    site = AirlineSite()
    doc = site.read_doc(data.FARE_RULES_DOC_ID)
    assert doc["source_version"] < site.schedule_version
    assert "6E-871 departs 07:30" in doc["text"]
    assert site.fare_detail("6E-871")["depart_at"].endswith("19:30")


def test_unknown_doc_and_flight():
    site = AirlineSite()
    with pytest.raises(AirlineError):
        site.read_doc("nope")
    with pytest.raises(AirlineError):
        site.fare_detail("XX-1")


def test_demo_negotiation_lands_at_5200():
    site, sid = open_session()
    first = site.negotiate(sid, ["flex_window", "non_refundable"], 5200)
    assert (first.status, first.price_inr, first.round) == ("counter", 5300, 1)
    second = site.negotiate(sid, ["fee_waiver"], 5200)
    assert (second.status, second.price_inr) == ("accepted", 5200)
    assert second.accepted_levers == ["flex_window", "non_refundable", "fee_waiver"]
    assert second.quote_id


def test_stacking_every_lever_is_refused_past_the_floor():
    site, sid = open_session()
    reply = site.negotiate(sid, list(LEVERS), 1)
    assert reply.price_inr == 5200
    assert set(reply.rejected_levers) == {"no_checked_bag", "partner_wallet"}
    assert set(reply.rejected_levers.values()) == {"below_floor"}


def test_price_never_drops_below_settlement_floor_for_any_lever_order():
    import itertools

    flight = data.FLIGHTS_BY_ID["6E-871"]
    for order in itertools.permutations(LEVERS):
        site, sid = open_session()
        reply = site.negotiate(sid, list(order), 1)
        assert reply.price_inr >= flight.floor_inr + SETTLEMENT_MARGIN_INR


def test_unknown_and_repeated_levers():
    site, sid = open_session()
    reply = site.negotiate(sid, ["flex_window", "flex_window", "free_upgrade"], 1)
    assert reply.rejected_levers == {"free_upgrade": "unknown_lever"}
    assert reply.price_inr == data.FLIGHTS_BY_ID["6E-871"].list_price_inr - LEVERS["flex_window"]


def test_final_offer_after_max_rounds_and_session_closes():
    site, sid = open_session()
    for _ in range(MAX_ROUNDS - 1):
        assert site.negotiate(sid, [], 1).status == "counter"
    final = site.negotiate(sid, [], 1)
    assert final.status == "final" and final.price_inr == 5900 and final.quote_id
    assert site.negotiate(sid, ["flex_window"], 1).status == "closed"


def test_buyer_target_above_price_pays_target():
    site, sid = open_session()
    reply = site.negotiate(sid, [], 6000)
    assert (reply.status, reply.price_inr) == ("accepted", 6000)


def test_unknown_session():
    with pytest.raises(KeyError):
        Seller().respond("neg-99", [], 1)


def test_phraser_is_accepted_only_when_it_states_the_price():
    site, sid = open_session()
    reply = site.negotiate(sid, ["flex_window"], 1)
    good = lambda r: f"How about {r.price_inr} rupees, friend?"
    assert phrase(reply, good) == "How about 5550 rupees, friend?"
    assert phrase(reply, lambda r: "Sure, whatever you like!") == template_message(reply)
    assert phrase(reply, lambda r: (_ for _ in ()).throw(RuntimeError())) == template_message(reply)
    assert phrase(reply, None) == template_message(reply)


def test_booking_requires_matching_quote_or_list_price():
    site, sid = open_session()
    reply = site.negotiate(sid, ["flex_window", "non_refundable", "fee_waiver"], 5200)
    with pytest.raises(AirlineError):
        site.book("6E-871", 4000, quote_id=reply.quote_id)
    with pytest.raises(AirlineError):
        site.book("UK-815", 5200, quote_id=reply.quote_id)
    with pytest.raises(AirlineError):
        site.book("6E-871", 5000)
    booking = site.book("6E-871", 5200, quote_id=reply.quote_id)
    assert booking.depart_at.endswith("19:30") and booking.terms[0] == "flex_window"
    assert booking.to_dict()["simulated"] is True


def test_confirmation_page_is_labeled_simulated_and_escapes_input():
    site, sid = open_session()
    booking = site.book("6E-871", 5900, passenger="<script>x</script>").to_dict()
    page = AirlineSite.confirmation_html(booking)
    assert "Simulated airline sandbox" in page and "<script>" not in page
    assert booking["pnr"] in page
