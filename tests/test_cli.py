from __future__ import annotations

import pytest

from agentreplay import cli
from agentreplay.replay.exceptions import ReplayDivergence, ReplayedError, TraceFetchError
from agentreplay.replay.runner import ReplayResult


class _FakeSession:
    def __init__(self, remaining: int = 0) -> None:
        self._remaining = remaining

    def remaining_count(self) -> int:
        return self._remaining


def test_cli_replay_success(monkeypatch, capsys):
    def fake_replay_run(run_id, entrypoint, *, endpoint, api_key, timeout):
        return ReplayResult(run_id=run_id, session=_FakeSession(0), entrypoint_result="ok")

    monkeypatch.setattr(cli, "replay_run", fake_replay_run)

    exit_code = cli.main(["replay", "run-1", "--entrypoint", "mod:fn", "--api-key", "k"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "replay complete" in out
    assert "0 recorded call(s) unused" in out


def test_cli_replay_warns_on_unused_recorded_calls(monkeypatch, capsys):
    def fake_replay_run(*args, **kwargs):
        return ReplayResult(run_id="r", session=_FakeSession(2), entrypoint_result=None)

    monkeypatch.setattr(cli, "replay_run", fake_replay_run)

    exit_code = cli.main(["replay", "run-1", "--entrypoint", "mod:fn", "--api-key", "k"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "2 recorded call(s) unused" in out
    assert "didn't take every code path" in out


def test_cli_missing_api_key_exits_1(monkeypatch, capsys):
    monkeypatch.delenv("AGENTREPLAY_API_KEY", raising=False)

    exit_code = cli.main(["replay", "run-1", "--entrypoint", "mod:fn"])
    assert exit_code == 1
    assert "no API key" in capsys.readouterr().err


def test_cli_trace_fetch_error_exits_1(monkeypatch, capsys):
    def fake_replay_run(*args, **kwargs):
        raise TraceFetchError("run-1", "404 not found")

    monkeypatch.setattr(cli, "replay_run", fake_replay_run)

    exit_code = cli.main(["replay", "run-1", "--entrypoint", "mod:fn", "--api-key", "k"])
    assert exit_code == 1
    assert "failed to fetch run" in capsys.readouterr().err


def test_cli_bad_entrypoint_exits_1(monkeypatch, capsys):
    def fake_replay_run(*args, **kwargs):
        raise ValueError("bad spec")

    monkeypatch.setattr(cli, "replay_run", fake_replay_run)

    exit_code = cli.main(["replay", "run-1", "--entrypoint", "bad", "--api-key", "k"])
    assert exit_code == 1
    assert "bad spec" in capsys.readouterr().err


def test_cli_divergence_exits_2(monkeypatch, capsys):
    def fake_replay_run(*args, **kwargs):
        raise ReplayDivergence(call_site="x", request_payload={}, fingerprint="abc", recorded_count=0)

    monkeypatch.setattr(cli, "replay_run", fake_replay_run)

    exit_code = cli.main(["replay", "run-1", "--entrypoint", "mod:fn", "--api-key", "k"])
    assert exit_code == 2
    assert "REPLAY DIVERGENCE" in capsys.readouterr().err


def test_cli_replayed_error_exits_2(monkeypatch, capsys):
    def fake_replay_run(*args, **kwargs):
        raise ReplayedError({"type": "RateLimitError", "message": "boom"})

    monkeypatch.setattr(cli, "replay_run", fake_replay_run)

    exit_code = cli.main(["replay", "run-1", "--entrypoint", "mod:fn", "--api-key", "k"])
    assert exit_code == 2
    assert "REPLAYED FAILURE" in capsys.readouterr().err


def test_cli_uses_env_api_key(monkeypatch):
    monkeypatch.setenv("AGENTREPLAY_API_KEY", "env-key")
    captured = {}

    def fake_replay_run(run_id, entrypoint, *, endpoint, api_key, timeout):
        captured["api_key"] = api_key
        return ReplayResult(run_id=run_id, session=_FakeSession(0), entrypoint_result=None)

    monkeypatch.setattr(cli, "replay_run", fake_replay_run)

    exit_code = cli.main(["replay", "run-1", "--entrypoint", "mod:fn"])
    assert exit_code == 0
    assert captured["api_key"] == "env-key"


def test_cli_requires_command():
    with pytest.raises(SystemExit):
        cli.main([])


# --- --file (Day 3 backlog: local-file trace loading) -----------------------


def test_cli_replay_with_file_success(monkeypatch, capsys):
    captured = {}

    def fake_replay_run_from_file(trace_file, entrypoint):
        captured["trace_file"] = trace_file
        captured["entrypoint"] = entrypoint
        return ReplayResult(run_id="from-file", session=_FakeSession(0), entrypoint_result="ok")

    monkeypatch.setattr(cli, "replay_run_from_file", fake_replay_run_from_file)

    exit_code = cli.main(["replay", "--file", "trace.json", "--entrypoint", "mod:fn"])
    assert exit_code == 0
    assert captured == {"trace_file": "trace.json", "entrypoint": "mod:fn"}
    assert "replay complete" in capsys.readouterr().out


def test_cli_replay_with_file_does_not_require_api_key(monkeypatch, capsys):
    monkeypatch.delenv("AGENTREPLAY_API_KEY", raising=False)
    monkeypatch.setattr(
        cli,
        "replay_run_from_file",
        lambda *a, **kw: ReplayResult(run_id="r", session=_FakeSession(0), entrypoint_result=None),
    )

    exit_code = cli.main(["replay", "--file", "trace.json", "--entrypoint", "mod:fn"])
    assert exit_code == 0


def test_cli_replay_both_run_id_and_file_exits_1(capsys):
    exit_code = cli.main(
        ["replay", "run-1", "--file", "trace.json", "--entrypoint", "mod:fn", "--api-key", "k"]
    )
    assert exit_code == 1
    assert "not both" in capsys.readouterr().err


def test_cli_replay_neither_run_id_nor_file_exits_1(capsys):
    exit_code = cli.main(["replay", "--entrypoint", "mod:fn"])
    assert exit_code == 1
    assert "provide either a run_id or --file" in capsys.readouterr().err


def test_cli_replay_with_file_trace_fetch_error_exits_1(monkeypatch, capsys):
    def fake_replay_run_from_file(*args, **kwargs):
        raise TraceFetchError("trace.json", "could not read trace file")

    monkeypatch.setattr(cli, "replay_run_from_file", fake_replay_run_from_file)

    exit_code = cli.main(["replay", "--file", "trace.json", "--entrypoint", "mod:fn"])
    assert exit_code == 1
    assert "could not read trace file" in capsys.readouterr().err
