from __future__ import annotations

from typing import Any, Optional

from . import common

_original_sync_create: Optional[Any] = None
_original_async_create: Optional[Any] = None
_patched = False


def patch_openai() -> bool:
    """Monkey-patch openai.OpenAI/AsyncOpenAI .chat.completions.create to record spans.

    Idempotent. Returns False (no-op) if the openai package isn't installed.

    NOTE: this also covers NVIDIA NIM-served models — NIM exposes an
    OpenAI-compatible API via this same client class (just a different
    base_url), so no separate interception code is needed (CLAUDE.md §3.3).
    """
    global _original_sync_create, _original_async_create, _patched
    if _patched:
        return True

    try:
        from openai.resources.chat import completions as openai_completions
    except ImportError:
        return False

    _original_sync_create = openai_completions.Completions.create
    _original_async_create = openai_completions.AsyncCompletions.create

    openai_completions.Completions.create = common.wrap_sync_create(
        "openai.chat.completions.create", _original_sync_create
    )
    openai_completions.AsyncCompletions.create = common.wrap_async_create(
        "openai.chat.completions.create", _original_async_create
    )

    _patched = True
    return True


def unpatch_openai() -> None:
    """Restore the original Completions.create / AsyncCompletions.create. Mainly for tests."""
    global _patched
    if not _patched:
        return

    from openai.resources.chat import completions as openai_completions

    openai_completions.Completions.create = _original_sync_create
    openai_completions.AsyncCompletions.create = _original_async_create
    _patched = False
