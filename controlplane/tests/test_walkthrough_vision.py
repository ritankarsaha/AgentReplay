from __future__ import annotations

import json

import httpx
import pytest

from controlplane.blobs import BlobStore
from controlplane.client import ControlPlaneError
from controlplane.incidents import IncidentPipeline
from controlplane.learn import vision
from controlplane.learn.causation import extract_facts
from controlplane.learn.walkthrough import build_walkthrough, meta_captioner, select_beats
from controlplane.tests.test_incidents import CLASSIFIED, FakeClient

PNG = b"\x89PNG\r\n\x1a\nfake-bytes"


def test_beats_follow_the_incident_in_order_with_span_references(travelbot_trace):
    spans = travelbot_trace["spans"]
    beats = select_beats(spans, extract_facts(spans))
    assert [b["kind"] for b in beats] == ["intent", "sponsored", "stale_data", "decision", "negotiation", "purchase", "halt"]
    ids = {s["id"] for s in spans}
    assert all(b["span_id"] in ids for b in beats)
    purchase = next(b for b in beats if b["kind"] == "purchase")
    assert purchase["title"] == "It books the wrong flight" and purchase["screenshot_sha256"]
    assert "morning" in purchase["caption"] and "19:30" in purchase["caption"]
    assert "flex window" in next(b for b in beats if b["kind"] == "negotiation")["caption"]
    assert "max_bookings" in json.dumps(next(b for b in beats if b["kind"] == "halt")["facts"])


def test_template_captions_are_the_baseline(travelbot_trace):
    spans = travelbot_trace["spans"]
    walkthrough = build_walkthrough(spans, extract_facts(spans))
    assert {b["caption_source"] for b in walkthrough["beats"]} == {"template"}
    assert walkthrough["captions_by_model"] == 0 and walkthrough["note"] is None


def captions_for(spans, mutate=None):
    beats = select_beats(spans, extract_facts(spans))
    captions = [f"{b['title']}, in plain words." for b in beats]
    if mutate:
        mutate(captions)
    return captions


def test_model_captions_replace_templates_when_valid(travelbot_trace):
    spans = travelbot_trace["spans"]
    chat = lambda prompt, system=None, max_tokens=None: json.dumps({"captions": captions_for(spans)})
    walkthrough = build_walkthrough(spans, extract_facts(spans), captioner=meta_captioner(chat), model="muse-test")
    assert walkthrough["captions_by_model"] == 7
    assert walkthrough["beats"][0]["caption"] == "The request, in plain words." and walkthrough["beats"][0]["caption_source"] == "muse-test"


def test_a_caption_with_an_invented_number_falls_back_to_its_template(travelbot_trace):
    spans = travelbot_trace["spans"]

    def invent(captions):
        captions[5] = "It booked a flight for INR 999 at 03:00."
        captions[1] = ""

    chat = lambda prompt, system=None, max_tokens=None: json.dumps({"captions": captions_for(spans, invent)})
    beats = build_walkthrough(spans, extract_facts(spans), captioner=meta_captioner(chat))["beats"]
    assert beats[5]["caption_source"] == "template" and "999" not in beats[5]["caption"]
    assert beats[1]["caption_source"] == "template"
    assert beats[0]["caption_source"] != "template"


@pytest.mark.parametrize("reply", ["no json", '{"captions": "x"}', '{"captions": ["only one"]}', '{"nope": 1}'])
def test_bad_model_output_keeps_template_captions_and_records_a_note(travelbot_trace, reply):
    spans = travelbot_trace["spans"]
    chat = lambda prompt, system=None, max_tokens=None: reply
    walkthrough = build_walkthrough(spans, extract_facts(spans), captioner=meta_captioner(chat))
    assert walkthrough["captions_by_model"] == 0 and "unavailable" in walkthrough["note"]


def test_captioner_exceptions_are_contained(travelbot_trace):
    spans = travelbot_trace["spans"]

    def boom(beats):
        raise RuntimeError("down")

    walkthrough = build_walkthrough(spans, extract_facts(spans), captioner=boom)
    assert walkthrough["beats"] and "RuntimeError" in walkthrough["note"]


def test_parse_boxes_reads_pixel_boxes_and_skips_masks_and_junk():
    text = "<|box;x1=166;y1=258;x2=343;y2=290;w=900;h=560|><|mask;x=0;y=0;data=AAAA|><|box;x1=1;y1=2|>"
    assert vision.parse_boxes(text) == [{"x1": 166, "y1": 258, "x2": 343, "y2": 290, "w": 900, "h": 560}]
    assert vision.parse_boxes("") == []


def test_segment_posts_text_and_image_and_returns_boxes():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["url"] = str(request.url)
        text = "<|box;x1=10;y1=20;x2=30;y2=40;w=100;h=50|>"
        return httpx.Response(200, json={"output": [{"content": [{"type": "output_text", "text": text}]}]})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    result = vision.segment(PNG, api_key="k", base_url="http://meta.test/v1", http=http)
    assert seen["url"] == "http://meta.test/v1/responses"
    content = seen["body"]["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": vision.DEPARTURE_PROMPT}
    assert content[1]["image_url"].startswith("data:image/png;base64,")
    assert seen["body"]["model"] == "sam-3.1"
    assert result["boxes"] == [{"x1": 10, "y1": 20, "x2": 30, "y2": 40, "w": 100, "h": 50}]


def test_segment_requires_a_key_and_surfaces_http_errors(monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    from controlplane import meta

    with pytest.raises(meta.MetaNotConfigured):
        vision.segment(PNG)
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(httpx.HTTPStatusError):
        vision.segment(PNG, api_key="k", http=http)


class VisualClient(FakeClient):
    def __init__(self, *args, fail_upload=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.blobs, self.fail_upload = [], fail_upload

    def put_blob(self, payload, mime):
        if self.fail_upload:
            raise ControlPlaneError("down")
        import hashlib

        self.blobs.append(mime)
        return {"sha256": hashlib.sha256(payload).hexdigest(), "mime": mime}


def stored_sha(spans, store):
    shot = next(s for s in spans if s["type"] == "screenshot")["output"]["image"]
    return shot["sha256"]


def test_pipeline_uploads_the_screenshot_and_stores_annotations_and_walkthrough(travelbot_trace, tmp_path):
    store = BlobStore(str(tmp_path / "blobs"))
    sha = stored_sha(travelbot_trace["spans"], store)
    for span in travelbot_trace["spans"]:
        if span["type"] == "screenshot":
            span["output"]["image"] = {"sha256": store.put(PNG, "image/png")["sha256"], "mime": "image/png", "bytes": len(PNG)}
    sha = stored_sha(travelbot_trace["spans"], store)
    client = VisualClient(travelbot_trace, classify=CLASSIFIED, trust={"band": "probation", "score": 536})
    boxes = [{"x1": 1, "y1": 2, "x2": 3, "y2": 4, "w": 9, "h": 9}]
    pipeline = IncidentPipeline(client, blobs=store, annotate=True, segment=lambda png: {"model": "sam-3.1", "prompt": "p", "boxes": boxes})
    report = pipeline.process("inc-1")
    assert report.assets == [sha] and client.blobs == ["image/png"]
    assert report.annotations[0]["boxes"] == boxes and report.annotations[0]["span_id"]
    assert len(report.walkthrough["beats"]) == 7
    assert client.details["assets"] == [sha] and client.details["walkthrough"]["beats"]


def test_pipeline_notes_missing_blob_failed_upload_and_failed_segmentation(travelbot_trace, tmp_path):
    empty = BlobStore(str(tmp_path / "none"))
    report = IncidentPipeline(VisualClient(travelbot_trace, classify=CLASSIFIED), blobs=empty).process("inc-1")
    assert report.assets == [] and any("not found locally" in n for n in report.notes)

    store = BlobStore(str(tmp_path / "blobs"))
    for span in travelbot_trace["spans"]:
        if span["type"] == "screenshot":
            span["output"]["image"] = {"sha256": store.put(PNG, "image/png")["sha256"], "mime": "image/png"}
    failed = IncidentPipeline(VisualClient(travelbot_trace, classify=CLASSIFIED, fail_upload=True), blobs=store).process("inc-1")
    assert failed.assets == [] and any("upload failed" in n for n in failed.notes)

    def bad_segment(png):
        raise RuntimeError("sam down")

    sam = IncidentPipeline(VisualClient(travelbot_trace, classify=CLASSIFIED), blobs=store, annotate=True, segment=bad_segment).process("inc-1")
    assert sam.assets and sam.annotations == [] and any("SAM 3.1 segmentation failed" in n for n in sam.notes)
