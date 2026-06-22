from typing import List, Optional, Type

from .diff import NEVER_RECORDED, FieldDiff, diff_payloads, format_diff
from .exception_registry import resolve_exception_class


class AgentReplayError(Exception):
    """Base exception for all agentreplay errors."""


class ConfigurationError(AgentReplayError):
    """Raised when the SDK is used before init() or with invalid config."""


class ReplayError(AgentReplayError):
    """Base class for replay-mode errors.

    Lives in core (not `agentreplay.replay`) because `agentreplay/tool.py`
    (core, eagerly imported) must be able to raise these during replay
    without depending on the optional `agentreplay.replay` subpackage.
    `agentreplay/replay/exceptions.py` re-exports these for the public
    `agentreplay.replay` API (CLAUDE.md §4 chunk 3.1/3.2).
    """


class ReplayDivergence(ReplayError):
    """A live call during replay had no matching recorded call (CLAUDE.md §3.4).

    This is a FEATURE, not a bug: it means the agent under replay diverged
    from the recorded trace at this call site, and the raised diff is the
    user-facing signal ("your new agent diverged here").

    `expected_request` (chunk 3.3) is the most-recently-recorded request at
    this call site — `None` if the call site was never recorded at all, as
    opposed to having recorded calls that are all already consumed (both
    are "no match", but they're different situations worth distinguishing).
    Either way, `self.diff` (a list of `agentreplay.diff.FieldDiff`) is
    always populated and safe to inspect programmatically, not just via the
    message string.
    """

    def __init__(
        self,
        call_site: str,
        request_payload: dict,
        fingerprint: str,
        recorded_count: int,
        expected_request: Optional[dict] = None,
    ) -> None:
        self.call_site = call_site
        self.request_payload = request_payload
        self.fingerprint = fingerprint
        self.recorded_count = recorded_count
        self.expected_request = expected_request
        self.diff: List[FieldDiff] = diff_payloads(
            expected_request if expected_request is not None else NEVER_RECORDED,
            request_payload,
        )
        super().__init__(
            f"ReplayDivergence at call site '{call_site}' "
            f"(fingerprint={fingerprint[:12]}..., {recorded_count} call(s) recorded, "
            f"all already consumed if >0): your agent diverged from the recorded "
            f"trace here.\nDiff (expected -> actual):\n{format_diff(self.diff)}"
        )


class ReplayedError(ReplayError):
    """Raised in place of the original exception for a recorded failed call.

    Reconstructs the type/message from the recorded `error` payload
    (`patching/common.py: build_error_payload`) but always raises as this
    one generic type, never the original exception class — reconstructing
    a real `anthropic.RateLimitError` etc. would need SDK-internal
    constructor args (a `response`/`body`) a recorded payload doesn't have.
    `original_exception_class` (best-effort, `None` if unrecognized) is the
    *introspectable* answer to "what type was it" — looked up via
    `exception_registry.py` (covers known Anthropic/OpenAI SDK exceptions
    and Python builtins, for tool-function failures) — without changing
    what actually gets raised. Exists for a future chunk (Day 4 assertion-
    spec generation) that wants exact type fidelity, e.g. to generate
    `pytest.raises(anthropic.RateLimitError)`.
    """

    def __init__(self, error_payload: dict) -> None:
        self.original_type: Optional[str] = error_payload.get("type")
        self.original_message: Optional[str] = error_payload.get("message")
        self.original_exception_class: Optional[Type[BaseException]] = resolve_exception_class(
            self.original_type
        )
        super().__init__(f"[replayed] {self.original_type}: {self.original_message}")
