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
Day 2 checkpoint. This works identically for `graph.invoke()`,
`graph.ainvoke()`, and `graph.astream()` (`run_inline = True` below is what
makes the async cases work — see its docstring).

Known limitation: nesting is tracked via a per-thread stack, not LangChain's
`run_id`/`parent_run_id` chain. This is correct for the common synchronous,
sequential-async, and thread-pool-parallel cases (all covered by
`tests/test_langgraph_adapter.py`, including `ainvoke`/`astream`), but
multiple LangGraph nodes running as concurrent `asyncio.Task`s on the SAME
thread (e.g. parallel branches awaited via `asyncio.gather` inside one event
loop) share one `threading.local` stack across tasks, so an LLM call in one
task can interleave with another task's push/pop and attribute to the wrong
sibling node. Fixing this properly needs a `contextvars.ContextVar`-based
stack (isolated per-Task) instead of `threading.local` — deferred until
dogfooding (§9) surfaces it with a concurrent-node graph.
"""

from __future__ import annotations

import sys
import time
import uuid
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

    # By default, `BaseCallbackHandler.run_inline = False` makes LangChain's
    # async callback manager dispatch our (sync) on_chain_start/on_chain_end
    # to a thread-pool executor — a DIFFERENT thread than the one running
    # the (async) node body. Since `_state`'s parent-span stack (chunk 2.1)
    # is per-thread, that desyncs push/peek: an LLM call inside an `async
    # def` node would see an empty stack and record `parent_id=None` instead
    # of nesting under the node span. `run_inline = True` forces the
    # callback manager to invoke our handler inline on the node's own
    # thread/task, keeping push/peek on the same per-thread stack for both
    # `graph.invoke()` and `graph.ainvoke()`/`astream()`.
    run_inline = True

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


def _record_checkpoint_span(config: Dict[str, Any], checkpoint: Dict[str, Any], metadata: Dict[str, Any]) -> None:
    if not _state.is_initialized() or not _state.get_config().enabled:
        return

    try:
        agentreplay_config = _state.get_config()
        thread_id = (config.get("configurable") or {}).get("thread_id")

        recorded_input: Dict[str, Any] = {
            "thread_id": thread_id,
            "step": metadata.get("step"),
            "source": metadata.get("source"),
        }
        recorded_output = safe_serialize(checkpoint.get("channel_values", {}))

        if agentreplay_config.redact is not None:
            recorded_input = agentreplay_config.redact(recorded_input)
            recorded_output = agentreplay_config.redact(recorded_output)

        fingerprint = compute_fingerprint(
            {"langgraph_checkpoint": checkpoint.get("id"), "thread_id": thread_id}
        )

        span = Span(
            id=str(uuid.uuid4()),
            run_id=_state.get_run_id(),
            parent_id=_state.peek_parent_span_id(),
            type="checkpoint",
            name="langgraph.checkpoint",
            input=recorded_input,
            output=recorded_output,
            error=None,
            started_at=datetime.now(timezone.utc),
            duration_ms=0.0,
            fingerprint=fingerprint,
        )
        get_collector().add(span)
    except Exception:
        # Recording must never break the host application.
        print("agentreplay: failed to record langgraph checkpoint span", file=sys.stderr)


def wrap_checkpointer(checkpointer: Any) -> Any:
    """Wrap a LangGraph `BaseCheckpointSaver` so every `put`/`aput` also
    records a `type="checkpoint"` span (CLAUDE.md §3.1/§3.3 "checkpointer
    wrapper").

    Unlike `AgentReplayCallbackHandler`'s per-node `type="node"` spans (which
    record each node's input/output slice), this records the FULL graph
    state (`checkpoint["channel_values"]`) as persisted after each superstep
    — the snapshot LangGraph itself uses to resume/replay a thread.

    Works by wrapping the checkpointer instance's `put`/`aput` bound methods
    in place (no subclassing needed, works for any `BaseCheckpointSaver`
    implementation: `MemorySaver`, `SqliteSaver`, `PostgresSaver`, ...).
    Returns the same instance for convenient chaining::

        checkpointer = wrap_checkpointer(MemorySaver())
        graph = builder.compile(checkpointer=checkpointer)
        graph.invoke(state, config={
            "configurable": {"thread_id": "1"},
            "callbacks": [AgentReplayCallbackHandler()],
        })
    """
    if not callable(getattr(checkpointer, "put", None)) or not callable(getattr(checkpointer, "aput", None)):
        raise ConfigurationError(
            "wrap_checkpointer() expects a LangGraph BaseCheckpointSaver "
            "(an object with put()/aput() methods)."
        )

    original_put = checkpointer.put
    original_aput = checkpointer.aput

    def wrapped_put(config: Dict[str, Any], checkpoint: Dict[str, Any], metadata: Dict[str, Any], new_versions: Any) -> Any:
        result = original_put(config, checkpoint, metadata, new_versions)
        _record_checkpoint_span(config, checkpoint, metadata)
        return result

    async def wrapped_aput(config: Dict[str, Any], checkpoint: Dict[str, Any], metadata: Dict[str, Any], new_versions: Any) -> Any:
        result = await original_aput(config, checkpoint, metadata, new_versions)
        _record_checkpoint_span(config, checkpoint, metadata)
        return result

    checkpointer.put = wrapped_put  # type: ignore[method-assign]
    checkpointer.aput = wrapped_aput  # type: ignore[method-assign]
    return checkpointer
