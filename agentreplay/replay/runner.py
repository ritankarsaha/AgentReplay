"""High-level orchestration for chunk 3.4: load a trace, replay it, call the entrypoint.

This is what `agentreplay/cli.py`'s `replay` subcommand calls, but it's a
plain function with no CLI/argparse concerns — usable directly from tests,
notebooks, or other tooling that wants to replay a run programmatically.
"""

from __future__ import annotations

import functools
import importlib
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from .client import ReplaySession, replay_mode
from .loader import fetch_run, load_run_from_file


@dataclass
class ReplayResult:
    """What a `replay_run()` call produced."""

    run_id: str
    session: ReplaySession
    entrypoint_result: Any


def resolve_entrypoint(spec: str) -> Callable[[], Any]:
    """Resolve a `"module.path:function_name"` spec into a zero-arg callable.

    Mirrors the `module:attr` convention used by gunicorn/uvicorn entry
    points. The function is called with no arguments — CLAUDE.md's chunk
    3.4 scope is "calls entrypoint", and every example agent in this repo
    (`examples/resume_bot.py:main`, `examples/langgraph_demo.py:main`) is
    already a zero-arg callable that derives its own input internally, so
    this is the smallest version that unblocks the chunk (CLAUDE.md §10).
    Raises `ValueError` (not `ImportError`/`AttributeError`) for every
    failure mode, so the CLI has one exception type to present uniformly.
    """
    if ":" not in spec:
        raise ValueError(
            f"invalid --entrypoint '{spec}': expected 'module.path:function_name' "
            "(e.g. 'examples.langgraph_demo:main')"
        )
    module_path, _, func_name = spec.partition(":")
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ValueError(f"could not import module '{module_path}': {exc}") from exc

    func = getattr(module, func_name, None)
    if func is None:
        raise ValueError(f"module '{module_path}' has no attribute '{func_name}'")
    if not callable(func):
        raise ValueError(f"'{module_path}:{func_name}' is not callable")
    return func


@contextmanager
def _suppress_live_init() -> Iterator[None]:
    """Force any `agentreplay.init()` call the entrypoint makes to `enabled=False`.

    Every example agent in this repo calls `agentreplay.init()` itself
    (the normal pattern for an instrumented agent). Without this, that call
    would, inside a `replay_mode()` block: (1) require real `api_key`/
    `project_id` credentials even though replay needs none, and (2), worst
    case, if `enabled=True` and credentials happen to be present (e.g. a
    stale `.env`), actually start a background exporter and silently
    re-record the replayed calls as a brand-new live run. Forcing
    `enabled=False` sidesteps both: no credential requirement, no exporter.
    `agentreplay.get_run_id()`/`agentreplay.checkpoint()` etc. still work
    normally during the entrypoint, since `init()` still sets `_state`'s
    config/run_id either way.

    (The third original risk this used to carry alone — `init()`'s
    `patching.patch_all()` re-wrapping the LLM client classes with a
    recording wrapper *on top of* replay's — is now also independently
    guarded at the source: `patching.patch_all()` itself no-ops while a
    replay session is active, see its docstring. That fix covers
    `replay_run()`/`replay_run_from_file()` being used as a library call
    inside a longer-lived process too, not just this CLI's one-shot
    lifecycle — previously a documented gap, PROGRESS.md "Day 3 pendings".)
    """
    import agentreplay as _agentreplay

    original_init = _agentreplay.init

    @functools.wraps(original_init)
    def _safe_init(*args: Any, **kwargs: Any) -> Any:
        kwargs["enabled"] = False
        return original_init(*args, **kwargs)

    _agentreplay.init = _safe_init  # type: ignore[assignment]
    try:
        yield
    finally:
        _agentreplay.init = original_init  # type: ignore[assignment]


def _replay_loaded_spans(run_id: str, spans: list, entrypoint: str) -> ReplayResult:
    """Shared tail end of `replay_run()`/`replay_run_from_file()`: replay `spans`, call `entrypoint`."""
    func = resolve_entrypoint(entrypoint)

    with _suppress_live_init(), replay_mode(spans) as session:
        entrypoint_result = func()

    return ReplayResult(run_id=run_id, session=session, entrypoint_result=entrypoint_result)


def replay_run(
    run_id: str,
    entrypoint: str,
    *,
    endpoint: str,
    api_key: str,
    timeout: float = 30.0,
) -> ReplayResult:
    """Fetch `run_id`'s trace from the ingest API, replay it, call `entrypoint`.

    The chunk 3.4 capstone: "loads trace, patches clients into replay mode,
    calls entrypoint." Raises `TraceFetchError` (bad run_id/credentials/
    network), `ValueError` (bad `--entrypoint` spec), or whatever the
    entrypoint itself raises — including `ReplayDivergence`/`ReplayedError`
    propagating up from inside it. Callers (the CLI) decide how to present
    each. See `replay_run_from_file()` for the credential-free, offline
    equivalent (Day 3 backlog: local-file trace loading).
    """
    data = fetch_run(run_id, endpoint=endpoint, api_key=api_key, timeout=timeout)
    return _replay_loaded_spans(run_id, data.get("spans", []), entrypoint)


def replay_run_from_file(trace_file: str, entrypoint: str) -> ReplayResult:
    """Load a trace from a local JSON file, replay it, call `entrypoint`.

    The same capstone as `replay_run()`, but for a trace that isn't (or
    can't be) fetched from the ingest API — a redacted export shared for a
    bug report, or a design partner's call without API access (Day 3
    backlog, PROGRESS.md "Day 3 pendings"). No `endpoint`/`api_key` needed
    at all; `replay_mode()` itself never cared where `spans` came from, so
    this only ever needed a loader, not an architecture change.

    `ReplayResult.run_id` is the file's own `"id"` field if the JSON is a
    full `RunDetailOut`-shaped dump, else `trace_file` itself (so there's
    always something meaningful to report even for a bare `{"spans": [...]}`
    file). Raises `TraceFetchError` (missing file/invalid JSON/missing
    `spans` key), `ValueError` (bad `--entrypoint` spec), or whatever the
    entrypoint itself raises — same exception contract as `replay_run()`.
    """
    data = load_run_from_file(trace_file)
    run_id = data.get("id") or trace_file
    return _replay_loaded_spans(run_id, data.get("spans", []), entrypoint)
