from __future__ import annotations

import json

import pytest

from controlplane import cassette as cas
from controlplane.blobs import BlobStore
from controlplane.learn import scoreboard as sb
from controlplane.learn import vision
from controlplane.learn.causation import extract_facts
from controlplane.learn.walkthrough import build_walkthrough, meta_captioner
from controlplane.narration import meta_narrator
from controlplane.transact import travelbot as tb
from controlplane.transact.choosers import ChoiceTask, LLMChooser
from controlplane.transact.negotiator import MetaBuyer
from controlplane.transact.travelbot import parse_sms
from world import AirlineSite, data

CTX = {
    "intent_text": "Book BLR→CCU Friday morning, under ₹6000.",
    "list_price_inr": 5900,
    "goal_price_inr": 5200,
    "round": 1,
}


def never(*_a, **_k):
    raise AssertionError("replay must not reach the network")


def replaying(tmp_path, slots):
    path = tmp_path / "c.json"
    recorder = cas.Cassette(str(path), "record")
    for slot, response in slots.items():
        recorder.run(slot, {}, lambda response=response: response)
    recorder.save()
    return cas.Cassette(str(path), "replay")


def task():
    site = AirlineSite()
    return ChoiceTask(
        parse_sms("Book BLR→CCU Friday morning, under ₹6000."),
        site.search("BLR", "CCU", data.TRAVEL_DATE)["results"],
        site.read_doc(data.FARE_RULES_DOC_ID),
    )


def test_buyer_rounds_are_separate_slots_and_replay_makes_no_call(tmp_path):
    move = json.dumps({"levers": ["fee_waiver"], "target_price_inr": 5200, "rationale": "r"})
    replay = replaying(tmp_path, {"buyer.round1": move})
    with cas.use(replay):
        got = MetaBuyer(chat=never).propose(CTX)
    assert got.levers == ["fee_waiver"] and replay.hits == ["buyer.round1"]


def test_chooser_replays_a_recorded_pick(tmp_path):
    pick = json.dumps({"flight": "6E-871", "believed_depart": "07:30", "reason": "r"})
    with cas.use(replaying(tmp_path, {"chooser": pick})):
        choice = LLMChooser(chat=never).choose(task())
    assert choice.chosen["flight"] == "6E-871"


def test_narrator_and_captioner_replay(tmp_path, travelbot_trace):
    spans = travelbot_trace["spans"]
    beats = build_walkthrough(spans, extract_facts(spans))["beats"]
    captions = json.dumps({"captions": [f"{b['title']}, in plain words." for b in beats]})
    with cas.use(replaying(tmp_path, {"narrate": "The agent paid ₹5,200.", "captions": captions})):
        assert meta_narrator(chat=never)({"transaction": {}}) == "The agent paid ₹5,200."
        walkthrough = build_walkthrough(spans, extract_facts(spans), captioner=meta_captioner(never))
    assert walkthrough["captions_by_model"] == 7


def test_sam_replays_boxes_without_a_key_or_network(tmp_path, monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    boxes = {"model": "sam-3.1", "prompt": vision.DEPARTURE_PROMPT, "boxes": [{"x1": 1, "y1": 2, "x2": 3, "y2": 4, "w": 9, "h": 9}]}
    with cas.use(replaying(tmp_path, {"sam": boxes})):
        assert vision.segment(b"\x89PNG-anything") == boxes


def test_scoreboard_trials_replay_by_slot_even_when_concurrent(tmp_path):
    model = sb.ModelSpec("m", "meta", "http://x", ("K",))
    reply = [json.dumps({"flight": None, "believed_depart": "", "reason": "r"}), {"prompt_tokens": 1, "completion_tokens": 1}]
    slots = {f"score.m.{trial}.1": reply for trial in range(3)}
    with cas.use(replaying(tmp_path, slots)):
        rows = sb.fan_out(task(), models=(model,), trials=3, ask=never)
    assert [r["verdict"] for r in rows] == [sb.CORRECT] * 3


def test_a_missing_scoreboard_slot_is_an_error_row_and_is_recorded_as_a_miss(tmp_path):
    model = sb.ModelSpec("m", "meta", "http://x", ("K",))
    replay = replaying(tmp_path, {"other": 1})
    with cas.use(replay):
        rows = sb.fan_out(task(), models=(model,), trials=1, ask=never)
    assert rows[0]["verdict"] == sb.ERROR and "CassetteMiss" in rows[0]["error"] and replay.misses == ["score.m.0.1"]


def test_browser_capture_replays_without_chrome(tmp_path, monkeypatch):
    import base64

    monkeypatch.setattr(tb, "capture_png", never)
    png = b"\x89PNG-recorded"
    with cas.use(replaying(tmp_path, {"capture": base64.b64encode(png).decode()})):
        bot = tb.TravelBot(blobs=BlobStore(str(tmp_path / "blobs")))
        record = bot._capture({"pnr": "SIMX", "flight": "6E-871", "depart_at": "2026-11-06T19:30", "price_inr": 5200.0, "passenger": "t"})
    assert record["image"]["bytes"] == len(png) and bot.blobs.get(record["image"]["sha256"]) == png


def test_capture_fallback_serves_the_recorded_image_when_chrome_is_missing(tmp_path, monkeypatch):
    import base64

    png = b"\x89PNG-recorded"
    path = tmp_path / "c.json"
    recorder = cas.Cassette(str(path), "record")
    recorder.run("capture", {}, lambda: base64.b64encode(png).decode())
    recorder.save()
    monkeypatch.setattr(tb, "capture_png", lambda html: None)
    with cas.use(cas.Cassette(str(path), "fallback")) as fb:
        bot = tb.TravelBot(blobs=BlobStore(str(tmp_path / "blobs")))
        record = bot._capture({"pnr": "SIMX", "flight": "6E-871", "depart_at": "2026-11-06T19:30", "price_inr": 5200.0, "passenger": "t"})
    assert record["image"] is not None and fb.fallbacks
