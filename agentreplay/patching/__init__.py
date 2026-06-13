from __future__ import annotations

from . import anthropic_patch, openai_patch, responses_patch


def patch_all() -> None:
    anthropic_patch.patch_anthropic()
    openai_patch.patch_openai()
    responses_patch.patch_openai_responses()


def unpatch_all() -> None:
    anthropic_patch.unpatch_anthropic()
    openai_patch.unpatch_openai()
    responses_patch.unpatch_openai_responses()
