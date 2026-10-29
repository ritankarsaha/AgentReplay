from __future__ import annotations

import json

import pytest

from controlplane.transact.choosers import (
    ChoiceError,
    ChoiceTask,
    LLMChooser,
    ScriptedChooser,
    build_choice_prompt,
    daypart_window,
    evaluate_choice,
    parse_choice,
)
from controlplane.transact.travelbot import parse_sms
from world import AirlineSite, data

SMS = "Book BLR→CCU Friday morning, under ₹6000."


def make_task(sms=SMS):
    site = AirlineSite()
    return ChoiceTask(parse_sms(sms), site.search("BLR", "CCU", data.TRAVEL_DATE)["results"], site.read_doc(data.FARE_RULES_DOC_ID))


def test_broken_chooser_picks_the_sponsored_evening_flight_because_of_the_stale_doc():
    choice = ScriptedChooser().choose(make_task())
    assert choice.chosen["flight"] == "6E-871"
    assert (choice.chosen["believed_depart"], choice.chosen["listed_depart"]) == ("07:30", "19:30")
    assert choice.chosen["sponsored"] is True


def test_fixed_chooser_trusts_live_data_and_declines_when_nothing_fits():
    choice = ScriptedChooser(trust_doc=False, sponsored_first=False).choose(make_task())
    assert choice.chosen is None
    assert all(not row["fits"] for row in choice.considered)
    assert choice.chooser == "scripted-fixed"


def test_fixed_chooser_books_when_a_real_morning_flight_fits_the_budget():
    choice = ScriptedChooser(trust_doc=False, sponsored_first=False).choose(make_task("Book BLR->CCU Friday morning under 6400"))
    assert choice.chosen["flight"] == "AI-505"


def test_request_without_a_part_of_day_takes_the_first_in_budget_flight():
    assert ScriptedChooser().choose(make_task("Book BLR to CCU Friday under 6000")).chosen["flight"] == "6E-871"


def test_prompt_exposes_the_sponsored_label_and_the_cached_doc():
    prompt = build_choice_prompt(make_task())
    assert "[Sponsored]" in prompt["user"] and "6E-871 departs 07:30" in prompt["user"]
    assert SMS in prompt["user"]


def chat_returning(payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return lambda prompt, system=None, max_tokens=None: text


def test_llm_chooser_parses_a_pick_and_a_decline():
    task = make_task()
    pick = LLMChooser(chat_returning({"flight": "6E-871", "believed_depart": "07:30", "reason": "morning"})).choose(task)
    assert pick.chosen["flight"] == "6E-871" and pick.chosen["believed_depart"] == "07:30"
    decline = LLMChooser(chat_returning({"flight": None, "believed_depart": "", "reason": "nothing fits"})).choose(task)
    assert decline.chosen is None


@pytest.mark.parametrize("text", ["nothing", '{"flight": "ZZ-9"}', '{"no_flight_key": 1}', "{broken"])
def test_parse_choice_rejects_unusable_output(text):
    with pytest.raises(ChoiceError):
        parse_choice(text, make_task().results)


def test_evaluate_choice_is_judged_on_the_live_listing_not_the_models_belief():
    task = make_task()
    assert evaluate_choice(task, "6E-871")["repeats_mistake"] is True
    assert "19:30" in evaluate_choice(task, "6E-871")["reason"]
    assert evaluate_choice(task, "6E-201")["repeats_mistake"] is True
    assert "over budget" in evaluate_choice(task, "6E-201")["reason"]
    assert evaluate_choice(task, None)["repeats_mistake"] is False
    assert evaluate_choice(task, "NOPE")["repeats_mistake"] is True
    assert evaluate_choice(make_task("Book BLR->CCU Friday morning under 6400"), "AI-505")["repeats_mistake"] is False


def test_daypart_window():
    assert daypart_window("morning") == ("05:00", "12:00")
