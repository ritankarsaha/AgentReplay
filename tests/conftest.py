from __future__ import annotations

import httpx
import pytest

from agentreplay import _state, exporter
from agentreplay.collector import get_collector
from agentreplay.patching import anthropic_patch, openai_patch, responses_patch

try:
    from anthropic.resources import messages as anthropic_messages
except ImportError:
    anthropic_messages = None

try:
    from openai.resources.chat import completions as openai_completions
except ImportError:
    openai_completions = None

try:
    from openai.resources.responses import responses as openai_responses
except ImportError:
    openai_responses = None


def _no_network_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(202)


@pytest.fixture(autouse=True)
def _agentreplay_clean_state(monkeypatch):
    """Reset agentreplay global state and undo any client patching around every test.

    patch_all() touches both Anthropic and OpenAI classes regardless of which
    provider a given test targets, and patching is idempotent via module-level
    `_patched` flags — so isolation has to reset those flags AND restore the
    pristine class attributes, otherwise a later test's `init()` won't re-wrap
    that test's fake `create` function.

    Also: agentreplay.init() (enabled=True, the default) starts a real
    BackgroundExporter. To keep the suite network-free and fast, patch the
    exporter's HTTP client factory to use an in-memory MockTransport for any
    test that goes through init() rather than constructing BackgroundExporter
    directly. Tests that need to inspect/control HTTP behavior should
    construct BackgroundExporter(..., client=...) themselves.
    """
    pristine = {}
    if anthropic_messages is not None:
        pristine["a_sync"] = anthropic_messages.Messages.create
        pristine["a_async"] = anthropic_messages.AsyncMessages.create
    if openai_completions is not None:
        pristine["o_sync"] = openai_completions.Completions.create
        pristine["o_async"] = openai_completions.AsyncCompletions.create
    if openai_responses is not None:
        pristine["r_sync"] = openai_responses.Responses.create
        pristine["r_async"] = openai_responses.AsyncResponses.create

    anthropic_patch._patched = False
    openai_patch._patched = False
    responses_patch._patched = False
    monkeypatch.setattr(
        exporter,
        "_build_client",
        lambda config: httpx.Client(
            base_url="http://agentreplay.test", transport=httpx.MockTransport(_no_network_handler)
        ),
    )
    _state.reset()
    get_collector().clear()

    yield

    if anthropic_messages is not None:
        anthropic_messages.Messages.create = pristine["a_sync"]
        anthropic_messages.AsyncMessages.create = pristine["a_async"]
    if openai_completions is not None:
        openai_completions.Completions.create = pristine["o_sync"]
        openai_completions.AsyncCompletions.create = pristine["o_async"]
    if openai_responses is not None:
        openai_responses.Responses.create = pristine["r_sync"]
        openai_responses.AsyncResponses.create = pristine["r_async"]

    anthropic_patch._patched = False
    openai_patch._patched = False
    responses_patch._patched = False
    _state.reset()
    get_collector().clear()
