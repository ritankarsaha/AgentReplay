"""Fixture module for tests/test_replay_runner.py — NOT a test file itself
(leading underscore keeps pytest from trying to collect it).

Stands in for a real agent module like `examples/resume_bot.py`: it calls
`agentreplay.init()` itself (the normal pattern) and makes a real LLM call,
so `resolve_entrypoint()`/`replay_run()` can be exercised against something
that imports/behaves like real agent code, not a bare lambda.
"""

from __future__ import annotations

import anthropic

import agentreplay

not_callable = "this is not callable"


def main() -> str:
    agentreplay.init(api_key="key", project_id="proj")
    client = anthropic.Anthropic(api_key="sk-fake")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=100,
        messages=[{"role": "user", "content": "hi"}],
    )
    return response.content[0].text


def boom() -> None:
    raise RuntimeError("entrypoint exploded")
