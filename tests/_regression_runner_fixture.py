"""Fixture module for tests/test_regression_runner.py — NOT a test file itself
(leading underscore keeps pytest from trying to collect it).

`search` is a real `@agentreplay.tool`-decorated function whose body must
never run under `mock_tools_mode()` — it raises if it ever actually
executes, so a test that accidentally lets the real body run fails loudly.
"""

from __future__ import annotations

import agentreplay


@agentreplay.tool
def search(query: str) -> str:
    raise RuntimeError("real tool body must never run under mock_tools_mode")


def main(payload):
    return {"result": search(payload["query"])}


def silent(payload):
    """Never calls any tool — for must_call_tools-violation tests."""
    return {"result": payload["query"]}


def boom(payload):
    raise RuntimeError("entrypoint exploded")
