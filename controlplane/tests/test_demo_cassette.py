from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from controlplane.demo import DEFAULT_CASSETTE

PATH = Path(DEFAULT_CASSETTE)
BASE_SLOTS = {"captions", "capture", "classify", "narrate", "sam"}
SCORE_MODELS = ("muse-spark-1.1", "muse-spark-1.2", "muse-spark-1.3")


@pytest.fixture(scope="module")
def entries():
    assert PATH.exists(), "the demo cassette must be committed: it is the offline fallback for every model beat"
    data = json.loads(PATH.read_text())
    assert data["version"] == 1
    return data["entries"]


def test_every_model_beat_has_a_recording(entries):
    scoreboard = {f"score.{m}.{t}.1" for m in SCORE_MODELS for t in range(3)}
    assert BASE_SLOTS | scoreboard <= set(entries)


def test_entries_carry_a_request_hash_and_a_timestamp(entries):
    assert all(len(e["request_hash"]) == 64 and e["recorded_at"] and "response" in e for e in entries.values())


def test_recorded_classification_is_done_and_names_a_mast_class(entries):
    reply = entries["classify"]["response"]
    assert reply["classification_status"] == "done" and reply["failure_class"]


def test_recorded_screenshot_is_a_real_png_and_sam_boxed_one_region(entries):
    png = base64.b64decode(entries["capture"]["response"])
    assert png.startswith(b"\x89PNG\r\n\x1a\n") and len(png) > 1000
    boxes = entries["sam"]["response"]["boxes"]
    assert len(boxes) == 1 and boxes[0]["x2"] > boxes[0]["x1"] and boxes[0]["y2"] > boxes[0]["y1"]


def test_recorded_text_states_the_amount_and_is_never_empty(entries):
    assert "5200" in entries["narrate"]["response"].replace(",", "")
    assert json.loads(entries["captions"]["response"][entries["captions"]["response"].index("{"):])["captions"]
    assert all(e["response"] not in ("", None) for e in entries.values())


def test_the_recording_contains_no_credentials(entries):
    blob = json.dumps(entries)
    assert "Bearer " not in blob and "LLM_" not in blob and "api_key" not in blob.lower()
