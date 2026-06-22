from __future__ import annotations

import importlib
import sys
from typing import TypedDict

import pytest

import agentreplay
from agentreplay import _state
from agentreplay.exceptions import ConfigurationError

langchain_core = pytest.importorskip("langchain_core")
langgraph = pytest.importorskip("langgraph")

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402

from agentreplay.adapters.langgraph import AgentReplayCallbackHandler  # noqa: E402
from agentreplay.serialize import safe_serialize  # noqa: E402

try:
    from anthropic.resources import messages as anthropic_messages
except ImportError:
    anthropic_messages = None


class State(TypedDict):
    text: str


def _build_two_node_graph(node_a, node_b, checkpointer=None):
    builder = StateGraph(State)
    builder.add_node("node_a", node_a)
    builder.add_node("node_b", node_b)
    builder.add_edge(START, "node_a")
    builder.add_edge("node_a", "node_b")
    builder.add_edge("node_b", END)
    return builder.compile(checkpointer=checkpointer)


def test_records_one_node_span_per_node_with_state_snapshots():
    def node_a(state):
        return {"text": state["text"] + "-a"}

    def node_b(state):
        return {"text": state["text"] + "-b"}

    graph = _build_two_node_graph(node_a, node_b)
    agentreplay.init(api_key="key", project_id="proj")

    result = graph.invoke({"text": "x"}, config={"callbacks": [AgentReplayCallbackHandler()]})
    assert result == {"text": "x-a-b"}

    spans = agentreplay.get_recorded_spans()
    node_spans = [s for s in spans if s.type == "node"]
    assert len(node_spans) == 2

    span_a = next(s for s in node_spans if s.name == "node_a")
    span_b = next(s for s in node_spans if s.name == "node_b")

    assert span_a.input == {"text": "x"}
    assert span_a.output == {"text": "x-a"}
    assert span_a.error is None
    assert span_a.run_id == _state.get_run_id()
    assert span_a.parent_id is None
    assert span_a.duration_ms >= 0

    assert span_b.input == {"text": "x-a"}
    assert span_b.output == {"text": "x-a-b"}
    assert span_b.parent_id is None


def test_node_error_records_error_span():
    def failing_node(state):
        raise RuntimeError("boom")

    builder = StateGraph(State)
    builder.add_node("failing_node", failing_node)
    builder.add_edge(START, "failing_node")
    builder.add_edge("failing_node", END)
    graph = builder.compile()

    agentreplay.init(api_key="key", project_id="proj")

    with pytest.raises(RuntimeError, match="boom"):
        graph.invoke({"text": "x"}, config={"callbacks": [AgentReplayCallbackHandler()]})

    spans = agentreplay.get_recorded_spans()
    node_spans = [s for s in spans if s.type == "node"]
    assert len(node_spans) == 1
    assert node_spans[0].name == "failing_node"
    assert node_spans[0].output is None
    assert node_spans[0].error == {"type": "RuntimeError", "message": "boom"}


@pytest.mark.skipif(anthropic_messages is None, reason="anthropic not installed")
def test_llm_span_inside_node_nests_under_node_span():
    class FakeMessage:
        def __init__(self, **kwargs):
            self._data = kwargs

        def model_dump(self):
            return dict(self._data)

    def _fake_create(self, **kwargs):
        return FakeMessage(
            id="msg_123",
            model=kwargs.get("model"),
            role="assistant",
            content=[{"type": "text", "text": "hello"}],
            stop_reason="end_turn",
            usage={"input_tokens": 1, "output_tokens": 1},
        )

    anthropic_messages.Messages.create = _fake_create

    def _call_llm():
        self_obj = anthropic_messages.Messages.__new__(anthropic_messages.Messages)
        return anthropic_messages.Messages.create(
            self_obj, model="claude-sonnet-4-6", messages=[{"role": "user", "content": "hi"}], max_tokens=10
        )

    def node_a(state):
        _call_llm()
        return {"text": state["text"] + "-a"}

    def node_b(state):
        return {"text": state["text"] + "-b"}

    graph = _build_two_node_graph(node_a, node_b)
    agentreplay.init(api_key="key", project_id="proj")

    graph.invoke({"text": "x"}, config={"callbacks": [AgentReplayCallbackHandler()]})

    spans = agentreplay.get_recorded_spans()
    node_a_span = next(s for s in spans if s.type == "node" and s.name == "node_a")
    node_b_span = next(s for s in spans if s.type == "node" and s.name == "node_b")
    llm_spans = [s for s in spans if s.type == "llm"]

    assert len(llm_spans) == 1
    assert llm_spans[0].parent_id == node_a_span.id
    assert node_b_span.parent_id is None

    # the parent stack must be empty again once the graph finishes
    assert _state.peek_parent_span_id() is None


async def test_ainvoke_records_one_node_span_per_node():
    async def node_a(state):
        return {"text": state["text"] + "-a"}

    async def node_b(state):
        return {"text": state["text"] + "-b"}

    graph = _build_two_node_graph(node_a, node_b)
    agentreplay.init(api_key="key", project_id="proj")

    result = await graph.ainvoke({"text": "x"}, config={"callbacks": [AgentReplayCallbackHandler()]})
    assert result == {"text": "x-a-b"}

    spans = agentreplay.get_recorded_spans()
    node_spans = [s for s in spans if s.type == "node"]
    assert len(node_spans) == 2

    span_a = next(s for s in node_spans if s.name == "node_a")
    span_b = next(s for s in node_spans if s.name == "node_b")
    assert span_a.input == {"text": "x"}
    assert span_a.output == {"text": "x-a"}
    assert span_b.input == {"text": "x-a"}
    assert span_b.output == {"text": "x-a-b"}

    # the parent stack must be empty again once the graph finishes
    assert _state.peek_parent_span_id() is None


async def test_astream_records_one_node_span_per_node():
    async def node_a(state):
        return {"text": state["text"] + "-a"}

    async def node_b(state):
        return {"text": state["text"] + "-b"}

    graph = _build_two_node_graph(node_a, node_b)
    agentreplay.init(api_key="key", project_id="proj")

    chunks = []
    async for chunk in graph.astream({"text": "x"}, config={"callbacks": [AgentReplayCallbackHandler()]}):
        chunks.append(chunk)

    assert chunks[-1] == {"node_b": {"text": "x-a-b"}}

    spans = agentreplay.get_recorded_spans()
    node_spans = [s for s in spans if s.type == "node"]
    assert len(node_spans) == 2
    assert {s.name for s in node_spans} == {"node_a", "node_b"}
    assert _state.peek_parent_span_id() is None


@pytest.mark.skipif(anthropic_messages is None, reason="anthropic not installed")
async def test_llm_span_inside_async_node_nests_under_node_span():
    class FakeMessage:
        def __init__(self, **kwargs):
            self._data = kwargs

        def model_dump(self):
            return dict(self._data)

    async def _fake_create(self, **kwargs):
        return FakeMessage(
            id="msg_123",
            model=kwargs.get("model"),
            role="assistant",
            content=[{"type": "text", "text": "hello"}],
            stop_reason="end_turn",
            usage={"input_tokens": 1, "output_tokens": 1},
        )

    anthropic_messages.AsyncMessages.create = _fake_create

    async def _call_llm():
        self_obj = anthropic_messages.AsyncMessages.__new__(anthropic_messages.AsyncMessages)
        return await anthropic_messages.AsyncMessages.create(
            self_obj, model="claude-sonnet-4-6", messages=[{"role": "user", "content": "hi"}], max_tokens=10
        )

    async def node_a(state):
        await _call_llm()
        return {"text": state["text"] + "-a"}

    async def node_b(state):
        return {"text": state["text"] + "-b"}

    graph = _build_two_node_graph(node_a, node_b)
    agentreplay.init(api_key="key", project_id="proj")

    await graph.ainvoke({"text": "x"}, config={"callbacks": [AgentReplayCallbackHandler()]})

    spans = agentreplay.get_recorded_spans()
    node_a_span = next(s for s in spans if s.type == "node" and s.name == "node_a")
    llm_spans = [s for s in spans if s.type == "llm"]

    assert len(llm_spans) == 1
    assert llm_spans[0].parent_id == node_a_span.id
    assert _state.peek_parent_span_id() is None


def test_wrap_checkpointer_records_checkpoint_span_per_superstep():
    from langgraph.checkpoint.memory import MemorySaver

    from agentreplay.adapters.langgraph import wrap_checkpointer

    def node_a(state):
        return {"text": state["text"] + "-a"}

    def node_b(state):
        return {"text": state["text"] + "-b"}

    checkpointer = wrap_checkpointer(MemorySaver())
    graph = _build_two_node_graph(node_a, node_b, checkpointer=checkpointer)
    agentreplay.init(api_key="key", project_id="proj")

    result = graph.invoke(
        {"text": "x"},
        config={"configurable": {"thread_id": "t1"}, "callbacks": [AgentReplayCallbackHandler()]},
    )
    assert result == {"text": "x-a-b"}

    spans = agentreplay.get_recorded_spans()
    checkpoint_spans = [s for s in spans if s.type == "checkpoint" and s.name == "langgraph.checkpoint"]

    # one checkpoint per superstep (input + node_a + node_b at minimum)
    assert len(checkpoint_spans) >= 3
    for span in checkpoint_spans:
        assert span.input["thread_id"] == "t1"
        assert isinstance(span.fingerprint, str)

    # each checkpoint has a distinct fingerprint (distinct checkpoint id)
    fingerprints = {s.fingerprint for s in checkpoint_spans}
    assert len(fingerprints) == len(checkpoint_spans)

    # the final checkpoint reflects the final graph state
    assert checkpoint_spans[-1].output == {"text": "x-a-b"}


async def test_wrap_checkpointer_aput_records_checkpoint_span():
    from langgraph.checkpoint.memory import MemorySaver

    from agentreplay.adapters.langgraph import wrap_checkpointer

    async def node_a(state):
        return {"text": state["text"] + "-a"}

    async def node_b(state):
        return {"text": state["text"] + "-b"}

    checkpointer = wrap_checkpointer(MemorySaver())
    graph = _build_two_node_graph(node_a, node_b, checkpointer=checkpointer)
    agentreplay.init(api_key="key", project_id="proj")

    await graph.ainvoke(
        {"text": "x"},
        config={"configurable": {"thread_id": "t2"}, "callbacks": [AgentReplayCallbackHandler()]},
    )

    spans = agentreplay.get_recorded_spans()
    checkpoint_spans = [s for s in spans if s.type == "checkpoint" and s.name == "langgraph.checkpoint"]
    assert len(checkpoint_spans) >= 3
    assert checkpoint_spans[-1].output == {"text": "x-a-b"}


def test_wrap_checkpointer_rejects_non_checkpointer():
    from agentreplay.adapters.langgraph import wrap_checkpointer

    with pytest.raises(ConfigurationError):
        wrap_checkpointer(object())


def test_disabled_mode_records_no_node_spans():
    def node_a(state):
        return {"text": state["text"] + "-a"}

    def node_b(state):
        return {"text": state["text"] + "-b"}

    graph = _build_two_node_graph(node_a, node_b)
    agentreplay.init(enabled=False)

    graph.invoke({"text": "x"}, config={"callbacks": [AgentReplayCallbackHandler()]})

    assert agentreplay.get_recorded_spans() == []


def test_fingerprint_is_deterministic_for_identical_node_input():
    def node_a(state):
        return {"text": state["text"] + "-a"}

    def node_b(state):
        return {"text": state["text"] + "-b"}

    graph = _build_two_node_graph(node_a, node_b)
    agentreplay.init(api_key="key", project_id="proj")

    graph.invoke({"text": "x"}, config={"callbacks": [AgentReplayCallbackHandler()]})
    graph.invoke({"text": "x"}, config={"callbacks": [AgentReplayCallbackHandler()]})

    spans = agentreplay.get_recorded_spans()
    node_a_spans = [s for s in spans if s.type == "node" and s.name == "node_a"]
    node_b_spans = [s for s in spans if s.type == "node" and s.name == "node_b"]

    # same node, same input ({"text": "x"} both times) -> same fingerprint
    assert node_a_spans[0].fingerprint == node_a_spans[1].fingerprint
    # different node / different input ("x" vs "x-a") -> different fingerprint
    assert node_a_spans[0].fingerprint != node_b_spans[0].fingerprint


class SecretState(TypedDict):
    text: str
    secret: str


def test_redact_callback_applied_to_node_input_and_output():
    def node_a(state):
        return {"text": state["text"] + "-a", "secret": "do-not-leak"}

    builder = StateGraph(SecretState)
    builder.add_node("node_a", node_a)
    builder.add_edge(START, "node_a")
    builder.add_edge("node_a", END)
    graph = builder.compile()

    def redact(payload):
        return {k: ("[REDACTED]" if k == "secret" else v) for k, v in payload.items()}

    agentreplay.init(api_key="key", project_id="proj", redact=redact)

    graph.invoke({"text": "x", "secret": "shh"}, config={"callbacks": [AgentReplayCallbackHandler()]})

    span = next(s for s in agentreplay.get_recorded_spans() if s.type == "node")
    assert span.input["secret"] == "[REDACTED]"
    assert span.output["secret"] == "[REDACTED]"
    assert isinstance(span.fingerprint, str)


def test_safe_serialize_handles_langchain_messages():
    value = {"messages": [HumanMessage(content="hi"), AIMessage(content="hello")], "n": 1}

    result = safe_serialize(value)

    assert result["n"] == 1
    assert result["messages"][0]["content"] == "hi"
    assert result["messages"][0]["type"] == "human"
    assert result["messages"][1]["content"] == "hello"
    assert result["messages"][1]["type"] == "ai"


def test_parent_span_stack_push_pop_peek_and_reset():
    assert _state.peek_parent_span_id() is None

    _state.push_parent_span_id("a")
    _state.push_parent_span_id("b")
    assert _state.peek_parent_span_id() == "b"

    # remove-by-value: popping the non-top entry doesn't disturb the top
    _state.pop_parent_span_id("a")
    assert _state.peek_parent_span_id() == "b"

    _state.pop_parent_span_id("b")
    assert _state.peek_parent_span_id() is None

    _state.push_parent_span_id("c")
    _state.reset()
    assert _state.peek_parent_span_id() is None


def test_raises_configuration_error_without_langchain_core():
    import agentreplay.adapters.langgraph as lg_module

    _MISSING = object()
    names = ["langchain_core", "langchain_core.callbacks", "langchain_core.callbacks.base"]
    saved = {name: sys.modules.get(name, _MISSING) for name in names}
    for name in names:
        sys.modules[name] = None  # type: ignore[assignment]

    try:
        importlib.reload(lg_module)
        with pytest.raises(ConfigurationError):
            lg_module.AgentReplayCallbackHandler()
    finally:
        for name, mod in saved.items():
            if mod is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
        importlib.reload(lg_module)
