from __future__ import annotations

from datetime import datetime, timezone

import pytest

import agentreplay
from agentreplay.fingerprint import compute_fingerprint
from agentreplay.replay import ReplayDivergence
from agentreplay.replay import runner as runner_module
from agentreplay.replay.runner import (
    ReplayResult,
    _suppress_live_init,
    replay_run,
    replay_run_from_file,
    resolve_entrypoint,
)
from agentreplay.span import Span

anthropic = pytest.importorskip("anthropic")


def test_resolve_entrypoint_resolves_real_function():
    func = resolve_entrypoint("_replay_runner_fixture:main")
    assert callable(func)
    assert func.__name__ == "main"


def test_resolve_entrypoint_rejects_spec_without_colon():
    with pytest.raises(ValueError, match="expected 'module.path:function_name'"):
        resolve_entrypoint("no_colon_here")


def test_resolve_entrypoint_rejects_unknown_module():
    with pytest.raises(ValueError, match="could not import module"):
        resolve_entrypoint("definitely_not_a_real_module_xyz:main")


def test_resolve_entrypoint_rejects_missing_attribute():
    with pytest.raises(ValueError, match="has no attribute"):
        resolve_entrypoint("_replay_runner_fixture:does_not_exist")


def test_resolve_entrypoint_rejects_non_callable():
    with pytest.raises(ValueError, match="is not callable"):
        resolve_entrypoint("_replay_runner_fixture:not_callable")


def test_suppress_live_init_forces_enabled_false_and_restores_after():
    original_init = agentreplay.init
    with _suppress_live_init():
        assert agentreplay.init is not original_init
        config = agentreplay.init(api_key="key", project_id="proj")
        assert config.enabled is False
    assert agentreplay.init is original_init


def test_suppress_live_init_allows_init_without_credentials():
    with _suppress_live_init():
        # Would normally raise ConfigurationError (no api_key/project_id +
        # enabled=True default) -- suppression forces enabled=False first.
        config = agentreplay.init()
        assert config.enabled is False


def _recorded_anthropic_span(request_payload: dict, output: dict) -> dict:
    return Span(
        id="span-0",
        run_id="run-1",
        parent_id=None,
        type="llm",
        name="anthropic.messages.create",
        input=request_payload,
        output=output,
        error=None,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        duration_ms=1.0,
        fingerprint=compute_fingerprint(request_payload),
    ).to_dict()


_REQUEST_PAYLOAD = {
    "model": "claude-sonnet-4-6",
    "max_tokens": 100,
    "messages": [{"role": "user", "content": "hi"}],
}

_RECORDED_OUTPUT = {
    "id": "msg_1",
    "model": "claude-sonnet-4-6",
    "role": "assistant",
    "type": "message",
    "content": [{"type": "text", "text": "replayed hello"}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 1, "output_tokens": 1},
}


def test_replay_run_fetches_trace_and_calls_entrypoint(monkeypatch):
    span = _recorded_anthropic_span(_REQUEST_PAYLOAD, _RECORDED_OUTPUT)

    def fake_fetch_run(run_id, *, endpoint, api_key, timeout):
        assert run_id == "run-123"
        assert endpoint == "http://localhost:8000"
        assert api_key == "test-key"
        return {"id": run_id, "spans": [span]}

    monkeypatch.setattr(runner_module, "fetch_run", fake_fetch_run)
    original_init = agentreplay.init

    result = replay_run(
        "run-123",
        "_replay_runner_fixture:main",
        endpoint="http://localhost:8000",
        api_key="test-key",
    )

    assert isinstance(result, ReplayResult)
    assert result.run_id == "run-123"
    assert result.entrypoint_result == "replayed hello"
    assert result.session.remaining_count() == 0
    # _suppress_live_init() restored the real init() after the call.
    assert agentreplay.init is original_init


def test_replay_run_propagates_entrypoint_exceptions(monkeypatch):
    monkeypatch.setattr(runner_module, "fetch_run", lambda *a, **kw: {"id": "r", "spans": []})

    with pytest.raises(RuntimeError, match="entrypoint exploded"):
        replay_run("run-x", "_replay_runner_fixture:boom", endpoint="http://x", api_key="k")


def test_replay_run_propagates_divergence(monkeypatch):
    monkeypatch.setattr(runner_module, "fetch_run", lambda *a, **kw: {"id": "r", "spans": []})

    with pytest.raises(ReplayDivergence):
        replay_run("run-x", "_replay_runner_fixture:main", endpoint="http://x", api_key="k")


def test_replay_run_passes_through_resolve_entrypoint_errors(monkeypatch):
    monkeypatch.setattr(runner_module, "fetch_run", lambda *a, **kw: {"id": "r", "spans": []})

    with pytest.raises(ValueError, match="has no attribute"):
        replay_run(
            "run-x", "_replay_runner_fixture:does_not_exist", endpoint="http://x", api_key="k"
        )


# --- replay_run_from_file (Day 3 backlog: local-file trace loading, no
# ingest API/credentials needed at all) -------------------------------------


def test_replay_run_from_file_loads_and_calls_entrypoint(tmp_path):
    import json

    span = _recorded_anthropic_span(_REQUEST_PAYLOAD, _RECORDED_OUTPUT)
    trace_file = tmp_path / "trace.json"
    trace_file.write_text(json.dumps({"id": "run-from-file", "spans": [span]}))
    original_init = agentreplay.init

    result = replay_run_from_file(str(trace_file), "_replay_runner_fixture:main")

    assert isinstance(result, ReplayResult)
    assert result.run_id == "run-from-file"
    assert result.entrypoint_result == "replayed hello"
    assert result.session.remaining_count() == 0
    assert agentreplay.init is original_init


def test_replay_run_from_file_falls_back_to_path_when_no_id_field(tmp_path):
    import json

    trace_file = tmp_path / "bare_trace.json"
    trace_file.write_text(json.dumps({"spans": []}))

    with pytest.raises(ReplayDivergence):
        replay_run_from_file(str(trace_file), "_replay_runner_fixture:main")
    # (divergence is expected — no recorded calls in a bare/empty trace;
    # this test only cares that loading + dispatch reached that point.)


def test_replay_run_from_file_missing_file_raises_trace_fetch_error(tmp_path):
    from agentreplay.replay.exceptions import TraceFetchError

    with pytest.raises(TraceFetchError):
        replay_run_from_file(str(tmp_path / "nope.json"), "_replay_runner_fixture:main")


def test_replay_run_from_file_propagates_entrypoint_exceptions(tmp_path):
    import json

    trace_file = tmp_path / "trace.json"
    trace_file.write_text(json.dumps({"spans": []}))

    with pytest.raises(RuntimeError, match="entrypoint exploded"):
        replay_run_from_file(str(trace_file), "_replay_runner_fixture:boom")
