from __future__ import annotations

import sys

from .. import _state
from . import anthropic_patch, openai_patch, responses_patch


def patch_all() -> None:
    """Patch every supported LLM client for recording.

    No-ops (with a one-line stderr note) if a `agentreplay.replay.replay_mode()`
    session is currently active — recording and replay are mutually
    exclusive for the same call sites by construction (you can't
    simultaneously serve a recorded response and record a brand-new live
    one), so the correct behavior for an `agentreplay.init()` call made
    *during* an active replay session (e.g. from inside the entrypoint
    `replay_run()` calls) is "don't patch", not a more complex stacking
    scheme. Without this guard, `patch_anthropic()` etc. would wrap the
    replay wrapper with a recording wrapper on top of it, and the two
    patch-state machines' unpatch ordering could leave the LLM client
    classes restored to the wrong thing once both layers eventually
    unwind — previously documented as a known constraint in PROGRESS.md
    "Day 3 pendings" (`_suppress_live_init()`'s docstring), closed out here
    instead of just suppressing credentials/the exporter.

    Detection reuses `_state`'s existing tool-replay-session flag (set/
    cleared atomically with `replay.client.patch_for_replay()`/
    `unpatch_replay()` inside `replay_mode()`) rather than adding a new
    global — `agentreplay.replay` is the optional subpackage, so core
    can't import it directly to ask "is replay active", but it can read
    this `_state` slot, which is already always in sync with that question.
    """
    if _state.get_active_tool_replay_run() is not None:
        print(
            "agentreplay: skipping LLM client patching for init() — a replay "
            "session is active (recording and replay are mutually exclusive)",
            file=sys.stderr,
        )
        return
    anthropic_patch.patch_anthropic()
    openai_patch.patch_openai()
    responses_patch.patch_openai_responses()


def unpatch_all() -> None:
    anthropic_patch.unpatch_anthropic()
    openai_patch.unpatch_openai()
    responses_patch.unpatch_openai_responses()
