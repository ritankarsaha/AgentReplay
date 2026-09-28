from __future__ import annotations

import pytest

from agentreplay.testgen import entrypoint as entrypoint_module
from agentreplay.testgen.entrypoint import call_entrypoint_with_input


def test_zero_arg_function_is_called_with_no_args():
    calls = []

    def main():
        calls.append("called")
        return "ok"

    result = call_entrypoint_with_input(main, {"job_posting": "hi"})
    assert result == "ok"
    assert calls == ["called"]


def test_one_arg_function_receives_recorded_input():
    captured = []

    def main(recorded_input):
        captured.append(recorded_input)
        return recorded_input["job_posting"]

    result = call_entrypoint_with_input(main, {"job_posting": "hi"})
    assert result == "hi"
    assert captured == [{"job_posting": "hi"}]


def test_function_with_default_value_still_receives_recorded_input():
    # A parameter existing at all (even with a default) means the function
    # opted in -- the recorded input should override the default, not be
    # ignored.
    def main(recorded_input=None):
        return recorded_input

    assert call_entrypoint_with_input(main, {"x": 1}) == {"x": 1}


def test_recorded_input_of_none_is_still_passed_through():
    def main(recorded_input):
        return recorded_input

    assert call_entrypoint_with_input(main, None) is None


def test_falls_back_to_zero_arg_call_when_signature_uninspectable(monkeypatch):
    def raise_value_error(func):
        raise ValueError("no signature available")

    monkeypatch.setattr(entrypoint_module.inspect, "signature", raise_value_error)

    calls = []

    def main():
        calls.append("called")
        return "fallback-ok"

    result = call_entrypoint_with_input(main, {"unused": True})
    assert result == "fallback-ok"
    assert calls == ["called"]


def test_propagates_exceptions_from_the_entrypoint():
    def main(recorded_input):
        raise RuntimeError("entrypoint exploded")

    with pytest.raises(RuntimeError, match="entrypoint exploded"):
        call_entrypoint_with_input(main, {})


# --- keyword-only parameter (Day 4 audit: "Day 4 pendings" -> resolved) -----


def test_keyword_only_parameter_receives_recorded_input():
    def main(*, recorded_input):
        return recorded_input["job_posting"]

    result = call_entrypoint_with_input(main, {"job_posting": "hi"})
    assert result == "hi"


def test_zero_arg_function_still_called_with_no_args_when_keyword_only_check_added():
    # Regression guard: the keyword-only branch must not affect the
    # already-covered zero-arg path above.
    calls = []

    def main():
        calls.append("called")
        return "ok"

    assert call_entrypoint_with_input(main, {"unused": True}) == "ok"
    assert calls == ["called"]


# --- async entrypoints (Day 4 audit: "Day 4 pendings" -> resolved) ----------


def test_async_zero_arg_entrypoint_is_actually_awaited():
    calls = []

    async def main():
        calls.append("ran")
        return "async-ok"

    result = call_entrypoint_with_input(main, {"unused": True})
    assert result == "async-ok"
    assert calls == ["ran"]  # would be [] if the coroutine were never awaited


def test_async_entrypoint_with_recorded_input_is_actually_awaited():
    async def main(recorded_input):
        return recorded_input["job_posting"]

    result = call_entrypoint_with_input(main, {"job_posting": "hi"})
    assert result == "hi"


def test_async_entrypoint_exceptions_propagate():
    async def main():
        raise RuntimeError("async entrypoint exploded")

    with pytest.raises(RuntimeError, match="async entrypoint exploded"):
        call_entrypoint_with_input(main, {})
