from __future__ import annotations

import pytest

import agentreplay
from agentreplay import ScopeViolation, _state
from agentreplay.replay import replay_mode
from controlplane.blobs import BlobStore
from controlplane.govern import Monitor, ScopeGuard, generate_keypair
from controlplane.transact import travelbot as tb
from controlplane.transact.travelbot import TravelBot, parse_sms, part_of_day, travelbot_manifest

SMS = "Book BLR→CCU Friday morning, under ₹6000."
PNG = b"\x89PNG\r\n\x1a\nfake"


@pytest.fixture(autouse=True)
def fake_capture(monkeypatch):
    monkeypatch.setattr(tb, "capture_png", lambda html: PNG)


def make_bot(tmp_path):
    return TravelBot(blobs=BlobStore(str(tmp_path)))


def test_parse_sms_variants():
    intent = parse_sms("book blr -> ccu friday evening, below ₹7,500 please")
    assert (intent.origin, intent.destination, intent.part_of_day, intent.budget_inr) == ("BLR", "CCU", "evening", 7500)
    assert parse_sms("Book BLR to CCU Friday under 6000").part_of_day is None


@pytest.mark.parametrize("body", ["hello", "Book BLR→CCU Monday morning under 6000", "Book BLR→CCU Friday morning"])
def test_parse_sms_rejects_unusable_requests(body):
    with pytest.raises(ValueError):
        parse_sms(body)


def test_part_of_day_boundaries():
    assert [part_of_day(t) for t in ("2026-11-06T05:00", "2026-11-06T11:59", "2026-11-06T12:00", "2026-11-06T19:30", "2026-11-06T23:00")] == [
        "morning", "morning", "afternoon", "evening", "night",
    ]


def test_wrong_purchase_path_is_reproducible_and_fully_traced(recorded, tmp_path):
    agentreplay.init(api_key="k", project_id="p")
    result = make_bot(tmp_path).run(SMS)

    assert result.flight == "6E-871" and result.price_inr == 5200
    assert result.mismatch is True
    assert result.booking["depart_at"].endswith("19:30")

    types = [s.type for s in recorded]
    assert types[0] == "message" and recorded[0].name == "sms.inbound"
    for expected in ("data_read", "decision", "negotiation", "screenshot"):
        assert expected in types
    assert types[-1] == "message" and recorded[-1].name == "sms.outbound"

    search = next(s for s in recorded if s.type == "tool" and s.name == "search_flights")
    assert search.output["results"][0]["sponsored"] is True

    data_read = next(s for s in recorded if s.type == "data_read")
    assert data_read.output["source_version"] < data_read.output["live_schedule_version"]

    decision = next(s for s in recorded if s.type == "decision").output["chosen"]
    assert decision["sponsored"] and decision["believed_depart"] == "07:30" and decision["listed_depart"] == "19:30"

    final = [s for s in recorded if s.type == "negotiation"][-1].output
    assert final["accepted_levers"][0] == "flex_window"


def test_two_runs_produce_identical_outcomes(tmp_path):
    outcomes = []
    for _ in range(2):
        agentreplay.init(api_key="k", project_id="p")
        result = make_bot(tmp_path).run(SMS)
        outcomes.append((result.flight, result.price_inr, result.booking["pnr"]))
    assert outcomes[0] == outcomes[1]


def test_screenshot_span_references_blobs(recorded, tmp_path):
    agentreplay.init(api_key="k", project_id="p")
    bot = make_bot(tmp_path)
    result = bot.run(SMS)
    shot = next(s for s in recorded if s.type == "screenshot").output
    assert shot["captured"] is True and shot["image"]["mime"] == "image/png"
    assert bot.blobs.get(shot["image"]["sha256"]) == PNG
    assert b"Booking confirmed" in bot.blobs.get(shot["html"]["sha256"])
    assert result.screenshot["pnr"] == result.booking["pnr"]


def test_screenshot_span_marks_missing_browser(recorded, tmp_path, monkeypatch):
    monkeypatch.setattr(tb, "capture_png", lambda html: None)
    agentreplay.init(api_key="k", project_id="p")
    make_bot(tmp_path).run(SMS)
    shot = next(s for s in recorded if s.type == "screenshot").output
    assert shot["captured"] is False and shot["image"] is None and shot["html"]["bytes"] > 0


def test_without_guard_the_fix_attempt_buys_a_second_ticket(tmp_path):
    bot = make_bot(tmp_path)
    bot.run(SMS, attempt_fix=True)
    assert len(bot.site.bookings) == 2


def test_guard_halts_the_second_booking_attempt(recorded, tmp_path):
    keypair = generate_keypair()
    guard = ScopeGuard(
        travelbot_manifest(keypair),
        keypair.public_key,
        bindings=tb.BINDINGS,
        arg_names=tb.ARG_NAMES,
        monitor=Monitor(),
    )
    agentreplay.set_tool_guard(guard)
    agentreplay.init(api_key="k", project_id="p")
    bot = make_bot(tmp_path)
    with pytest.raises(ScopeViolation) as exc:
        bot.run(SMS, attempt_fix=True)
    assert exc.value.rule == "max_bookings"
    assert len(bot.site.bookings) == 1 and guard.is_halted()
    assert recorded[-1].type == "alert"


def test_clean_run_stays_inside_the_manifest(tmp_path):
    keypair = generate_keypair()
    guard = ScopeGuard(travelbot_manifest(keypair), keypair.public_key, bindings=tb.BINDINGS, arg_names=tb.ARG_NAMES)
    agentreplay.set_tool_guard(guard)
    agentreplay.init(api_key="k", project_id="p")
    result = make_bot(tmp_path).run(SMS)
    assert result.price_inr == 5200 and not guard.is_halted()
    assert guard.bookings == 1 and guard.spent_inr == 5200


def test_strict_replay_reproduces_the_run_without_touching_the_world(recorded, tmp_path):
    agentreplay.init(api_key="k", project_id="p")
    first = make_bot(tmp_path).run(SMS)
    trace = [s.to_dict() for s in recorded]

    _state.reset()
    fresh = make_bot(tmp_path)
    with replay_mode(trace) as session:
        replayed = fresh.run(SMS)
    assert replayed.booking == first.booking
    assert fresh.site.bookings == []
    assert session.remaining_count() == 0
