"""Sonnet/MAST failure classifier (chunk 3.6, CLAUDE.md §3.6).

On `status="failure"` (set by chunk 3.5's `agentreplay.fail()` / auto-detect-
on-exception), a Celery job (`tasks.py`) sends a trace summary to an LLM with
the MAST taxonomy (`mast.py`) via a forced tool call, and writes the result
back onto the `runs` row: `failure_class`/`root_span_id` (overwriting
whatever 3.5 set, since the classifier's verdict is authoritative) plus the
new `classification_status`/`diagnosis` columns.

Backend-swappable (CLAUDE.md §5 NIM cost-cutting track, scoped to "the
CLASSIFIER ONLY (3.6)"): `classify_trace()` dispatches to either Anthropic
Sonnet (forced `tool_choice`, the literal "forced JSON tool_use" CLAUDE.md
§3.6 calls for) or an OpenAI-compatible NIM endpoint (forced function-call
`tool_choice`) purely based on `Settings.classifier_backend` — no caller
ever needs to know which one ran.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from . import crud
from .config import Settings
from .mast import MAST_CATEGORY_KEYS, render_taxonomy_for_prompt
from .models import Run, SpanModel

CLASSIFY_TOOL_NAME = "classify_failure"

# Per-field/per-trace caps so a large run doesn't blow the model's context
# (or the API bill) — generous enough for a real demo-sized trace, not
# meant to be a tuned production limit yet.
MAX_FIELD_CHARS = 1000
MAX_SPANS = 60


class ClassifierNotConfigured(Exception):
    """Raised when `classify_trace()` is asked to use a backend with no API key set."""


@dataclass
class ClassificationResult:
    failure_class: str
    culprit_span_id: Optional[str]
    diagnosis: str
    suggested_assertion: dict
    model: str
    backend: str


def _tool_input_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "failure_class": {
                "type": "string",
                "enum": MAST_CATEGORY_KEYS,
                "description": "The single MAST category that best describes this failure.",
            },
            "culprit_span_id": {
                "type": "string",
                "description": (
                    "The exact `id` of the single span most responsible for the "
                    "failure, copied verbatim from the trace. Use the literal "
                    "string \"unknown\" if no single span is clearly at fault."
                ),
            },
            "diagnosis": {
                "type": "string",
                "description": "2-4 sentences, for a human engineer, on what went wrong and why.",
            },
            "suggested_assertion": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["exact", "structural", "semantic"]},
                    "description": {
                        "type": "string",
                        "description": "What a regression test for this failure should assert.",
                    },
                },
                "required": ["type", "description"],
            },
        },
        "required": ["failure_class", "culprit_span_id", "diagnosis", "suggested_assertion"],
    }


def _system_prompt() -> str:
    return (
        "You are AgentReplay's failure classifier. You are given the full "
        "recorded trace of one AI agent run that has been marked as failed. "
        "Classify the failure using exactly one of the following MAST "
        f"taxonomy categories:\n\n{render_taxonomy_for_prompt()}\n\n"
        "Then identify the single span most responsible for the failure, "
        "write a concise diagnosis for a human engineer, and suggest what a "
        "regression test for this failure should assert. Always call the "
        f"`{CLASSIFY_TOOL_NAME}` tool with your answer — never respond in "
        "plain text."
    )


def _truncate(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) > MAX_FIELD_CHARS:
        return f"{text[:MAX_FIELD_CHARS]}... [truncated, {len(text)} chars total]"
    return text


def build_trace_summary(run: Run, spans: Sequence[SpanModel]) -> str:
    """Render a run + its spans as plain text for the classifier prompt.

    Spans are ordered by `started_at` (execution order). If a trace has more
    than `MAX_SPANS`, only the most recent ones are kept — a failure is most
    often visible near the end of a trace, and trimming from the front loses
    less diagnostic signal than trimming from the back.
    """
    ordered = sorted(spans, key=lambda s: s.started_at)
    if len(ordered) > MAX_SPANS:
        ordered = ordered[-MAX_SPANS:]

    lines = [
        f"Run {run.id} (agent_version={run.agent_version}, framework={run.framework})",
        f"{len(ordered)} span(s), in execution order:",
        "",
    ]
    for span in ordered:
        lines.append(f"- id={span.id} parent_id={span.parent_id} type={span.type} name={span.name}")
        lines.append(f"  input: {_truncate(span.input)}")
        lines.append(f"  output: {_truncate(span.output)}")
        if span.error:
            lines.append(f"  error: {_truncate(span.error)}")
    return "\n".join(lines)


def _result_from_tool_input(data: dict, *, model: str, backend: str) -> ClassificationResult:
    failure_class = data.get("failure_class")
    if failure_class not in MAST_CATEGORY_KEYS:
        failure_class = "other"

    culprit_span_id = data.get("culprit_span_id")
    if not culprit_span_id or culprit_span_id.strip().lower() == "unknown":
        culprit_span_id = None

    suggested_assertion = data.get("suggested_assertion")
    if not isinstance(suggested_assertion, dict) or "type" not in suggested_assertion:
        suggested_assertion = {"type": "structural", "description": ""}

    return ClassificationResult(
        failure_class=failure_class,
        culprit_span_id=culprit_span_id,
        diagnosis=str(data.get("diagnosis") or ""),
        suggested_assertion=suggested_assertion,
        model=model,
        backend=backend,
    )


def classify_with_anthropic(trace_summary: str, *, api_key: str, model: str) -> ClassificationResult:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=_system_prompt(),
        tools=[
            {
                "name": CLASSIFY_TOOL_NAME,
                "description": "Classify an AI agent run failure using the MAST taxonomy.",
                "input_schema": _tool_input_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": CLASSIFY_TOOL_NAME},
        messages=[{"role": "user", "content": trace_summary}],
    )
    tool_use = next(block for block in response.content if block.type == "tool_use")
    return _result_from_tool_input(tool_use.input, model=model, backend="sonnet")


def classify_with_nim(
    trace_summary: str, *, api_key: str, model: str, base_url: str
) -> ClassificationResult:
    import openai

    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        max_tokens=1024,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": CLASSIFY_TOOL_NAME,
                    "description": "Classify an AI agent run failure using the MAST taxonomy.",
                    "parameters": _tool_input_schema(),
                },
            }
        ],
        tool_choice={"type": "function", "function": {"name": CLASSIFY_TOOL_NAME}},
        messages=[
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": trace_summary},
        ],
    )
    tool_call = response.choices[0].message.tool_calls[0]
    arguments = json.loads(tool_call.function.arguments)
    return _result_from_tool_input(arguments, model=model, backend="nim")


def classify_trace(trace_summary: str, settings: Settings) -> ClassificationResult:
    """Dispatch to the configured backend. Raises `ClassifierNotConfigured` if no key is set."""
    if settings.classifier_backend == "nim":
        if not settings.nim_api_key:
            raise ClassifierNotConfigured("AGENTREPLAY_INGEST_NIM_API_KEY is not set")
        return classify_with_nim(
            trace_summary,
            api_key=settings.nim_api_key,
            model=settings.nim_model,
            base_url=settings.nim_base_url,
        )

    if not settings.anthropic_api_key:
        raise ClassifierNotConfigured("AGENTREPLAY_INGEST_ANTHROPIC_API_KEY is not set")
    return classify_with_anthropic(
        trace_summary, api_key=settings.anthropic_api_key, model=settings.anthropic_model
    )


async def classify_run_async(
    run_id: str,
    session: AsyncSession,
    settings: Settings,
    *,
    classify_fn: Callable[[str, Settings], ClassificationResult] = classify_trace,
) -> None:
    """Classify one run and persist the result. Idempotent and safe to call repeatedly.

    No-ops if the run doesn't exist, isn't (or is no longer) `status="failure"`,
    or has already been classified (`classification_status == "done"`) — so a
    race between two ingest batches both enqueueing the same `run_id` costs at
    most one duplicate (wasted, not incorrect) classification call.

    `classify_fn` is injectable for testing (mirrors the rest of this
    codebase's swappable-factory pattern, e.g. `exporter._build_client`) —
    defaults to the real `classify_trace()` dispatcher.
    """
    run = await crud.get_run_with_spans_by_id(session, run_id=run_id)
    if run is None or run.status != "failure" or run.classification_status == "done":
        return

    trace_summary = build_trace_summary(run, run.spans)

    try:
        result = await asyncio.to_thread(classify_fn, trace_summary, settings)
    except Exception as exc:
        run.classification_status = "error"
        run.diagnosis = {
            "error": str(exc),
            "backend": settings.classifier_backend,
            "attempted_at": datetime.now(timezone.utc).isoformat(),
        }
        await session.commit()
        return

    # A hallucinated span id is a real risk with any LLM-generated reference
    # — only trust `culprit_span_id` if it's an id that actually exists on
    # this run, else fall back to whatever `root_span_id` chunk 3.5 may have
    # already set (an explicit caller-supplied `span_id`), or null.
    span_ids = {span.id for span in run.spans}
    culprit_span_id = result.culprit_span_id if result.culprit_span_id in span_ids else None

    run.failure_class = result.failure_class
    if culprit_span_id is not None:
        run.root_span_id = culprit_span_id
    run.classification_status = "done"
    run.diagnosis = {
        "failure_class": result.failure_class,
        "culprit_span_id": culprit_span_id,
        "text": result.diagnosis,
        "suggested_assertion": result.suggested_assertion,
        "model": result.model,
        "backend": result.backend,
        "classified_at": datetime.now(timezone.utc).isoformat(),
    }
    await session.commit()
