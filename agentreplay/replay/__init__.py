"""Mode A — Strict Replay (CLAUDE.md §3.2): re-serve recorded LLM calls instead
of making live ones, for deterministic local reproduction of a recorded run.

This subpackage is intentionally NOT imported by `agentreplay/__init__.py` —
mirrors the `agentreplay.adapters` pattern: importing `agentreplay.replay`
itself has no extra deps, and the SDK core stays import-light. The CLI
(`agentreplay replay <run_id>`, chunk 3.4) is the primary consumer; this is
also usable directly for tests/tooling.

Both `type="llm"` spans (chunk 3.1, served via monkey-patched Anthropic/
OpenAI SDK classes) and `type="tool"` spans (chunk 3.2, served via
`agentreplay/tool.py` consulting `_state.get_active_tool_replay_run()`) are
matched here, both through the same `RecordedRun`/`CallSiteQueue` matching
primitives in `store.py`. `ReplayDivergence` (chunk 3.3) carries a real
field-level diff (`agentreplay.diff.FieldDiff` list) between the most
recently recorded request at that call site and the live one that diverged.

`replay_run()` (chunk 3.4) is the highest-level entry point: given a
`run_id` and a `"module:function"` entrypoint spec, it fetches the trace
from the ingest API, replays it, and calls the entrypoint — this is what
the `agentreplay replay <run_id>` console script (`agentreplay/cli.py`)
calls.
"""

from __future__ import annotations

from ..diff import FieldDiff, diff_payloads, format_diff
from .client import ReplaySession, is_active, patch_for_replay, replay_mode, unpatch_replay
from .exceptions import ReplayDivergence, ReplayedError, ReplayError, TraceFetchError
from .loader import fetch_run, load_run_from_file
from .runner import ReplayResult, replay_run, replay_run_from_file, resolve_entrypoint
from .store import CallSiteQueue, RecordedCall, RecordedRun

__all__ = [
    "replay_mode",
    "patch_for_replay",
    "unpatch_replay",
    "is_active",
    "ReplaySession",
    "RecordedRun",
    "RecordedCall",
    "CallSiteQueue",
    "ReplayError",
    "ReplayDivergence",
    "ReplayedError",
    "TraceFetchError",
    "FieldDiff",
    "diff_payloads",
    "format_diff",
    "fetch_run",
    "load_run_from_file",
    "resolve_entrypoint",
    "replay_run",
    "replay_run_from_file",
    "ReplayResult",
]
