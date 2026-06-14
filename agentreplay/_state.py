from __future__ import annotations

import threading
from typing import List, Optional

from .config import Config
from .exceptions import ConfigurationError
from .exporter import BackgroundExporter

_lock = threading.Lock()
_config: Optional[Config] = None
_run_id: Optional[str] = None
_exporter: Optional[BackgroundExporter] = None

# Thread-local stack of "current node span id" (chunk 2.1). Framework
# adapters (e.g. the LangGraph callback handler) push the active node's span
# id while a node is executing, so that LLM/tool spans recorded via Layer 1
# patching (1.2/1.3) and Layer 3 tool wrapping nest under that node.
_node_stack_local = threading.local()


def set_config(config: Config) -> None:
    global _config
    with _lock:
        _config = config


def get_config() -> Config:
    if _config is None:
        raise ConfigurationError(
            "agentreplay is not initialized. Call agentreplay.init() first."
        )
    return _config


def is_initialized() -> bool:
    return _config is not None


def set_run_id(run_id: str) -> None:
    global _run_id
    with _lock:
        _run_id = run_id


def get_run_id() -> str:
    if _run_id is None:
        raise ConfigurationError(
            "agentreplay is not initialized. Call agentreplay.init() first."
        )
    return _run_id


def set_exporter(exporter: Optional[BackgroundExporter]) -> None:
    global _exporter
    with _lock:
        _exporter = exporter


def get_exporter() -> Optional[BackgroundExporter]:
    return _exporter


def _node_stack() -> List[str]:
    stack = getattr(_node_stack_local, "stack", None)
    if stack is None:
        stack = []
        _node_stack_local.stack = stack
    return stack


def push_parent_span_id(span_id: str) -> None:
    """Mark `span_id` (a node span) as the current parent for this thread."""
    _node_stack().append(span_id)


def pop_parent_span_id(span_id: str) -> None:
    """Unmark `span_id` as an active parent.

    Removes by value (not strict LIFO pop): node enter/exit is normally
    well-nested per thread, but async/concurrent node execution can finish
    out of order, so a plain `pop()` could evict the wrong entry.
    """
    stack = _node_stack()
    try:
        stack.remove(span_id)
    except ValueError:
        pass


def peek_parent_span_id() -> Optional[str]:
    """Return the innermost active node span id for this thread, if any."""
    stack = _node_stack()
    return stack[-1] if stack else None


def reset() -> None:
    """Clear global state. Intended for tests."""
    global _config, _run_id, _exporter
    with _lock:
        if _exporter is not None:
            _exporter.shutdown()
        _config = None
        _run_id = None
        _exporter = None
    _node_stack().clear()
