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


class _FakeFixtureData:
    def __init__(self, run_id="run-1", tool_spans=None) -> None:
        self.run_id = run_id
        self.tool_spans = tool_spans or []


def test_cli_fixture_success(monkeypatch, capsys):
    captured = {}

    def fake_generate_fixture(run_id, output, *, endpoint, api_key, timeout):
        captured.update(run_id=run_id, output=output, endpoint=endpoint, api_key=api_key)
        return _FakeFixtureData(run_id=run_id, tool_spans=[{"id": "t1"}])

    monkeypatch.setattr(cli, "generate_fixture", fake_generate_fixture)

    exit_code = cli.main(["fixture", "run-1", "--output", "out.py", "--api-key", "k"])
    assert exit_code == 0
    assert captured["run_id"] == "run-1"
    assert captured["output"] == "out.py"
    out = capsys.readouterr().out
    assert "wrote fixture for run run-1" in out
    assert "1 recorded tool call(s)" in out


def test_cli_fixture_missing_api_key_exits_1(monkeypatch, capsys):
    monkeypatch.delenv("AGENTREPLAY_API_KEY", raising=False)

    exit_code = cli.main(["fixture", "run-1", "--output", "out.py"])
    assert exit_code == 1
    assert "no API key" in capsys.readouterr().err


def test_cli_fixture_uses_env_api_key(monkeypatch):
    monkeypatch.setenv("AGENTREPLAY_API_KEY", "env-key")
    captured = {}

    def fake_generate_fixture(run_id, output, *, endpoint, api_key, timeout):
        captured["api_key"] = api_key
        return _FakeFixtureData(run_id=run_id)

    monkeypatch.setattr(cli, "generate_fixture", fake_generate_fixture)

    exit_code = cli.main(["fixture", "run-1", "--output", "out.py"])
    assert exit_code == 0
    assert captured["api_key"] == "env-key"


def test_cli_fixture_run_id_and_file_mutually_exclusive(capsys):
    exit_code = cli.main(
        ["fixture", "run-1", "--file", "trace.json", "--output", "out.py"]
    )
    assert exit_code == 1
    assert "not both" in capsys.readouterr().err


def test_cli_fixture_neither_run_id_nor_file_exits_1(capsys):
    exit_code = cli.main(["fixture", "--output", "out.py"])
    assert exit_code == 1
    assert "provide either a run_id or --file" in capsys.readouterr().err


def test_cli_fixture_with_file_success(monkeypatch, capsys):
    captured = {}

    def fake_generate_fixture_from_file(trace_file, output):
        captured.update(trace_file=trace_file, output=output)
        return _FakeFixtureData(run_id="from-file")

    monkeypatch.setattr(cli, "generate_fixture_from_file", fake_generate_fixture_from_file)

    exit_code = cli.main(["fixture", "--file", "trace.json", "--output", "out.py"])
    assert exit_code == 0
    assert captured == {"trace_file": "trace.json", "output": "out.py"}
    assert "wrote fixture for run from-file" in capsys.readouterr().out


def test_cli_fixture_with_file_does_not_require_api_key(monkeypatch, capsys):
    monkeypatch.delenv("AGENTREPLAY_API_KEY", raising=False)
    monkeypatch.setattr(
        cli, "generate_fixture_from_file", lambda *a, **kw: _FakeFixtureData(run_id="from-file")
    )

    exit_code = cli.main(["fixture", "--file", "trace.json", "--output", "out.py"])
    assert exit_code == 0


def test_cli_fixture_trace_fetch_error_exits_1(monkeypatch, capsys):
    def fake_generate_fixture(*args, **kwargs):
        raise TraceFetchError("run-1", "404 not found")

    monkeypatch.setattr(cli, "generate_fixture", fake_generate_fixture)

    exit_code = cli.main(["fixture", "run-1", "--output", "out.py", "--api-key", "k"])
    assert exit_code == 1
    assert "404 not found" in capsys.readouterr().err


# --- generate-test (chunk 4.2) ----------------------------------------------


class _FakeGeneratedTest:
    def __init__(
        self,
        run_id="run-1",
        fixture_path="fixture.py",
        test_path="test.py",
        tool_spans=None,
        assertion_spec=None,
    ):
        self.run_id = run_id
        self.fixture_path = fixture_path
        self.test_path = test_path
        self.assertion_spec = assertion_spec

        class _Fixture:
            pass

        self.fixture = _Fixture()
        self.fixture.tool_spans = tool_spans or []


def test_cli_generate_test_success(monkeypatch, capsys):
    captured = {}

    def fake_generate_test(run_id, entrypoint, output_dir, *, endpoint, api_key, timeout):
        captured.update(
            run_id=run_id, entrypoint=entrypoint, output_dir=output_dir,
            endpoint=endpoint, api_key=api_key,
        )
        return _FakeGeneratedTest(
            run_id=run_id, fixture_path="d/fixture_run_1.py", test_path="d/test_run_1.py",
            tool_spans=[{"id": "t1"}],
        )

    monkeypatch.setattr(cli, "generate_test", fake_generate_test)

    exit_code = cli.main(
        ["generate-test", "run-1", "--entrypoint", "mod:fn", "--output-dir", "d", "--api-key", "k"]
    )
    assert exit_code == 0
    assert captured["run_id"] == "run-1"
    assert captured["entrypoint"] == "mod:fn"
    assert captured["output_dir"] == "d"
    out = capsys.readouterr().out
    assert "wrote fixture d/fixture_run_1.py and test d/test_run_1.py" in out
    assert "with a placeholder assertion" in out


def test_cli_generate_test_success_reports_structural_assertions(monkeypatch, capsys):
    def fake_generate_test(run_id, entrypoint, output_dir, *, endpoint, api_key, timeout):
        return _FakeGeneratedTest(assertion_spec={"must_call_tools": ["validate_output"]})

    monkeypatch.setattr(cli, "generate_test", fake_generate_test)

    exit_code = cli.main(
        ["generate-test", "run-1", "--entrypoint", "mod:fn", "--output-dir", "d", "--api-key", "k"]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "with generated structural assertions (chunk 4.4)" in out


def test_cli_generate_test_success_reports_semantic_assertions(monkeypatch, capsys):
    def fake_generate_test(run_id, entrypoint, output_dir, *, endpoint, api_key, timeout):
        return _FakeGeneratedTest(
            assertion_spec={"must_call_tools": [], "semantic_rubric": "no markdown artifacts"}
        )

    monkeypatch.setattr(cli, "generate_test", fake_generate_test)

    exit_code = cli.main(
        ["generate-test", "run-1", "--entrypoint", "mod:fn", "--output-dir", "d", "--api-key", "k"]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "with generated structural + semantic assertions (chunks 4.4+4.7)" in out


def test_cli_generate_test_missing_api_key_exits_1(monkeypatch, capsys):
    monkeypatch.delenv("AGENTREPLAY_API_KEY", raising=False)

    exit_code = cli.main(
        ["generate-test", "run-1", "--entrypoint", "mod:fn", "--output-dir", "d"]
    )
    assert exit_code == 1
    assert "no API key" in capsys.readouterr().err


def test_cli_generate_test_uses_env_api_key(monkeypatch):
    monkeypatch.setenv("AGENTREPLAY_API_KEY", "env-key")
    captured = {}

    def fake_generate_test(run_id, entrypoint, output_dir, *, endpoint, api_key, timeout):
        captured["api_key"] = api_key
        return _FakeGeneratedTest(run_id=run_id)

    monkeypatch.setattr(cli, "generate_test", fake_generate_test)

    exit_code = cli.main(["generate-test", "run-1", "--entrypoint", "mod:fn", "--output-dir", "d"])
    assert exit_code == 0
    assert captured["api_key"] == "env-key"


def test_cli_generate_test_run_id_and_file_mutually_exclusive(capsys):
    exit_code = cli.main(
        ["generate-test", "run-1", "--file", "trace.json", "--entrypoint", "mod:fn", "--output-dir", "d"]
    )
    assert exit_code == 1
    assert "not both" in capsys.readouterr().err


def test_cli_generate_test_neither_run_id_nor_file_exits_1(capsys):
    exit_code = cli.main(["generate-test", "--entrypoint", "mod:fn", "--output-dir", "d"])
    assert exit_code == 1
    assert "provide either a run_id or --file" in capsys.readouterr().err


def test_cli_generate_test_with_file_success(monkeypatch, capsys):
    captured = {}

    def fake_generate_test_from_file(trace_file, entrypoint, output_dir):
        captured.update(trace_file=trace_file, entrypoint=entrypoint, output_dir=output_dir)
        return _FakeGeneratedTest(run_id="from-file")

    monkeypatch.setattr(cli, "generate_test_from_file", fake_generate_test_from_file)

    exit_code = cli.main(
        ["generate-test", "--file", "trace.json", "--entrypoint", "mod:fn", "--output-dir", "d"]
    )
    assert exit_code == 0
    assert captured == {"trace_file": "trace.json", "entrypoint": "mod:fn", "output_dir": "d"}
    assert "wrote fixture" in capsys.readouterr().out


def test_cli_generate_test_with_file_does_not_require_api_key(monkeypatch, capsys):
    monkeypatch.delenv("AGENTREPLAY_API_KEY", raising=False)
    monkeypatch.setattr(
        cli, "generate_test_from_file", lambda *a, **kw: _FakeGeneratedTest(run_id="from-file")
    )

    exit_code = cli.main(
        ["generate-test", "--file", "trace.json", "--entrypoint", "mod:fn", "--output-dir", "d"]
    )
    assert exit_code == 0


def test_cli_generate_test_trace_fetch_error_exits_1(monkeypatch, capsys):
    def fake_generate_test(*args, **kwargs):
        raise TraceFetchError("run-1", "404 not found")

    monkeypatch.setattr(cli, "generate_test", fake_generate_test)

    exit_code = cli.main(
        ["generate-test", "run-1", "--entrypoint", "mod:fn", "--output-dir", "d", "--api-key", "k"]
    )
    assert exit_code == 1
    assert "404 not found" in capsys.readouterr().err


def test_cli_generate_test_bad_entrypoint_exits_1(monkeypatch, capsys):
    def fake_generate_test(*args, **kwargs):
        raise ValueError("bad spec")

    monkeypatch.setattr(cli, "generate_test", fake_generate_test)

    exit_code = cli.main(
        ["generate-test", "run-1", "--entrypoint", "bad", "--output-dir", "d", "--api-key", "k"]
    )
    assert exit_code == 1
    assert "bad spec" in capsys.readouterr().err
