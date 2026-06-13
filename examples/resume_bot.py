"""resume-bot — the Day 1 / chunk 1.6 checkpoint demo agent.

A tiny two-step "agent": given a job posting and a resume bullet point, it
1. asks an LLM to extract the target keywords from the job posting, then
2. asks an LLM to rewrite the bullet point to incorporate those keywords.

Each step is a real LLM call instrumented by `agentreplay.init()` (chunks
1.2/1.3's OpenAI-compatible patch). The point isn't the resume-rewriting
itself — it's the smallest realistic stand-in for the "resume bot" referenced
throughout CLAUDE.md's Day 1 checkpoint ("run resume bot -> query Postgres ->
see real LLM call spans"): it proves the SDK -> background exporter -> ingest
API -> Postgres pipeline works end-to-end against real LLM traffic.

Uses NVIDIA NIM's OpenAI-compatible free endpoints as a stand-in for a real
ANTHROPIC_API_KEY (see PROGRESS.md "Blockers" — revisit later; the SDK's
Anthropic patch from chunk 1.2 is what production agents will actually use).
The SDK's OpenAI patch covers NIM automatically — same client, different
base_url, zero NIM-specific code. CANDIDATE_MODELS is tried in order and
falls back on error (rate limit / model retired) so the demo is robust to
NIM's free-tier limits (~40 rpm) and catalog changes.

Usage (from repo root):

    .venv/bin/python examples/resume_bot.py

Reads NVIDIA_API_KEY, AGENTREPLAY_API_KEY, AGENTREPLAY_PROJECT_ID,
AGENTREPLAY_ENDPOINT from `.env` (repo root) via python-dotenv, or the shell
environment. Then check `GET {AGENTREPLAY_ENDPOINT}/v1/runs/{run_id}` for the
run + its spans.
"""
from __future__ import annotations

import os

import openai
from dotenv import load_dotenv

import agentreplay

load_dotenv()

NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"

# Free-tier NIM models, tried in order. Each attempt (success or error) is
# still recorded as its own span, so a fallback also exercises the SDK's
# error-span path (chunks 1.2/1.3).
CANDIDATE_MODELS = [
    "meta/llama-3.1-8b-instruct",
    "mistralai/mistral-7b-instruct-v0.3",
    "google/gemma-2-9b-it",
    "microsoft/phi-3-mini-4k-instruct",
]

JOB_POSTING = """\
We're hiring a Senior Backend Engineer to build and scale our event-driven
payments platform. Must have deep experience with distributed systems,
Python, Kafka, and PostgreSQL, plus a track record of mentoring engineers.
"""

RESUME_BULLET = "Worked on the backend team and helped improve system reliability."


def chat(client: openai.OpenAI, prompt: str) -> str:
    """Call the first working model in CANDIDATE_MODELS, falling back on error."""
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


def extract_keywords(client: openai.OpenAI, job_posting: str) -> str:
    return chat(
        client,
        "List the top 5 technical keywords a resume should target for this "
        f"job posting:\n\n{job_posting}",
    )


def rewrite_bullet(client: openai.OpenAI, bullet: str, keywords: str) -> str:
    return chat(
        client,
        "Rewrite this resume bullet point to naturally incorporate these "
        f"keywords where relevant:\n\nBullet: {bullet}\n\nKeywords:\n{keywords}",
    )


def main() -> None:
    # framework="raw" — this script patches openai directly (CLAUDE.md §3.3
    # Layer 1), no LangGraph/CrewAI adapter. Populates runs.framework
    # (chunk "run-lifecycle metadata"); runs.agent_version defaults to the
    # current git SHA if this repo is a git checkout, else stays null.
    agentreplay.init(framework="raw")
    print("run_id:", agentreplay.get_run_id())

    client = openai.OpenAI(base_url=NIM_BASE_URL, api_key=os.environ["NVIDIA_API_KEY"])

    print("\n--- Extracting keywords from job posting ---")
    keywords = extract_keywords(client, JOB_POSTING)
    print(keywords)

    print("\n--- Rewriting resume bullet ---")
    rewritten = rewrite_bullet(client, RESUME_BULLET, keywords)
    print(rewritten)

    agentreplay.flush()
    agentreplay.shutdown()


if __name__ == "__main__":
    main()
