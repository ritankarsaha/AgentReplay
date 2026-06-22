"""Replay-mode LLM client (CLAUDE.md §3.2 Mode A / §4 chunk 3.1).

Monkey-patches the same call sites as `agentreplay/patching/` (Anthropic +
OpenAI chat/responses, sync + async), but instead of making a live API call
and recording a span, it serves the matching recorded response straight
from a `RecordedRun` — no network, no API key, fully deterministic by
construction.

Deliberately a *separate* patch-state machine from `agentreplay/patching/`
(not a mode flag on it): replay and recording are mutually exclusive for a
given call site at a given moment, and keeping them independent means
`agentreplay.init()` (recording) and `replay_mode()` (replay) can't silently
corrupt each other's `_patched` bookkeeping.
"""

from __future__ import annotations

import importlib
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Tuple

from .. import _state
from ..fingerprint import compute_fingerprint
from ..patching.common import build_request_payload
from .exceptions import ReplayDivergence, ReplayedError, ReplayError
from .reconstruct import reconstruct_response
from .store import RecordedRun


@dataclass
class ReplaySession:
    """Both halves of an active replay (chunk 3.1 LLM + chunk 3.2 tool).

    `llm` matches/serves `type="llm"` spans (patched into the Anthropic/
    OpenAI SDK classes, see `patch_for_replay()` below). `tool` matches
    `type="tool"` spans and is consulted directly by `agentreplay/tool.py`
    via `_state.get_active_tool_replay_run()` — tool wrapping is our own
    decorator, not a third-party class to monkey-patch, so there's nothing
    to patch for it; it just reads this session's `.tool` run at call time.
    """

    llm: RecordedRun
    tool: RecordedRun

    def remaining_count(self) -> int:
        return self.llm.remaining_count() + self.tool.remaining_count()

# (module path, class name, method name, call-site name, is_async)
_REPLAY_TARGETS: Tuple[Tuple[str, str, str, str, bool], ...] = (
    ("anthropic.resources.messages", "Messages", "create", "anthropic.messages.create", False),
    ("anthropic.resources.messages", "AsyncMessages", "create", "anthropic.messages.create", True),
    (
        "openai.resources.chat.completions",
        "Completions",
        "create",
        "openai.chat.completions.create",
        False,
    ),
    (
        "openai.resources.chat.completions",
        "AsyncCompletions",
        "create",
        "openai.chat.completions.create",
        True,
    ),
    (
        "openai.resources.responses.responses",
        "Responses",
        "create",
        "openai.responses.create",
        False,
    ),
    (
        "openai.resources.responses.responses",
        "AsyncResponses",
        "create",
        "openai.responses.create",
        True,
    ),
)

_saved: Dict[str, Tuple[type, str, Any]] = {}
_active = False


def is_active() -> bool:
    return _active


def _resolve_or_raise(run: RecordedRun, call_site: str, kwargs: dict) -> Any:
    if kwargs.get("stream"):
        raise ReplayError(
            f"cannot replay a streaming call at '{call_site}': agentreplay only "
            "records an assembled-output placeholder for streaming requests in "
            "v1 (CLAUDE.md §3.4); full chunk capture/replay is a Weeks 2-4 item."
        )

    request_payload = build_request_payload(kwargs)
    call = run.resolve(call_site, request_payload)
    if call is None:
        raise ReplayDivergence(
            call_site=call_site,
            request_payload=request_payload,
            fingerprint=compute_fingerprint(request_payload),
            recorded_count=run.call_site_total(call_site),
            expected_request=run.last_request(call_site),
        )
    if call.error is not None:
        raise ReplayedError(call.error)
    return reconstruct_response(call_site, call.output)


def _wrap_sync(call_site: str, run: RecordedRun) -> Any:
    def patched(self: Any, *args: Any, **kwargs: Any) -> Any:
        return _resolve_or_raise(run, call_site, kwargs)

    return patched


def _wrap_async(call_site: str, run: RecordedRun) -> Any:
    async def patched(self: Any, *args: Any, **kwargs: Any) -> Any:
        return _resolve_or_raise(run, call_site, kwargs)

    return patched


def patch_for_replay(run: RecordedRun) -> None:
    """Monkey-patch every available LLM call site into replay mode for `run`.

    Skips any provider whose package isn't installed, same as the recording
    patches. If replay mode is already active, unpatches first (single
    active `RecordedRun` at a time, mirrors the recording patches' model).
    """
    global _active
    if _active:
        unpatch_replay()

    for module_path, class_name, method_name, call_site, is_async in _REPLAY_TARGETS:
        try:
            module = importlib.import_module(module_path)
        except ImportError:
            continue
        cls = getattr(module, class_name, None)
        if cls is None:
            continue

        key = f"{module_path}.{class_name}.{method_name}"
        _saved[key] = (cls, method_name, getattr(cls, method_name))
        wrapper = _wrap_async(call_site, run) if is_async else _wrap_sync(call_site, run)
        setattr(cls, method_name, wrapper)

    _active = True


def unpatch_replay() -> None:
    """Restore every method `patch_for_replay()` touched."""
    global _active
    for cls, method_name, original in _saved.values():
        setattr(cls, method_name, original)
    _saved.clear()
    _active = False


@contextmanager
def replay_mode(spans: Any) -> Iterator[ReplaySession]:
    """Patch all LLM call sites and arm tool replay for the `with` block.

    `spans` is a recorded trace's spans — a list of `Span`, `Span.to_dict()`
    dicts, or ingest-API span dicts (e.g. the `spans` field of
    `GET /v1/runs/{run_id}`). Builds two `RecordedRun`s from the same list
    (one per `type="llm"`, one per `type="tool"`) and activates both:
    Anthropic/OpenAI SDK classes are monkey-patched to serve recorded LLM
    responses (chunk 3.1); any `@agentreplay.tool`-decorated function called
    inside the block is served its recorded output WITHOUT running the real
    function body (chunk 3.2 — tools are always mocked in replay, CLAUDE.md
    §9 risk #3, never a live side effect).

    Yields a `ReplaySession` (inspect `.remaining_count()` after the block
    to see if any recorded calls went unused). Raises `ReplayDivergence` if
    a live call/tool invocation has no recorded match, or `ReplayedError`
    if the matched recorded call originally failed. Always unpatches /
    disarms on exit, even on exception.
    """
    session = ReplaySession(
        llm=RecordedRun(spans, span_type="llm"),
        tool=RecordedRun(spans, span_type="tool"),
    )
    patch_for_replay(session.llm)
    _state.set_active_tool_replay_run(session.tool)
    try:
        yield session
    finally:
        unpatch_replay()
        _state.set_active_tool_replay_run(None)
