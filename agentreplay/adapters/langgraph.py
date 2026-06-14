"""LangGraph adapter (chunk 2.1, CLAUDE.md §3.1/§3.3 Layer 2).

`AgentReplayCallbackHandler` is a `langchain_core` `BaseCallbackHandler` that
records one `type="node"` span per LangGraph node execution: enter (input =
the channel-state slice passed into the node) and exit (output = the
channel-state update the node returned, or an error).

Usage::

    from agentreplay.adapters.langgraph import AgentReplayCallbackHandler

    graph = builder.compile()
    graph.invoke(initial_state, config={"callbacks": [AgentReplayCallbackHandler()]})

While a node is executing, its span id is pushed onto `_state`'s per-thread
parent stack, so LLM spans recorded via Layer 1 patching (1.2/1.3) and tool
spans (Layer 3, chunk 2.5) recorded on the same thread automatically nest
under that node — giving the node -> LLM -> tool timeline from CLAUDE.md's
Day 2 checkpoint.

Known limitation: nesting is tracked via a per-thread stack, not LangChain's
`run_id`/`parent_run_id` chain. This is correct for the common synchronous
and thread-pool-parallel cases, but concurrent nodes interleaved on a single
thread (e.g. `asyncio.gather` inside one event loop) can attribute an LLM
call to the wrong sibling node. Acceptable for v1 — revisit if it shows up
in practice (CLAUDE.md §9 "dogfood before claiming deterministic").
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from .. import _state
from ..collector import get_collector
from ..exceptions import ConfigurationError
from ..fingerprint import compute_fingerprint
from ..serialize import safe_serialize
from ..span import Span

try:
    from langchain_core.callbacks.base import BaseCallbackHandler
except ImportError as _exc:  # pragma: no cover - exercised via ConfigurationError test
    BaseCallbackHandler = object  # type: ignore[assignment, misc]
    _IMPORT_ERROR: Optional[ImportError] = _exc
else:
    _IMPORT_ERROR = None


class AgentReplayCallbackHandler(BaseCallbackHandler):  # type: ignore[misc]
    """Records one `type="node"` span per LangGraph node enter/exit."""

    def __init__(self) -> None:
        if _IMPORT_ERROR is not None:
            raise ConfigurationError(
                "agentreplay.adapters.langgraph requires langchain-core to be "
                "installed (pip install langchain-core, or langgraph which "
                "depends on it)."
            ) from _IMPORT_ERROR
        super().__init__()
        self._starts: Dict[UUID, Dict[str, Any]] = {}

    @staticmethod
    def _node_name(metadata: Optional[Dict[str, Any]]) -> Optional[str]:
        """Return the LangGraph node name for this callback, or None.

        LangGraph stamps `metadata["langgraph_node"]` on the runnable
        invocation for each graph node, but not on the top-level
        `graph.invoke()`/subgraph chain invocations — that's how we
        distinguish "a node ran" from generic LCEL plumbing.
        """
        if not metadata:
            return None
        node_name = metadata.get("langgraph_node")
        return node_name if isinstance(node_name, str) else None

    def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        node_name = self._node_name(metadata)
        if node_name is None:
            return
        if not _state.is_initialized() or not _state.get_config().enabled:
            return

        self._starts[run_id] = {
            "name": node_name,
            "input": safe_serialize(inputs),
            "started_at": datetime.now(timezone.utc),
            "start_perf": time.perf_counter(),
            "parent_id": _state.peek_parent_span_id(),
            "step": metadata.get("langgraph_step") if metadata else None,
        }
        _state.push_parent_span_id(str(run_id))

    def on_chain_end(
        self,
        outputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        self._finish(run_id, output=safe_serialize(outputs), error=None)

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        self._finish(
            run_id,
            output=None,
            error={"type": type(error).__name__, "message": str(error)},
        )

    def _finish(self, run_id: UUID, output: Optional[Any], error: Optional[dict]) -> None:
        start = self._starts.pop(run_id, None)
        if start is None:
            return

        _state.pop_parent_span_id(str(run_id))
        duration_ms = (time.perf_counter() - start["start_perf"]) * 1000

        try:
            fingerprint = compute_fingerprint(
                {"node": start["name"], "step": start["step"], "input": start["input"]}
            )

            recorded_input = start["input"]
            recorded_output = output
            config = _state.get_config()
            if config.redact is not None:
                if recorded_input is not None:
                    recorded_input = config.redact(recorded_input)
                if recorded_output is not None:
                    recorded_output = config.redact(recorded_output)

            span = Span(
                id=str(run_id),
                run_id=_state.get_run_id(),
                parent_id=start["parent_id"],
                type="node",
                name=start["name"],
                input=recorded_input,
                output=recorded_output,
                error=error,
                started_at=start["started_at"],
                duration_ms=duration_ms,
                fingerprint=fingerprint,
            )
            get_collector().add(span)
        except Exception:
            # Recording must never break the host application.
            print(f"agentreplay: failed to record node span ({start['name']})", file=sys.stderr)
