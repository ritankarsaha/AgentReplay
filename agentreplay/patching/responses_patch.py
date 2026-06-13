from __future__ import annotations

from typing import Any, Optional

from . import common

_original_sync_create: Optional[Any] = None
_original_async_create: Optional[Any] = None
_patched = False


def patch_openai_responses() -> bool:
    """Monkey-patch openai.OpenAI/AsyncOpenAI .responses.create to record spans.

    Idempotent. Returns False (no-op) if the openai package isn't installed,
    or if it's old enough not to ship the Responses API.

    This is the `client.responses.create` analog of `openai_patch.py`'s
    `chat.completions.create` patch (deferred in 1.5, see PROGRESS.md item 5) —
    same recording logic via `common.wrap_*_create`, just a different
    Stainless-generated resource class.
    """
    global _original_sync_create, _original_async_create, _patched
    if _patched:
        return True

    try:
        from openai.resources.responses import responses as openai_responses
    except ImportError:
        return False

    _original_sync_create = openai_responses.Responses.create
    _original_async_create = openai_responses.AsyncResponses.create

    openai_responses.Responses.create = common.wrap_sync_create(
        "openai.responses.create", _original_sync_create
    )
    openai_responses.AsyncResponses.create = common.wrap_async_create(
        "openai.responses.create", _original_async_create
    )

    _patched = True
    return True


def unpatch_openai_responses() -> None:
    """Restore the original Responses.create / AsyncResponses.create. Mainly for tests."""
    global _patched
    if not _patched:
        return

    from openai.resources.responses import responses as openai_responses

    openai_responses.Responses.create = _original_sync_create
    openai_responses.AsyncResponses.create = _original_async_create
    _patched = False
