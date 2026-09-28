from __future__ import annotations

from agentreplay._async_call import call_maybe_async


def test_non_awaitable_passed_through_unchanged():
    assert call_maybe_async("plain value") == "plain value"
    assert call_maybe_async(None) is None
    assert call_maybe_async(42) == 42


def test_coroutine_is_awaited_to_completion():
    calls = []

    async def coro():
        calls.append("ran")
        return "done"

    assert call_maybe_async(coro()) == "done"
    assert calls == ["ran"]
