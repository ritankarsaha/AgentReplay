from __future__ import annotations

from typing import Any, Optional

from . import common

_original_sync_create: Optional[Any] = None
_original_async_create: Optional[Any] = None
_patched = False


def patch_anthropic() -> bool:
    """Monkey-patch anthropic.Anthropic/AsyncAnthropic .messages.create to record spans.

    Idempotent. Returns False (no-op) if the anthropic package isn't
    installed — the SDK must not require it.
    """
    global _original_sync_create, _original_async_create, _patched
    if _patched:
        return True

    try:
        from anthropic.resources import messages as anthropic_messages
    except ImportError:
        return False

    _original_sync_create = anthropic_messages.Messages.create
    _original_async_create = anthropic_messages.AsyncMessages.create

    anthropic_messages.Messages.create = common.wrap_sync_create(
        "anthropic.messages.create", _original_sync_create
    )
    anthropic_messages.AsyncMessages.create = common.wrap_async_create(
        "anthropic.messages.create", _original_async_create
    )

    _patched = True
    return True


def unpatch_anthropic() -> None:
    """Restore the original Messages.create / AsyncMessages.create. Mainly for tests."""
    global _patched
    if not _patched:
        return

    from anthropic.resources import messages as anthropic_messages

    anthropic_messages.Messages.create = _original_sync_create
    anthropic_messages.AsyncMessages.create = _original_async_create
    _patched = False
