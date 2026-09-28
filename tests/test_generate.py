from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentreplay.fingerprint import compute_fingerprint
from agentreplay.span import Span
from agentreplay.testgen.fixture import load_fixture_module
from agentreplay.testgen.generate import GeneratedTest, generate_test, generate_test_from_file
from agentreplay.tool import _build_tool_payload

T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc)

_THIS_DIR = Path(__file__).parent


def _root_span(input_: dict) -> dict:
    return Span(
        id="root-1", run_id="run-1", parent_id=None, type="checkpoint", name="entrypoint_input",
        input=input_, output=None, error=None, started_at=T0, duration_ms=0.0, fingerprint="fp-root",
    ).to_dict()


def _tool_span(tool_name: str, args: tuple, output) -> dict:
    fp = compute_fingerprint({"tool": tool_name, "input": _build_tool_payload(args, {})})
    return Span(
        id="tool-1", run_id="run-1", parent_id="root-1", type="tool", name=tool_name,
        input=_build_tool_payload(args, {}), output=output, error=None,
        started_at=T1, duration_ms=1.0, fingerprint=fp,
    ).to_dict()


# --- generate_test (ingest API path) ----------------------------------------


def test_generate_test_writes_fixture_and_test_as_siblings(monkeypatch, tmp_path):
    root = _root_span({"job_posting": "hi"})
    tool = _tool_span("search", ("q",), "result")

    def fake_fetch_run(run_id, *, endpoint, api_key, timeout):
        return {"id": run_id, "spans": [root, tool]}

    # generate_test() (chunk 4.4 onward) calls fetch_run() directly from
    # agentreplay.testgen.generate -- patch it there, not in fixture.py (it
    # no longer delegates to generate_fixture(), see generate.py's docstring).
    monkeypatch.setattr("agentreplay.testgen.generate.fetch_run", fake_fetch_run)

    result = generate_test(
        "run-123",
        "_testgen_entrypoint_fixture:zero_arg_main",
        tmp_path,
        endpoint="http://x",
        api_key="k",
    )

    assert isinstance(result, GeneratedTest)
    assert result.run_id == "run-123"
    assert result.fixture_path == tmp_path / "fixture_run_123.py"
    assert result.test_path == tmp_path / "test_run_123.py"
    assert result.fixture_path.is_file()
    assert result.test_path.is_file()
    assert len(result.fixture.tool_spans) == 1
    assert result.assertion_spec is None

    loaded = load_fixture_module(result.fixture_path)
    assert loaded.recorded_input == {"job_posting": "hi"}

    test_source = result.test_path.read_text()
    assert "from fixture_run_123 import RECORDED_INPUT, TOOL_SPANS" in test_source
    assert "ENTRYPOINT = '_testgen_entrypoint_fixture:zero_arg_main'" in test_source
    assert "assert True" in test_source  # no assertion_spec -> chunk 4.2 placeholder


def test_generate_test_picks_up_assertion_spec_from_diagnosis(monkeypatch, tmp_path):
    root = _root_span({"job_posting": "hi"})
    tool = _tool_span("search", ("q",), "result")
    spec = {
        "must_call_tools": ["search"],
        "must_not_call_tools": [],
        "max_steps": None,
        "no_exception": True,
        "rationale": "search must be called",
    }

    def fake_fetch_run(run_id, *, endpoint, api_key, timeout):
        return {"id": run_id, "spans": [root, tool], "diagnosis": {"assertion_spec": spec}}

    monkeypatch.setattr("agentreplay.testgen.generate.fetch_run", fake_fetch_run)

    result = generate_test(
        "run-123", "_testgen_entrypoint_fixture:zero_arg_main", tmp_path,
        endpoint="http://x", api_key="k",
    )

    assert result.assertion_spec == spec
    test_source = result.test_path.read_text()
    assert "MUST_CALL_TOOLS = ['search']" in test_source
    assert "assert True" not in test_source
    assert "from agentreplay.testgen import assertions" in test_source


def test_generate_test_rejects_bad_entrypoint_before_writing_anything(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "agentreplay.testgen.generate.fetch_run",
        lambda *a, **kw: pytest.fail("fetch_run should not be called for a bad entrypoint"),
    )

    with pytest.raises(ValueError, match="expected 'module.path:function_name'"):
        generate_test("run-x", "no-colon-here", tmp_path, endpoint="http://x", api_key="k")

    assert list(tmp_path.iterdir()) == []


def test_generate_test_propagates_trace_fetch_error(monkeypatch, tmp_path):
    from agentreplay.replay.exceptions import TraceFetchError

    monkeypatch.setattr(
        "agentreplay.testgen.generate.fetch_run",
        lambda *a, **kw: (_ for _ in ()).throw(TraceFetchError("run-x", "404 not found")),
    )

    with pytest.raises(TraceFetchError):
        generate_test(
            "run-x",
            "_testgen_entrypoint_fixture:zero_arg_main",
            tmp_path,
            endpoint="http://x",
            api_key="k",
        )


# --- generate_test_from_file (local file path) -------------------------------


def test_generate_test_from_file_writes_fixture_and_test_as_siblings(tmp_path):
    root = _root_span({"term": "widget"})
    tool = _tool_span("lookup", ("widget",), "looked-up-widget")
    trace_file = tmp_path / "trace.json"
    trace_file.write_text(json.dumps({"id": "run-from-file", "spans": [root, tool]}))

    output_dir = tmp_path / "out"
    result = generate_test_from_file(
        trace_file, "_testgen_entrypoint_fixture:zero_arg_main", output_dir
    )

    assert result.run_id == "run-from-file"
    assert result.fixture_path == output_dir / "fixture_run_from_file.py"
    assert result.test_path == output_dir / "test_run_from_file.py"
    assert result.fixture_path.is_file()
    assert result.test_path.is_file()
    assert result.assertion_spec is None


def test_generate_test_from_file_picks_up_assertion_spec_from_diagnosis(tmp_path):
    root = _root_span({"term": "widget"})
    tool = _tool_span("lookup", ("widget",), "looked-up-widget")
    spec = {
        "must_call_tools": [],
        "must_not_call_tools": ["lookup"],
        "max_steps": 3,
        "no_exception": False,
        "rationale": "lookup should never be called for this scenario",
    }
    trace_file = tmp_path / "trace.json"
    trace_file.write_text(
        json.dumps(
            {"id": "run-from-file", "spans": [root, tool], "diagnosis": {"assertion_spec": spec}}
        )
    )

    output_dir = tmp_path / "out"
    result = generate_test_from_file(
        trace_file, "_testgen_entrypoint_fixture:zero_arg_main", output_dir
    )

    assert result.assertion_spec == spec
    test_source = result.test_path.read_text()
    assert "MUST_NOT_CALL_TOOLS = ['lookup']" in test_source
    assert "MAX_STEPS = 3" in test_source
    assert "NO_EXCEPTION = False" in test_source


def test_generate_test_from_file_rejects_bad_entrypoint_before_writing_anything(tmp_path):
    trace_file = tmp_path / "trace.json"
    trace_file.write_text(json.dumps({"id": "run-x", "spans": []}))
    output_dir = tmp_path / "out"

    with pytest.raises(ValueError, match="expected 'module.path:function_name'"):
        generate_test_from_file(trace_file, "no-colon-here", output_dir)

    assert not output_dir.exists()


def test_generate_test_from_file_falls_back_to_path_as_run_id(tmp_path):
    trace_file = tmp_path / "trace.json"
    trace_file.write_text(json.dumps({"spans": []}))
    output_dir = tmp_path / "out"

    result = generate_test_from_file(
        trace_file, "_testgen_entrypoint_fixture:zero_arg_main", output_dir
    )
    assert result.run_id == str(trace_file)


# --- full integration: run the generated file through a real pytest --------


def test_generated_test_actually_passes_under_real_pytest(tmp_path):
    """The chunk 4.6-style proof, scoped to 4.2: a generated test, executed by
    a real `pytest` subprocess, mocks the recorded tool call (the real
    `lookup()` body would raise if it ran) and calls the entrypoint with the
    recorded input -- end to end, not just unit-testing the renderer.
    """
    root = _root_span({"term": "widget"})
    tool = _tool_span("lookup", ("widget",), "looked-up-widget")
    trace_file = tmp_path / "trace.json"
    trace_file.write_text(json.dumps({"id": "run-integration", "spans": [root, tool]}))

    result = generate_test_from_file(
        trace_file, "_testgen_entrypoint_fixture:main", tmp_path
    )
    # The entrypoint fixture module must be a sibling for pytest's default
    # rootdir-relative import mode to resolve `resolve_entrypoint()`'s
    # `importlib.import_module("_testgen_entrypoint_fixture")` at test-run time.
    shutil.copy(_THIS_DIR / "_testgen_entrypoint_fixture.py", tmp_path)

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(result.test_path), "-q"],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert "1 passed" in proc.stdout


def _run_generated_test(tmp_path, spec: dict) -> subprocess.CompletedProcess:
    root = _root_span({"term": "widget"})
    tool = _tool_span("lookup", ("widget",), "looked-up-widget")
    trace_file = tmp_path / "trace.json"
    trace_file.write_text(
        json.dumps(
            {
                "id": "run-integration-spec",
                "spans": [root, tool],
                "diagnosis": {"assertion_spec": spec},
            }
        )
    )

    result = generate_test_from_file(trace_file, "_testgen_entrypoint_fixture:main", tmp_path)
    shutil.copy(_THIS_DIR / "_testgen_entrypoint_fixture.py", tmp_path)

    return subprocess.run(
        [sys.executable, "-m", "pytest", str(result.test_path), "-q"],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_generated_test_with_assertion_spec_passes_when_spec_is_satisfied(tmp_path):
    """Chunk 4.4's real proof: a generated test with a real spec, run by a
    real pytest subprocess, passes when the agent's actual behavior (the
    fixture entrypoint genuinely calls `lookup`) satisfies the spec.
    """
    proc = _run_generated_test(
        tmp_path,
        {
            "must_call_tools": ["lookup"],
            "must_not_call_tools": [],
            "max_steps": 5,
            "no_exception": True,
            "rationale": "lookup must be called to resolve the term",
        },
    )
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert "1 passed" in proc.stdout


def test_generated_test_with_assertion_spec_fails_when_spec_is_violated(tmp_path):
    """The other half of the proof: the same real entrypoint, same real
    pytest run, but a spec that the real behavior actually violates
    (`must_not_call_tools=["lookup"]`, while the fixture entrypoint does
    call it) -- must FAIL, with a clear message identifying which check.
    """
    proc = _run_generated_test(
        tmp_path,
        {
            "must_call_tools": [],
            "must_not_call_tools": ["lookup"],
            "max_steps": None,
            "no_exception": True,
            "rationale": "lookup should never be called for this (made-up) scenario",
        },
    )
    assert proc.returncode != 0, f"expected failure but got:\nstdout:\n{proc.stdout}"
    assert "1 failed" in proc.stdout
    assert "expected these tools to never be called" in proc.stdout
    assert "lookup" in proc.stdout
