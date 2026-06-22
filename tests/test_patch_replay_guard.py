"""Day 3 backlog: `patching.patch_all()` must no-op while a replay session is active.

Previously documented as a known gap in `_suppress_live_init()`'s docstring
(PROGRESS.md "Day 3 pendings") — without this guard, an `agentreplay.init()`
call made *during* an active `replay_mode()` block would wrap the replay
wrapper with a recording wrapper on top of it.
"""

from __future__ import annotations

import agentreplay
from agentreplay import _state
from agentreplay.patching import anthropic_patch
from agentreplay.replay.client import replay_mode


def test_init_skips_patching_while_replay_is_active(capsys):
    with replay_mode([]):
        agentreplay.init(enabled=False)
        assert anthropic_patch._patched is False

    captured = capsys.readouterr()
    assert "skipping LLM client patching" in captured.err


def test_init_patches_normally_after_replay_session_ends():
    with replay_mode([]):
        pass

    agentreplay.init(enabled=False)
    assert anthropic_patch._patched is True


def test_init_patches_normally_when_no_replay_active():
    assert _state.get_active_tool_replay_run() is None
    agentreplay.init(enabled=False)
    assert anthropic_patch._patched is True


def test_replay_mode_clears_active_flag_on_exception():
    class Boom(Exception):
        pass

    try:
        with replay_mode([]):
            raise Boom()
    except Boom:
        pass

    assert _state.get_active_tool_replay_run() is None
    agentreplay.init(enabled=False)
    assert anthropic_patch._patched is True
