from __future__ import annotations

import subprocess

import agentreplay
from controlplane.blobs import BlobStore
from controlplane.world import capture
from controlplane.world.sms import SmsGateway


def test_blob_store_is_content_addressed_and_deduplicates(tmp_path):
    store = BlobStore(str(tmp_path))
    first = store.put(b"hello", "image/png")
    second = store.put(b"hello", "image/png")
    assert first == second and first["uri"] == f"blob://sha256/{first['sha256']}"
    assert len(list(tmp_path.iterdir())) == 1
    assert store.get(first["sha256"]) == b"hello"
    assert store.get("0" * 64) is None


def test_blob_store_env_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTREPLAY_BLOB_DIR", str(tmp_path / "x"))
    ref = BlobStore().put(b"a", "text/html")
    assert (tmp_path / "x" / f"{ref['sha256']}.html").exists()


def test_capture_returns_none_without_a_browser(monkeypatch):
    monkeypatch.setattr(capture, "find_browser", lambda: None)
    assert capture.capture_png("<p>x</p>") is None


def test_capture_returns_none_when_browser_fails(monkeypatch):
    monkeypatch.setattr(capture, "find_browser", lambda: "/bin/false")

    def boom(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "x")

    monkeypatch.setattr(capture.subprocess, "run", boom)
    assert capture.capture_png("<p>x</p>") is None


def test_capture_reads_the_screenshot_the_browser_wrote(monkeypatch):
    monkeypatch.setattr(capture, "find_browser", lambda: "/fake/chrome")

    def fake_run(cmd, **kwargs):
        out = next(a for a in cmd if a.startswith("--screenshot=")).split("=", 1)[1]
        open(out, "wb").write(b"PNGDATA")

    monkeypatch.setattr(capture.subprocess, "run", fake_run)
    assert capture.capture_png("<p>x</p>") == b"PNGDATA"


def test_find_browser_respects_explicit_path(tmp_path, monkeypatch):
    exe = tmp_path / "chrome"
    exe.write_text("")
    monkeypatch.setenv("AGENTREPLAY_CHROME", str(exe))
    assert capture.find_browser() == str(exe)
    monkeypatch.setenv("AGENTREPLAY_CHROME", str(tmp_path / "missing"))
    assert capture.find_browser() is None


def test_sms_gateway_records_message_spans_labeled_simulated(recorded):
    agentreplay.init(api_key="k", project_id="p")
    gateway = SmsGateway()
    gateway.receive("+91", "hi")
    gateway.send("+91", "yo")
    assert [(s.type, s.name) for s in recorded] == [("message", "sms.inbound"), ("message", "sms.outbound")]
    assert all(s.output["simulated"] for s in recorded)
    assert recorded[0].output["direction"] == "inbound"


def test_sms_gateway_is_silent_when_not_recording():
    assert SmsGateway().receive("+91", "hi") is None
