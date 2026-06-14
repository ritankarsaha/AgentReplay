"""Framework adapters (CLAUDE.md §3.3 Layer 2: "depth" beyond client patching).

Each adapter is an optional extra — importing this package itself has no
dependencies beyond the rest of `agentreplay`. Submodules (e.g. `.langgraph`)
import their target framework lazily and raise `ConfigurationError` if it
isn't installed, so the SDK core never gains a hard dependency on any
particular agent framework.
"""

from __future__ import annotations

__all__: list[str] = []
