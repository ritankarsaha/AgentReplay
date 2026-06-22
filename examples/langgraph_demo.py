"""langgraph_demo — verification aid for chunk 2.4 (run-detail timeline).

A minimal 2-node LangGraph graph where each node makes one real LLM call
(same NIM/OpenAI pattern as `examples/resume_bot.py`), run through
`agentreplay.adapters.langgraph.AgentReplayCallbackHandler` (chunk 2.1).

This is the only way to produce a run with `type="node"` spans containing
nested `type="llm"` children — the node -> llm timeline the Day 2 checkpoint
in CLAUDE.md describes. Not part of 2.3/2.4 itself; a throwaway data
generator for the viewer.

Usage (from repo root):

    .venv/bin/python examples/langgraph_demo.py
"""
from __future__ import annotations

import os
from typing import TypedDict

import openai
from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

import agentreplay
from agentreplay.adapters.langgraph import AgentReplayCallbackHandler

load_dotenv()

NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
CANDIDATE_MODELS = [
    "meta/llama-3.1-8b-instruct",
    "mistralai/mistral-7b-instruct-v0.3",
    "google/gemma-2-9b-it",
    "microsoft/phi-3-mini-4k-instruct",
]


class State(TypedDict):
    job_posting: str
    keywords: str
    keyword_list: list[str]
    bullet: str


@agentreplay.tool
def parse_keyword_list(keywords_text: str) -> list[str]:
    """Turn the LLM's free-text keyword list into a clean list of strings.

    A `@agentreplay.tool`-decorated function (chunk 2.5) called from inside
    the `extract_keywords` node below, so its `type="tool"` span is recorded
    nested under that node's `type="node"` span (CLAUDE.md Day 2 checkpoint:
    node -> tool timeline).
    """
    lines = [line.strip(" -*0123456789.") for line in keywords_text.splitlines()]
    return [line for line in lines if line]


def _chat(client: openai.OpenAI, prompt: str) -> str:
    last_error: Exception | None = None
    for model in CANDIDATE_MODELS:
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content
        except openai.APIStatusError as exc:
            last_error = exc
            continue
    raise last_error  # type: ignore[misc]


def extract_keywords(state: State) -> dict:
    client = openai.OpenAI(base_url=NIM_BASE_URL, api_key=os.environ["NVIDIA_API_KEY"])
    keywords = _chat(
        client,
        "List the top 5 technical keywords a resume should target for this "
        f"job posting:\n\n{state['job_posting']}",
    )
    keyword_list = parse_keyword_list(keywords)
    return {"keywords": keywords, "keyword_list": keyword_list}


def rewrite_bullet(state: State) -> dict:
    client = openai.OpenAI(base_url=NIM_BASE_URL, api_key=os.environ["NVIDIA_API_KEY"])
    rewritten = _chat(
        client,
        "Rewrite this resume bullet point to naturally incorporate these "
        f"keywords where relevant:\n\nBullet: {state['bullet']}\n\nKeywords:\n{state['keywords']}",
    )
    return {"bullet": rewritten}


def build_graph():
    builder = StateGraph(State)
    builder.add_node("extract_keywords", extract_keywords)
    builder.add_node("rewrite_bullet", rewrite_bullet)
    builder.add_edge(START, "extract_keywords")
    builder.add_edge("extract_keywords", "rewrite_bullet")
    builder.add_edge("rewrite_bullet", END)
    return builder.compile()


def main() -> None:
    agentreplay.init(framework="langgraph")
    print("run_id:", agentreplay.get_run_id())

    graph = build_graph()
    initial_state: State = {
        "job_posting": (
            "We're hiring a Senior Backend Engineer to build and scale our "
            "event-driven payments platform. Must have deep experience with "
            "distributed systems, Python, Kafka, and PostgreSQL, plus a "
            "track record of mentoring engineers."
        ),
        "keywords": "",
        "keyword_list": [],
        "bullet": "Worked on the backend team and helped improve system reliability.",
    }

    result = graph.invoke(initial_state, config={"callbacks": [AgentReplayCallbackHandler()]})

    print("\n--- Extracted keywords ---")
    print(result["keywords"])
    print("\n--- Parsed keyword list ---")
    print(result["keyword_list"])
    print("\n--- Rewritten bullet ---")
    print(result["bullet"])

    agentreplay.flush()
    agentreplay.shutdown()


if __name__ == "__main__":
    main()
