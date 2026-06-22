"""Re-exports for `agentreplay.replay`'s public exception API.

`ReplayError`/`ReplayDivergence`/`ReplayedError` actually live in core
`agentreplay/exceptions.py` (moved there in chunk 3.2) because
`agentreplay/tool.py` — core, eagerly imported — needs to raise them during
tool replay without depending on this optional subpackage. This module
exists purely so `from agentreplay.replay import ReplayDivergence` (the
public surface chunk 3.1 shipped) keeps working unchanged.
"""

from __future__ import annotations

from ..exceptions import ReplayDivergence, ReplayedError, ReplayError


class TraceFetchError(ReplayError):
    """Couldn't load a trace for replay (chunk 3.4: `agentreplay replay <run_id>`).

    Covers both transport failures (network error, timeout) and the ingest
    API rejecting the request (401/404/5xx) — `agentreplay/replay/loader.py`
    raises this uniformly so the CLI has one exception type to present to
    the user, regardless of which step of fetching failed. This is purely a
    replay/CLI-side concept (no core module ever raises it), so unlike
    `ReplayDivergence`/`ReplayedError` it doesn't need to live in core
    `agentreplay/exceptions.py`.
    """

    def __init__(self, run_id: str, message: str) -> None:
        self.run_id = run_id
        super().__init__(f"failed to fetch run '{run_id}': {message}")


__all__ = ["ReplayError", "ReplayDivergence", "ReplayedError", "TraceFetchError"]
