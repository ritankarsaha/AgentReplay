

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from ..replay.store import RecordedRun

DEFAULT_SEMANTIC_JUDGE_MODEL = "claude-sonnet-4-6"

DEFAULT_SEMANTIC_JUDGE_NIM_MODEL = "meta/llama-3.1-8b-instruct"
DEFAULT_SEMANTIC_JUDGE_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
SEMANTIC_JUDGE_TOOL_NAME = "judge_output"


def assert_no_exception(exception: Optional[BaseException]) -> None:
    """Fail with a clear message if the entrypoint raised."""
    if exception is not None:
        raise AssertionError(
            f"expected the agent to complete without raising, but it raised: {exception!r}"
        ) from exception


def assert_must_call_tools(tool_run: RecordedRun, expected: Iterable[str]) -> None:
    """Fail if any tool name in `expected` was never actually invoked this run."""
    called = tool_run.called_sites()
    missing = [name for name in expected if name not in called]
    assert not missing, (
        f"expected these tools to be called but they weren't: {missing} "
        f"(tools actually called: {sorted(called)})"
    )


def assert_must_not_call_tools(tool_run: RecordedRun, forbidden: Iterable[str]) -> None:
    """Fail if any tool name in `forbidden` was actually invoked this run."""
    called = tool_run.called_sites()
    violated = [name for name in forbidden if name in called]
    assert not violated, f"expected these tools to never be called, but they were: {violated}"


def assert_max_steps(tool_run: RecordedRun, max_steps: Optional[int]) -> None:
    """Fail if more than `max_steps` tool-call steps were taken. No-op if `max_steps` is `None`."""
    if max_steps is None:
        return
    actual = tool_run.consumed_count()
    assert actual <= max_steps, f"expected at most {max_steps} tool-call step(s), agent took {actual}"


class SemanticJudgeNotConfigured(Exception):
    """Raised when `assert_semantic()` needs a judge call but can't make one.

    Deliberately an error (test ERRORS), not a silent pass — a missing
    `anthropic` package or `ANTHROPIC_API_KEY` in CI is a real, visible
    problem for a semantic-assertion test to surface, not something to
    quietly skip past.
    """


@dataclass
class SemanticJudgment:
    passes: bool
    reasoning: str


def _judge_tool_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "passes": {
                "type": "boolean",
                "description": "Whether the actual output satisfies the rubric.",
            },
            "reasoning": {
                "type": "string",
                "description": "1-2 sentences explaining the verdict.",
            },
        },
        "required": ["passes", "reasoning"],
    }


def _judge_system_prompt() -> str:
    return (
        "You are AgentReplay's semantic regression judge. You are given a "
        "rubric describing what a CORRECT agent output should look like for "
        "a specific recorded scenario, plus the actual output a real run just "
        "produced. Judge strictly against the rubric only — do not invent "
        "additional requirements beyond it. Always call the "
        f"`{SEMANTIC_JUDGE_TOOL_NAME}` tool with your verdict — never respond "
        "in plain text."
    )


def _judge_user_message(actual_output: Any, rubric: str) -> str:
    serialized = json.dumps(actual_output, default=str, indent=2)
    return f"Rubric:\n{rubric}\n\nActual output:\n{serialized}"


def _judge_with_anthropic(actual_output: Any, rubric: str, *, model: str) -> SemanticJudgment:
    try:
        import anthropic
    except ImportError as exc:
        raise SemanticJudgeNotConfigured(
            "the 'anthropic' package is required for the anthropic semantic-judge "
            "backend (pip install anthropic)"
        ) from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SemanticJudgeNotConfigured(
            "ANTHROPIC_API_KEY is not set — required for the anthropic semantic-judge "
            "backend (AGENTREPLAY_SEMANTIC_JUDGE_BACKEND=anthropic, the default)"
        )

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=512,
        system=_judge_system_prompt(),
        tools=[
            {
                "name": SEMANTIC_JUDGE_TOOL_NAME,
                "description": "Judge whether the actual output satisfies the rubric.",
                "input_schema": _judge_tool_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": SEMANTIC_JUDGE_TOOL_NAME},
        messages=[{"role": "user", "content": _judge_user_message(actual_output, rubric)}],
    )
    tool_use = next(block for block in response.content if block.type == "tool_use")
    return SemanticJudgment(
        passes=bool(tool_use.input.get("passes")),
        reasoning=str(tool_use.input.get("reasoning") or ""),
    )


def _judge_with_nim(actual_output: Any, rubric: str, *, model: str) -> SemanticJudgment:
    try:
        import openai
    except ImportError as exc:
        raise SemanticJudgeNotConfigured(
            "the 'openai' package is required for the NIM semantic-judge backend "
            "(pip install openai)"
        ) from exc

    api_key = os.environ.get("AGENTREPLAY_SEMANTIC_JUDGE_NIM_API_KEY")
    if not api_key:
        raise SemanticJudgeNotConfigured(
            "AGENTREPLAY_SEMANTIC_JUDGE_NIM_API_KEY is not set — required for the NIM "
            "semantic-judge backend (AGENTREPLAY_SEMANTIC_JUDGE_BACKEND=nim)"
        )

    client = openai.OpenAI(api_key=api_key, base_url=DEFAULT_SEMANTIC_JUDGE_NIM_BASE_URL)
    response = client.chat.completions.create(
        model=model,
        max_tokens=512,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": SEMANTIC_JUDGE_TOOL_NAME,
                    "description": "Judge whether the actual output satisfies the rubric.",
                    "parameters": _judge_tool_schema(),
                },
            }
        ],
        tool_choice={"type": "function", "function": {"name": SEMANTIC_JUDGE_TOOL_NAME}},
        messages=[
            {"role": "system", "content": _judge_system_prompt()},
            {"role": "user", "content": _judge_user_message(actual_output, rubric)},
        ],
    )
    tool_call = response.choices[0].message.tool_calls[0]
    arguments = json.loads(tool_call.function.arguments)
    return SemanticJudgment(
        passes=bool(arguments.get("passes")),
        reasoning=str(arguments.get("reasoning") or ""),
    )


def _default_judge(actual_output: Any, rubric: str, *, model: Optional[str] = None) -> SemanticJudgment:
    """Dispatches to `AGENTREPLAY_SEMANTIC_JUDGE_BACKEND` (`"anthropic"` default, or
    `"nim"`) — see this module's docstring for why this is swappable at all.
    """
    backend = os.environ.get("AGENTREPLAY_SEMANTIC_JUDGE_BACKEND", "anthropic")
    if backend == "nim":
        return _judge_with_nim(actual_output, rubric, model=model or DEFAULT_SEMANTIC_JUDGE_NIM_MODEL)
    return _judge_with_anthropic(actual_output, rubric, model=model or DEFAULT_SEMANTIC_JUDGE_MODEL)


def assert_semantic(
    actual_output: Any,
    rubric: Optional[str],
    *,
    judge_fn: Callable[[Any, str], SemanticJudgment] = _default_judge,
) -> None:
    """Fail if an LLM judge rejects `actual_output` against `rubric`. No-op if `rubric` is falsy.

    `rubric` being `None`/empty is the common case (CLAUDE.md §3.6: semantic
    is the secondary, escalation-only tier — most failures are fully
    captured by the structural checks above) — not an error.
    """
    if not rubric:
        return
    judgment = judge_fn(actual_output, rubric)
    assert judgment.passes, f"semantic judge rejected the output: {judgment.reasoning}"


def run_assertion_spec(
    spec: Optional[dict],
    *,
    tool_run: RecordedRun,
    result: Any,
    exception: Optional[BaseException],
) -> None:
    """Run every check in an assertion spec, same order/skip semantics as the
    rendered pytest file — a no-op if `spec` is falsy. Shared by
    `test_template.py`'s rendered tests and the N-trial regression runner so
    both judge a spec identically.
    """
    if not spec:
        return
    if bool(spec.get("no_exception", True)):
        assert_no_exception(exception)
    assert_must_call_tools(tool_run, spec.get("must_call_tools") or [])
    assert_must_not_call_tools(tool_run, spec.get("must_not_call_tools") or [])
    assert_max_steps(tool_run, spec.get("max_steps"))
    assert_semantic(result, spec.get("semantic_rubric"))
