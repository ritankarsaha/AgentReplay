from __future__ import annotations

import ast

import pytest

from agentreplay.testgen.test_template import (
    render_test_module,
    slugify_run_id,
    write_test_module,
)


def test_slugify_replaces_non_identifier_characters():
    # Leading underscore because the run id starts with a digit -- Python
    # identifiers can't, so this also covers the leading-digit case.
    assert slugify_run_id("754393b3-baac-4cd2-ae10-d437db4e1397") == (
        "_754393b3_baac_4cd2_ae10_d437db4e1397"
    )


def test_slugify_prefixes_leading_digit():
    slug = slugify_run_id("123abc")
    assert slug == "_123abc"
    assert slug.isidentifier()


def test_slugify_empty_string_falls_back_to_unknown():
    assert slugify_run_id("") == "unknown"


def test_slugify_result_is_always_a_valid_identifier():
    for run_id in ["754393b3-baac", "123", "a b c", "", "_already_valid", "run.id:weird"]:
        assert slugify_run_id(run_id).isidentifier()


# --- render_test_module -------------------------------------------------------


def test_render_test_module_is_valid_python():
    source = render_test_module(
        fixture_module="fixture_run_abc",
        entrypoint="examples.langgraph_demo:main",
        run_id="run-abc",
    )
    ast.parse(source)


def test_render_test_module_embeds_expected_values():
    source = render_test_module(
        fixture_module="fixture_run_abc",
        entrypoint="examples.langgraph_demo:main",
        run_id="run-abc",
    )
    assert "from fixture_run_abc import RECORDED_INPUT, TOOL_SPANS" in source
    assert "ENTRYPOINT = 'examples.langgraph_demo:main'" in source
    assert "def test_run_run_abc():" in source
    assert "mock_tools_mode(TOOL_SPANS)" in source
    assert "call_entrypoint_with_input(func, RECORDED_INPUT)" in source
    assert "TODO(agentreplay)" in source


def test_render_test_module_slugifies_run_id_in_test_name():
    source = render_test_module(
        fixture_module="fixture_run_x",
        entrypoint="mod:fn",
        run_id="754393b3-baac-4cd2",
    )
    assert "def test_run__754393b3_baac_4cd2():" in source


# --- render_test_module(assertion_spec=...) -- chunks 4.4 + 4.7 --------------


_STRUCTURAL_SPEC = {
    "must_call_tools": ["validate_output"],
    "must_not_call_tools": ["risky_tool"],
    "max_steps": 3,
    "no_exception": True,
    "rationale": "validate_output must run and risky_tool must never run",
    "semantic_rubric": None,
}


def test_render_test_module_with_spec_renders_real_structural_assertions():
    source = render_test_module(
        fixture_module="fixture_run_abc",
        entrypoint="mod:fn",
        run_id="run-abc",
        assertion_spec=_STRUCTURAL_SPEC,
    )
    ast.parse(source)
    assert "MUST_CALL_TOOLS = ['validate_output']" in source
    assert "MUST_NOT_CALL_TOOLS = ['risky_tool']" in source
    assert "MAX_STEPS = 3" in source
    assert "NO_EXCEPTION = True" in source
    assert "SEMANTIC_RUBRIC = None" in source
    assert "assert True" not in source
    assert "TODO(agentreplay)" not in source
    assert "from agentreplay.testgen import assertions" in source
    assert "assertions.assert_must_call_tools(tool_run, MUST_CALL_TOOLS)" in source
    assert "assertions.assert_semantic(result, SEMANTIC_RUBRIC)" in source


def test_render_test_module_captures_entrypoint_result_for_semantic_check():
    # Chunk 4.7 needs the entrypoint's actual return value to judge -- the
    # chunk 4.4 template discarded it entirely.
    source = render_test_module(
        fixture_module="fixture_run_abc", entrypoint="mod:fn", run_id="run-abc",
        assertion_spec=_STRUCTURAL_SPEC,
    )
    assert "result = call_entrypoint_with_input(func, RECORDED_INPUT)" in source


def test_render_test_module_with_semantic_rubric():
    spec = {**_STRUCTURAL_SPEC, "semantic_rubric": "Output must not contain '**'."}
    source = render_test_module(
        fixture_module="fixture_run_abc", entrypoint="mod:fn", run_id="run-abc",
        assertion_spec=spec,
    )
    ast.parse(source)
    assert "SEMANTIC_RUBRIC = \"Output must not contain '**'.\"" in source


def test_render_test_module_semantic_rubric_with_quotes_stays_valid_python():
    spec = {**_STRUCTURAL_SPEC, "semantic_rubric": "must not say \"sorry\" or use '**'"}
    source = render_test_module(
        fixture_module="fixture_run_abc", entrypoint="mod:fn", run_id="run-abc",
        assertion_spec=spec,
    )
    ast.parse(source)  # repr() picks safe quoting regardless of embedded quote chars


def test_render_test_module_no_spec_path_has_no_semantic_rubric_at_all():
    source = render_test_module(
        fixture_module="fixture_run_abc", entrypoint="mod:fn", run_id="run-abc"
    )
    assert "SEMANTIC_RUBRIC" not in source
    assert "assert_semantic" not in source


# --- write_test_module ---------------------------------------------------------


def test_write_test_module_creates_parent_dirs_and_writes_content(tmp_path):
    source = render_test_module(fixture_module="fixture_run_x", entrypoint="mod:fn", run_id="x")
    path = write_test_module(source, tmp_path / "nested" / "test_x.py")

    assert path.is_file()
    assert path.read_text() == source


def test_write_test_module_warns_on_overwrite_with_different_content(tmp_path, capsys):
    path = tmp_path / "test_x.py"
    path.write_text("# hand-edited test, not what generation would produce\n")

    source = render_test_module(fixture_module="fixture_run_x", entrypoint="mod:fn", run_id="x")
    write_test_module(source, path)

    assert "overwriting existing file with different content" in capsys.readouterr().err


def test_write_test_module_no_warning_for_a_new_file(tmp_path, capsys):
    source = render_test_module(fixture_module="fixture_run_x", entrypoint="mod:fn", run_id="x")
    write_test_module(source, tmp_path / "test_x.py")
    assert capsys.readouterr().err == ""
