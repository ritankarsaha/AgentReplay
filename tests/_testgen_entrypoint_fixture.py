
from __future__ import annotations

import agentreplay


@agentreplay.tool
def lookup(term: str) -> str:
    raise AssertionError("real tool body should never run under mock_tools_mode()")


def main(recorded_input: dict) -> str:
    return lookup(recorded_input["term"])


def zero_arg_main() -> str:
    return "zero-arg-result"
