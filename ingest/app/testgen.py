

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from agentreplay.testgen.fixture import build_fixture_data, render_fixture_module
from agentreplay.testgen.test_template import render_test_module, slugify_run_id
from sqlalchemy.ext.asyncio import AsyncSession

from .assertion_spec import AssertionSpec, generate_assertion_spec, generate_assertion_spec_for_run
from .config import Settings
from .models import Run, SpanModel

_ENTRYPOINT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")


class EntrypointFormatError(Exception):
    """Raised when `entrypoint` isn't shaped like `"module.path:function_name"`.

    Mirrors `resolve_entrypoint()`'s `ValueError` message wording (chunk
    3.4) for a consistent error a user sees the same way from either the
    CLI or the viewer.
    """

    def __init__(self, entrypoint: str) -> None:
        super().__init__(
            f"invalid entrypoint '{entrypoint}': expected 'module.path:function_name' "
            "(e.g. 'examples.langgraph_demo:main')"
        )
        self.entrypoint = entrypoint


@dataclass
class GeneratedTestFiles:
    """What `generate_test_files_for_run()` produced — two file contents, not files."""

    run_id: str
    fixture_filename: str
    fixture_source: str
    test_filename: str
    test_source: str
    assertion_spec: Optional[dict]


def validate_entrypoint_shape(entrypoint: str) -> None:
    """Shape-only check (`module.path:function_name`) — never imports/resolves it,
    since the ingest server never has the user's agent code available.
    """
    if not _ENTRYPOINT_RE.match(entrypoint):
        raise EntrypointFormatError(entrypoint)


def span_to_fixture_dict(span: SpanModel) -> dict:
    """`SpanModel` (ORM) -> the dict shape `build_fixture_data()` accepts.

    Mirrors `schemas.py: span_to_out()` field-for-field, except `started_at`
    is rendered as an ISO string here (not left as a `datetime`) so the
    generated fixture's `TOOL_SPANS` literal matches exactly what the CLI
    path produces (which goes through a JSON round-trip via `fetch_run()`,
    where `started_at` is necessarily already a string).

    Public (not `_`-prefixed) because `app/regression.py` needs the same
    conversion — both are `ingest/app` internals.
    """
    return {
        "id": span.id,
        "run_id": span.run_id,
        "parent_id": span.parent_id,
        "type": span.type,
        "name": span.name,
        "input": span.input,
        "output": span.output,
        "error": span.error,
        "started_at": span.started_at.isoformat(),
        "duration_ms": span.duration_ms,
        "fingerprint": span.fingerprint,
    }


async def generate_test_files_for_run(
    run: Run,
    entrypoint: str,
    session: AsyncSession,
    settings: Settings,
    *,
    generate_fn: Callable[[str, str, Optional[str], Settings], AssertionSpec] = generate_assertion_spec,
) -> GeneratedTestFiles:
    """Render fixture+test source for `run`, generating an assertion spec first if needed.

    `run` must already have `.spans` loaded (e.g. via `crud.get_run_with_spans()`),
    same calling convention as `generate_assertion_spec_for_run()` — no
    internal re-fetch.

    Raises `EntrypointFormatError` for a malformed `entrypoint` (before
    touching the DB or Sonnet — fail fast on a typo). Raises
    `RunNotClassifiedError`/`AssertionSpecNotConfigured` (re-raised from
    `generate_assertion_spec_for_run()`) only when this run has no
    assertion spec yet and needs one generated; a run that already has one
    persisted skips straight to rendering, even if Sonnet is unconfigured.
    """
    validate_entrypoint_shape(entrypoint)

    diagnosis = run.diagnosis or {}
    assertion_spec = diagnosis.get("assertion_spec")
    if assertion_spec is None:
        spec = await generate_assertion_spec_for_run(run, session, settings, generate_fn=generate_fn)
        assertion_spec = spec.to_dict()

    fixture = build_fixture_data(run.id, [span_to_fixture_dict(s) for s in run.spans])
    slug = slugify_run_id(run.id)
    fixture_filename = f"fixture_{slug}.py"

    test_source = render_test_module(
        fixture_module=f"fixture_{slug}",
        entrypoint=entrypoint,
        run_id=run.id,
        assertion_spec=assertion_spec,
    )

    return GeneratedTestFiles(
        run_id=run.id,
        fixture_filename=fixture_filename,
        fixture_source=render_fixture_module(fixture),
        test_filename=f"test_{slug}.py",
        test_source=test_source,
        assertion_spec=assertion_spec,
    )
