

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Callable, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from .classifier import build_trace_summary
from .config import Settings
from .models import Run

ASSERTION_SPEC_TOOL_NAME = "generate_assertion_spec"


class AssertionSpecNotConfigured(Exception):
    """Raised when the configured backend (`settings.assertion_spec_backend`)
    has no API key set — same shape as `classifier.ClassifierNotConfigured`.
    """


class RunNotClassifiedError(Exception):
    """Raised when asked to generate a spec for a run chunk 3.6 hasn't classified yet.

    CLAUDE.md's pipeline is Classifier -> Test Generator, in that order
    (§2's architecture diagram, §3.6's "one click on a classified
    failure") — there's no diagnosis to build a spec from otherwise.
    """

    def __init__(self, run_id: str) -> None:
        super().__init__(f"run '{run_id}' has not been classified yet (chunk 3.6)")
        self.run_id = run_id


@dataclass
class AssertionSpec:
    must_call_tools: List[str]
    must_not_call_tools: List[str]
    max_steps: Optional[int]
    no_exception: bool
    rationale: str
    model: str
    # `semantic` tier (CLAUDE.md §3.6/§4 chunk 4.7) -- an LLM-judge rubric
    # for failures that aren't reducible to tool-call shape (which tools ran,
    # how many times, whether anything raised) but are about output
    # *content* being wrong (chunk 4.6 found exactly this gap: a tool
    # returning garbled output passes every structural check above).
    # `None` when the structural fields alone fully capture the failure --
    # layered on top of, not instead of, the structural tier.
    semantic_rubric: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "must_call_tools": self.must_call_tools,
            "must_not_call_tools": self.must_not_call_tools,
            "max_steps": self.max_steps,
            "no_exception": self.no_exception,
            "rationale": self.rationale,
            "model": self.model,
            "semantic_rubric": self.semantic_rubric,
        }


def _tool_input_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "must_call_tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Tool span `name`s -- ONLY from trace lines showing `type=tool`, "
                    "copied verbatim -- that a CORRECTED agent run must call for this "
                    "exact scenario. NEVER include a `type=node`, `type=llm`, or "
                    "`type=checkpoint` span's name here, even if it seems central to "
                    "the failure -- this field is for tool calls only. Empty array if "
                    "no tool-call requirement applies, or if the trace has no "
                    "`type=tool` spans at all."
                ),
            },
            "must_not_call_tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Tool span `name`s -- ONLY from trace lines showing `type=tool` "
                    "-- that a CORRECTED run must NEVER call even ONCE for this "
                    "scenario -- use ONLY when the tool itself is "
                    "wrong/erroneous to call at all (e.g. it called the wrong tool "
                    "entirely, or a tool that should never have been reached given "
                    "the input). Do NOT use this for a tool that was called too "
                    "MANY TIMES -- that tool should still appear in "
                    "`must_call_tools` (it's legitimately needed), with the repeat-"
                    "call problem captured by `max_steps` instead. Empty array if "
                    "not applicable."
                ),
            },
            "max_steps": {
                "type": ["integer", "null"],
                "description": (
                    "Maximum total number of recorded tool-call spans a corrected "
                    "run should take, or null if step count isn't diagnostic for "
                    "this failure. REQUIRED (not null) whenever the diagnosis "
                    "describes a tool being called more times than it should be "
                    "(step repetition / looping / runaway calls) -- set it to the "
                    "correct, lower call count, and put that tool in "
                    "`must_call_tools` too, since it's still a legitimately needed "
                    "call, just not a repeated one."
                ),
            },
            "no_exception": {
                "type": "boolean",
                "description": (
                    "Whether a corrected run must complete without raising an "
                    "unhandled exception."
                ),
            },
            "semantic_rubric": {
                "type": ["string", "null"],
                "description": (
                    "A short rubric for an LLM judge to evaluate the agent's "
                    "actual final output against, for failures that are about "
                    "output CONTENT being wrong/malformed rather than which "
                    "tools ran (e.g. \"the parsed keyword list must not contain "
                    "leftover markdown formatting like '**'\"). null if the "
                    "structural fields above already fully capture this "
                    "failure -- do not invent a rubric just to fill this field."
                ),
            },
            "rationale": {
                "type": "string",
                "description": (
                    "1-3 sentences for a human reviewing the generated test: why "
                    "these specific checks were chosen for this failure."
                ),
            },
        },
        "required": [
            "must_call_tools",
            "must_not_call_tools",
            "max_steps",
            "no_exception",
            "semantic_rubric",
            "rationale",
        ],
    }


def _system_prompt() -> str:
    return (
        "You are AgentReplay's assertion-spec generator. You are given the "
        "full recorded trace of an AI agent run that has already been "
        "classified as a failure, plus the classifier's diagnosis. Propose a "
        "regression-test assertion spec with two tiers (CLAUDE.md §3.6's "
        "escalating assertion types, layered together, not either/or):\n\n"
        "1. STRUCTURAL (always consider these first): concrete, "
        "mechanically-checkable conditions on the agent's CONTROL FLOW -- "
        "tool-call requirements, a step-count ceiling, and/or an "
        "exception-free requirement. Never propose exact string-equality "
        "checks on LLM output here (too brittle). IMPORTANT: if the "
        "diagnosis describes a tool being called too MANY times (step "
        "repetition/looping), that tool is still legitimately needed -- put "
        "it in `must_call_tools` AND set `max_steps` to the correct lower "
        "count. `must_not_call_tools` is ONLY for a tool that should never "
        "be called at all, not one that's just called too often. Only ever "
        "reference `type=tool` span names in `must_call_tools`/"
        "`must_not_call_tools` -- never a `type=node`/`type=llm`/"
        "`type=checkpoint` span's name, even one central to the failure.\n\n"
        "2. SEMANTIC (`semantic_rubric`, optional, only when structural "
        "checks alone can't express the failure): a short rubric for an LLM "
        "judge to evaluate the agent's actual final output CONTENT against -- "
        "use this for failures where every tool ran correctly and no "
        "exception occurred, but the output itself is wrong, malformed, or "
        "low-quality (e.g. leftover formatting artifacts, an incomplete "
        "answer, a factually wrong rewrite). Leave null whenever the "
        "structural fields alone already fully capture the failure -- this "
        "is the secondary, escalation-only tier, not the default.\n\n"
        "It's fine and expected for fields to be empty/null when they don't "
        "apply to this failure — do not invent a requirement just to fill a "
        "field. Always call the "
        f"`{ASSERTION_SPEC_TOOL_NAME}` tool with your answer — never respond "
        "in plain text."
    )


def _build_user_message(trace_summary: str, diagnosis_text: str, failure_class: Optional[str]) -> str:
    parts = [trace_summary, "", f"Classifier diagnosis: {diagnosis_text or '(none)'}"]
    if failure_class:
        parts.append(f"Failure category: {failure_class}")
    return "\n".join(parts)


def _result_from_tool_input(data: dict, *, model: str) -> AssertionSpec:
    must_call = data.get("must_call_tools")
    must_not_call = data.get("must_not_call_tools")
    max_steps = data.get("max_steps")
    semantic_rubric = data.get("semantic_rubric")
    return AssertionSpec(
        must_call_tools=[str(t) for t in must_call] if isinstance(must_call, list) else [],
        must_not_call_tools=(
            [str(t) for t in must_not_call] if isinstance(must_not_call, list) else []
        ),
        max_steps=int(max_steps) if isinstance(max_steps, (int, float)) and not isinstance(max_steps, bool) else None,
        no_exception=bool(data.get("no_exception", True)),
        rationale=str(data.get("rationale") or ""),
        model=model,
        semantic_rubric=str(semantic_rubric) if isinstance(semantic_rubric, str) and semantic_rubric.strip() else None,
    )


def generate_with_anthropic(
    trace_summary: str,
    diagnosis_text: str,
    failure_class: Optional[str],
    *,
    api_key: str,
    model: str,
) -> AssertionSpec:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=_system_prompt(),
        tools=[
            {
                "name": ASSERTION_SPEC_TOOL_NAME,
                "description": (
                    "Propose a structural regression-test assertion spec for a "
                    "classified agent failure."
                ),
                "input_schema": _tool_input_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": ASSERTION_SPEC_TOOL_NAME},
        messages=[
            {"role": "user", "content": _build_user_message(trace_summary, diagnosis_text, failure_class)}
        ],
    )
    tool_use = next(block for block in response.content if block.type == "tool_use")
    return _result_from_tool_input(tool_use.input, model=model)


def generate_with_nim(
    trace_summary: str,
    diagnosis_text: str,
    failure_class: Optional[str],
    *,
    api_key: str,
    model: str,
    base_url: str,
) -> AssertionSpec:
    """NIM backend (OpenAI-compatible forced function-call) — mirrors
    `classifier.classify_with_nim()`'s pattern exactly.
    """
    import openai

    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        max_tokens=1024,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": ASSERTION_SPEC_TOOL_NAME,
                    "description": (
                        "Propose a structural regression-test assertion spec for a "
                        "classified agent failure."
                    ),
                    "parameters": _tool_input_schema(),
                },
            }
        ],
        tool_choice={"type": "function", "function": {"name": ASSERTION_SPEC_TOOL_NAME}},
        messages=[
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": _build_user_message(trace_summary, diagnosis_text, failure_class)},
        ],
    )
    tool_call = response.choices[0].message.tool_calls[0]
    arguments = json.loads(tool_call.function.arguments)
    return _result_from_tool_input(arguments, model=model)


def generate_assertion_spec(
    trace_summary: str,
    diagnosis_text: str,
    failure_class: Optional[str],
    settings: Settings,
) -> AssertionSpec:
    """Dispatch to `settings.assertion_spec_backend` — see this module's
    docstring for why this is swappable at all. Raises
    `AssertionSpecNotConfigured` if the selected backend's key is missing.
    """
    if settings.assertion_spec_backend == "nim":
        if not settings.assertion_spec_nim_api_key:
            raise AssertionSpecNotConfigured("AGENTREPLAY_INGEST_ASSERTION_SPEC_NIM_API_KEY is not set")
        return generate_with_nim(
            trace_summary,
            diagnosis_text,
            failure_class,
            api_key=settings.assertion_spec_nim_api_key,
            model=settings.assertion_spec_nim_model,
            base_url=settings.nim_base_url,
        )

    if not settings.anthropic_api_key:
        raise AssertionSpecNotConfigured("AGENTREPLAY_INGEST_ANTHROPIC_API_KEY is not set")
    return generate_with_anthropic(
        trace_summary,
        diagnosis_text,
        failure_class,
        api_key=settings.anthropic_api_key,
        model=settings.anthropic_model,
    )


async def generate_assertion_spec_for_run(
    run: Run,
    session: AsyncSession,
    settings: Settings,
    *,
    generate_fn: Callable[[str, str, Optional[str], Settings], AssertionSpec] = generate_assertion_spec,
) -> AssertionSpec:
    """Generate an assertion spec for `run` and persist it onto `run.diagnosis`.

    `run` must already have its `.spans` loaded (e.g. via
    `crud.get_run_with_spans()`/`get_run_with_spans_by_id()`) — this
    function does no fetching of its own; the caller (the HTTP route)
    already needed to fetch+authorize the run before calling this, so a
    second internal fetch would be a redundant query for no benefit.

    Raises `RunNotClassifiedError` if `run.classification_status != "done"`.
    Any other exception (network error, `AssertionSpecNotConfigured`) is
    NOT caught here — see this module's docstring for why, unlike
    `classify_run_async()`.
    """
    if run.classification_status != "done":
        raise RunNotClassifiedError(run.id)

    trace_summary = build_trace_summary(run, run.spans)
    diagnosis = run.diagnosis or {}
    diagnosis_text = str(diagnosis.get("text") or "")

    spec = await asyncio.to_thread(generate_fn, trace_summary, diagnosis_text, run.failure_class, settings)

    run.diagnosis = {**diagnosis, "assertion_spec": spec.to_dict()}
    await session.commit()
    return spec
