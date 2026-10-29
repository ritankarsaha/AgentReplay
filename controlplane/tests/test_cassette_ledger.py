from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from controlplane import cassette as cas
from controlplane import ledger, meta
from controlplane.pricing import cost_usd


def never(*_a, **_k):
    raise AssertionError("must not call out")


def record(tmp_path, entries):
    path = tmp_path / "c.json"
    recorder = cas.Cassette(str(path), "record")
    for slot, request, response in entries:
        recorder.run(slot, request, lambda response=response: response)
    recorder.save()
    return str(path)


def test_record_then_replay_serves_without_calling_out(tmp_path):
    path = record(tmp_path, [("buyer.round1", {"p": 1}, "hello"), ("sam", {"i": 2}, {"boxes": [1]})])
    replay = cas.Cassette(path, "replay")
    assert replay.run("buyer.round1", {"p": 1}, never) == "hello"
    assert replay.run("sam", {"i": 2}, never) == {"boxes": [1]}
    assert replay.stats()["hits"] == 2 and replay.stats()["live_calls"] == 0 and replay.drift == []


def test_replay_reports_drift_but_still_serves(tmp_path):
    path = record(tmp_path, [("narrate", {"p": "old"}, "text")])
    replay = cas.Cassette(path, "replay")
    assert replay.run("narrate", {"p": "new"}, never) == "text"
    assert replay.drift == ["narrate"]


def test_replay_miss_is_an_error_and_is_recorded(tmp_path):
    replay = cas.Cassette(record(tmp_path, [("a", {}, 1)]), "replay")
    with pytest.raises(cas.CassetteMiss):
        replay.run("b", {}, never)
    assert replay.misses == ["b"]


def test_replay_against_a_missing_file_misses_everything(tmp_path):
    replay = cas.Cassette(str(tmp_path / "nope.json"), "replay")
    with pytest.raises(cas.CassetteMiss):
        replay.run("a", {}, never)


def test_record_keeps_every_slot_and_saves_sorted_json(tmp_path):
    path = record(tmp_path, [("z", {}, 1), ("a", {}, 2)])
    saved = json.loads(open(path).read())
    assert list(saved["entries"]) == ["a", "z"] and saved["entries"]["a"]["response"] == 2


def test_live_mode_calls_out_and_records_nothing(tmp_path):
    live = cas.Cassette(str(tmp_path / "c.json"), "live")
    assert live.run("a", {}, lambda: "x") == "x"
    assert live.entries == {} and live.stats()["live_calls"] == 1


def test_fallback_serves_the_recording_on_error_or_unusable_result(tmp_path):
    path = record(tmp_path, [("buyer.round1", {}, "recorded"), ("sam", {}, {"boxes": []})])
    fb = cas.Cassette(path, "fallback")

    def boom():
        raise TimeoutError("stalled")

    assert fb.run("buyer.round1", {}, boom) == "recorded"
    assert fb.run("sam", {}, lambda: "", valid=bool) == {"boxes": []}
    assert [slot for slot, _ in fb.fallbacks] == ["buyer.round1", "sam"]
    assert "TimeoutError" in fb.fallbacks[0][1] and "unusable" in fb.fallbacks[1][1]


def test_fallback_prefers_live_and_reraises_without_a_recording(tmp_path):
    fb = cas.Cassette(record(tmp_path, [("a", {}, "recorded")]), "fallback")
    assert fb.run("a", {}, lambda: "live") == "live" and fb.fallbacks == []
    with pytest.raises(ZeroDivisionError):
        fb.run("unrecorded", {}, lambda: 1 / 0)


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        cas.Cassette(None, "sometimes")


def test_module_run_is_a_plain_call_without_an_active_cassette():
    assert cas.active() is None
    assert cas.run("x", {}, lambda: 5) == 5


def test_use_activates_and_restores(tmp_path):
    c = cas.Cassette(str(tmp_path / "c.json"), "live")
    with cas.use(c):
        assert cas.active() is c
        cas.run("x", {}, lambda: 1)
    assert cas.active() is None and c.live_calls == ["x"]


def test_ledger_records_priced_and_unpriced_calls_by_purpose():
    led = ledger.Ledger()
    led.record("muse-spark-1.3", {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}, purpose="a")
    led.record("some-nim-model", {"prompt_tokens": 5, "completion_tokens": 5}, purpose="b")
    led.record("sam-3.1", None, cost=None, purpose="sam")
    summary = led.summary()
    assert summary["calls"] == 3 and summary["unpriced_calls"] == 2 and summary["cost_usd"] == 5.5
    assert summary["by_purpose"]["a"] == 5.5 and summary["by_purpose"]["b"] == 0.0


def test_ledger_persists_jsonl_and_loads_back(tmp_path):
    path = str(tmp_path / "l" / "credits.jsonl")
    led = ledger.Ledger()
    led.configure(path)
    led.record("muse-spark-1.3", {"prompt_tokens": 10, "completion_tokens": 20}, purpose="classify")
    led.record("muse-spark-1.3", {"prompt_tokens": 1, "completion_tokens": 1}, purpose="classify")
    loaded = ledger.load(path)
    assert [e.purpose for e in loaded] == ["classify", "classify"] and loaded[0].completion_tokens == 20
    assert ledger.load(str(tmp_path / "missing.jsonl")) == []


def test_purpose_scope_labels_nested_calls_and_a_live_cassette_call_sets_it(tmp_path):
    led = ledger.LEDGER
    before = len(led.entries)
    with cas.use(cas.Cassette(None, "live")):
        cas.run("captions", {}, lambda: led.record("muse-spark-1.3", {"prompt_tokens": 1, "completion_tokens": 1}))
    assert led.entries[before].purpose == "captions"


def test_replay_records_nothing_in_the_ledger(tmp_path):
    path = record(tmp_path, [("buyer.round1", {}, "x")])
    before = len(ledger.LEDGER.entries)
    with cas.use(cas.Cassette(path, "replay")):
        cas.run("buyer.round1", {}, never)
    assert len(ledger.LEDGER.entries) == before


def test_cost_estimate_is_unknown_for_unpriced_models():
    assert cost_usd("muse-spark-1.3", {"prompt_tokens": 1_000_000, "completion_tokens": 0}) == 1.25
    assert cost_usd("meta/muse-glimmer-30b", {"prompt_tokens": 1, "completion_tokens": 1}) is None
    assert cost_usd("muse-spark-1.3", None) is None


def make_client(replies, usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20)):
    calls = []

    class _Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            text = replies[min(len(calls) - 1, len(replies) - 1)]
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))], usage=usage)

    return SimpleNamespace(chat=SimpleNamespace(completions=_Completions())), calls


def test_chat_retries_an_empty_reply_once_and_records_every_call():
    client, calls = make_client(["", "pong"])
    before = len(ledger.LEDGER.entries)
    assert meta.chat("hi", client=client) == "pong"
    assert len(calls) == 2 and len(ledger.LEDGER.entries) == before + 2


def test_chat_gives_up_after_one_retry_and_passes_pinning_only_when_asked():
    client, calls = make_client([""])
    assert meta.chat("hi", client=client) == "" and len(calls) == 2
    assert "temperature" not in calls[0] and "seed" not in calls[0]
    client, calls = make_client(["ok"])
    meta.chat("hi", client=client, temperature=0, seed=7)
    assert calls[0]["temperature"] == 0 and calls[0]["seed"] == 7
