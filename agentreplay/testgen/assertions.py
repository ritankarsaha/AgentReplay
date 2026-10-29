

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from ..replay.store import RecordedRun

DEFAULT_SEMANTIC_JUDGE_MODEL = "claude-sonnet-4-6"

DEFAULT_SEMANTIC_JUDGE_NIM_MODEL = "meta/llama-3.1-8b-instruct"
DEFAULT_SEMANTIC_JUDGE_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_SEMANTIC_JUDGE_META_MODEL = "muse-spark-1.3"
DEFAULT_SEMANTIC_JUDGE_META_BASE_URL = "https://api.meta.ai/v1"
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


_MISSING = object()


def _resolve_path(value: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part, _MISSING)
        else:
            value = getattr(value, part, _MISSING)
        if value is _MISSING or value is None:
            return _MISSING if value is _MISSING else None
    return value


def _minutes(clock: str) -> int:
    hours, minutes = clock[-5:].split(":")
    return int(hours) * 60 + int(minutes)


def _check_one(result: Any, check: dict) -> Optional[str]:
    path, op = check["path"], check["op"]
    value = _resolve_path(result, path)
    if value is _MISSING or value is None:
        return None if check.get("allow_missing") else f"'{path}' is missing from the agent output"
    label = check.get("description") or f"{path} {op}"
    if op == "time_in_window":
        moment = _minutes(str(value))
        if not _minutes(check["start"]) <= moment < _minutes(check["end"]):
            return f"{label}: got {value!r}, expected a time in [{check['start']}, {check['end']})"
    elif op == "lte":
        if not value <= check["value"]:
            return f"{label}: got {value!r}, expected <= {check['value']!r}"
    elif op == "eq":
        if value != check["value"]:
            return f"{label}: got {value!r}, expected {check['value']!r}"
    else:
        return f"unknown output check op {op!r}"
    return None


def assert_output_checks(result: Any, checks: Optional[Iterable[dict]]) -> None:
    """Fail if any structured check on the agent's returned value does not hold."""
    failures = [message for check in checks or [] if (message := _check_one(result, check))]
    assert not failures, "output checks failed: " + "; ".join(failures)


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


def _judge_with_meta(
    actual_output: Any,
    rubric: str,
    *,
    model: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> SemanticJudgment:
    """Meta rejects a forced `tool_choice` and spends reasoning tokens against
    `max_tokens`, so this uses "auto", a generous cap, and a JSON-text fallback."""
    try:
        import openai
    except ImportError as exc:
        raise SemanticJudgeNotConfigured(
            "the 'openai' package is required for the meta semantic-judge backend "
            "(pip install openai)"
        ) from exc

    api_key = (
        api_key
        or os.environ.get("AGENTREPLAY_SEMANTIC_JUDGE_META_API_KEY")
        or os.environ.get("META_API_KEY")
    )
    if not api_key:
        raise SemanticJudgeNotConfigured(
            "AGENTREPLAY_SEMANTIC_JUDGE_META_API_KEY (or META_API_KEY) is not set — required "
            "for the meta semantic-judge backend (AGENTREPLAY_SEMANTIC_JUDGE_BACKEND=meta)"
        )
    base_url = base_url or os.environ.get("META_BASE_URL") or DEFAULT_SEMANTIC_JUDGE_META_BASE_URL

    client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=120.0)
    response = client.chat.completions.create(
        model=model,
        max_tokens=4096,
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
        tool_choice="auto",
        messages=[
            {"role": "system", "content": _judge_system_prompt()},
            {"role": "user", "content": _judge_user_message(actual_output, rubric)},
        ],
    )
    message = response.choices[0].message
    arguments = None
    for call in message.tool_calls or []:
        if call.function.name == SEMANTIC_JUDGE_TOOL_NAME:
            arguments = json.loads(call.function.arguments)
            break
    if arguments is None and message.content:
        start, end = message.content.find("{"), message.content.rfind("}")
        if start != -1 and end > start:
            try:
                arguments = json.loads(message.content[start : end + 1])
            except json.JSONDecodeError:
                arguments = None
    if not isinstance(arguments, dict):
        raise SemanticJudgeNotConfigured(
            f"{model} returned neither a `{SEMANTIC_JUDGE_TOOL_NAME}` call nor a JSON verdict"
        )
    return SemanticJudgment(
        passes=bool(arguments.get("passes")),
        reasoning=str(arguments.get("reasoning") or ""),
    )


def _default_judge(actual_output: Any, rubric: str, *, model: Optional[str] = None) -> SemanticJudgment:
    """Dispatches to `AGENTREPLAY_SEMANTIC_JUDGE_BACKEND` (`"anthropic"` default,
    `"nim"`, or `"meta"`) — see this module's docstring for why this is swappable at all.
    """
    backend = os.environ.get("AGENTREPLAY_SEMANTIC_JUDGE_BACKEND", "anthropic")
    if backend == "meta":
        return _judge_with_meta(actual_output, rubric, model=model or DEFAULT_SEMANTIC_JUDGE_META_MODEL)
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
    assert_output_checks(result, spec.get("output_checks"))
    assert_semantic(result, spec.get("semantic_rubric"))
