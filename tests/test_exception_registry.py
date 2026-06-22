from __future__ import annotations

from agentreplay.exception_registry import resolve_exception_class
from agentreplay.exceptions import ReplayedError


def test_resolves_builtin_exception_by_name():
    assert resolve_exception_class("ValueError") is ValueError
    assert resolve_exception_class("KeyError") is KeyError
    assert resolve_exception_class("RuntimeError") is RuntimeError


def test_returns_none_for_unknown_name():
    assert resolve_exception_class("TotallyNotARealExceptionType") is None


def test_returns_none_for_falsy_input():
    assert resolve_exception_class(None) is None
    assert resolve_exception_class("") is None


def test_resolves_anthropic_sdk_exception():
    import anthropic

    resolved = resolve_exception_class("RateLimitError")
    assert resolved is anthropic.RateLimitError


def test_resolves_anthropic_api_error_base_class():
    import anthropic

    assert resolve_exception_class("APIConnectionError") is anthropic.APIConnectionError


def test_replayed_error_carries_resolved_exception_class():
    exc = ReplayedError({"type": "ValueError", "message": "bad input"})
    assert exc.original_exception_class is ValueError
    assert exc.original_type == "ValueError"
    assert exc.original_message == "bad input"


def test_replayed_error_exception_class_none_when_unrecognized():
    exc = ReplayedError({"type": "SomeCustomUserException", "message": "x"})
    assert exc.original_exception_class is None


def test_replayed_error_handles_missing_type():
    exc = ReplayedError({"message": "no type given"})
    assert exc.original_type is None
    assert exc.original_exception_class is None
