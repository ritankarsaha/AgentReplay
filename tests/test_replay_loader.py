from __future__ import annotations

import httpx
import pytest

from agentreplay.replay import loader
from agentreplay.replay.exceptions import TraceFetchError


def _client_for(handler):
    return lambda timeout: httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_run_returns_decoded_json_on_success(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/runs/run-123"
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"id": "run-123", "spans": []})

    monkeypatch.setattr(loader, "_build_client", _client_for(handler))

    data = loader.fetch_run(
        "run-123", endpoint="http://ingest.test", api_key="test-key", timeout=5.0
    )
    assert data == {"id": "run-123", "spans": []}


def test_fetch_run_strips_trailing_slash_from_endpoint(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={"id": "x", "spans": []})

    monkeypatch.setattr(loader, "_build_client", _client_for(handler))
    loader.fetch_run("x", endpoint="http://ingest.test/", api_key="k")
    assert seen["path"] == "/v1/runs/x"


def test_fetch_run_401_raises_trace_fetch_error(monkeypatch):
    monkeypatch.setattr(
        loader, "_build_client", _client_for(lambda r: httpx.Response(401, text="unauthorized"))
    )

    with pytest.raises(TraceFetchError, match="401 Unauthorized"):
        loader.fetch_run("x", endpoint="http://ingest.test", api_key="bad-key")


def test_fetch_run_404_raises_trace_fetch_error(monkeypatch):
    monkeypatch.setattr(loader, "_build_client", _client_for(lambda r: httpx.Response(404)))

    with pytest.raises(TraceFetchError, match="run not found"):
        loader.fetch_run("missing-run", endpoint="http://ingest.test", api_key="k")


def test_fetch_run_5xx_raises_trace_fetch_error(monkeypatch):
    monkeypatch.setattr(
        loader, "_build_client", _client_for(lambda r: httpx.Response(500, text="boom"))
    )

    with pytest.raises(TraceFetchError, match="500"):
        loader.fetch_run("x", endpoint="http://ingest.test", api_key="k")


def test_fetch_run_network_error_raises_trace_fetch_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(loader, "_build_client", _client_for(handler))

    with pytest.raises(TraceFetchError, match="network error"):
        loader.fetch_run("x", endpoint="http://ingest.test", api_key="k")


def test_trace_fetch_error_carries_run_id():
    exc = TraceFetchError("run-1", "something went wrong")
    assert exc.run_id == "run-1"
    assert "run-1" in str(exc)
    assert "something went wrong" in str(exc)


# --- load_run_from_file (Day 3 backlog: local-file trace loading) ----------


def test_load_run_from_file_full_run_detail_shape(tmp_path):
    import json

    trace_file = tmp_path / "trace.json"
    trace_file.write_text(json.dumps({"id": "run-abc", "status": "failure", "spans": [{"id": "s1"}]}))

    data = loader.load_run_from_file(trace_file)
    assert data["id"] == "run-abc"
    assert data["spans"] == [{"id": "s1"}]


def test_load_run_from_file_bare_spans_shape(tmp_path):
    import json

    trace_file = tmp_path / "trace.json"
    trace_file.write_text(json.dumps({"spans": [{"id": "s1"}, {"id": "s2"}]}))

    data = loader.load_run_from_file(trace_file)
    assert len(data["spans"]) == 2


def test_load_run_from_file_accepts_str_path(tmp_path):
    import json

    trace_file = tmp_path / "trace.json"
    trace_file.write_text(json.dumps({"spans": []}))

    data = loader.load_run_from_file(str(trace_file))
    assert data == {"spans": []}


def test_load_run_from_file_missing_file_raises_trace_fetch_error(tmp_path):
    with pytest.raises(TraceFetchError, match="could not read"):
        loader.load_run_from_file(tmp_path / "does-not-exist.json")


def test_load_run_from_file_invalid_json_raises_trace_fetch_error(tmp_path):
    trace_file = tmp_path / "trace.json"
    trace_file.write_text("{not valid json")

    with pytest.raises(TraceFetchError, match="not valid JSON"):
        loader.load_run_from_file(trace_file)


def test_load_run_from_file_missing_spans_key_raises_trace_fetch_error(tmp_path):
    import json

    trace_file = tmp_path / "trace.json"
    trace_file.write_text(json.dumps({"id": "run-abc"}))

    with pytest.raises(TraceFetchError, match="missing the required 'spans' key"):
        loader.load_run_from_file(trace_file)


def test_load_run_from_file_non_object_json_raises_trace_fetch_error(tmp_path):
    import json

    trace_file = tmp_path / "trace.json"
    trace_file.write_text(json.dumps([1, 2, 3]))

    with pytest.raises(TraceFetchError, match="missing the required 'spans' key"):
        loader.load_run_from_file(trace_file)
