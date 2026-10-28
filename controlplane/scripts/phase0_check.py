"""Checks that a Muse Spark call is recorded as an `llm` span. Spans stay in memory.

    python -m controlplane.scripts.phase0_check
"""

from __future__ import annotations

import sys

import agentreplay
from controlplane import meta

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def main() -> int:
    agentreplay.init(
        api_key="phase0-check", endpoint="http://127.0.0.1:9", flush_interval=3600, agent_version="phase0"
    )
    answer = meta.chat("Reply with exactly one word: pong")
    spans = [s for s in agentreplay.get_recorded_spans() if s.type == "llm"]
    print(f"model reply : {answer!r}")
    print(f"llm spans   : {len(spans)}")
    if not spans:
        print("FAIL: no llm span was recorded", file=sys.stderr)
        return 1
    out = spans[-1].output or {}
    print(f"span model  : {out.get('model')}")
    print(f"span usage  : {out.get('usage')}")
    from importlib import import_module

    try:
        pricing = import_module("app.pricing")
        print(f"est. cost   : ${pricing.span_cost_usd(spans[-1].input, out)}")
    except ImportError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
