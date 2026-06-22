"""MAST failure taxonomy (CLAUDE.md §3.6: "Sonnet + MAST taxonomy").

The 14 core categories below are the published MAST taxonomy from
"Why Do Multi-Agent LLM Systems Fail?" (Cemri et al.), grouped into its
three phases (specification/design, inter-agent misalignment, task
verification). AgentReplay also targets single-agent/tool-calling agents,
which MAST's multi-agent framing doesn't cleanly cover, so three
AgentReplay-specific categories are appended for those cases. Both the
classifier's forced tool schema (`classifier.py`) and the system prompt's
category descriptions are generated from this one module so they can never
drift apart.
"""

from __future__ import annotations

from typing import List, Tuple

# (key, human-readable description). Order matters only for prompt
# readability — grouped by MAST's three phases, AgentReplay extensions last.
MAST_CATEGORIES: List[Tuple[str, str]] = [
    # Phase 1 — Specification & System Design Failures
    ("disobey_task_specification", "The agent ignored or violated explicit constraints of the task it was given."),
    ("disobey_role_specification", "The agent acted outside its assigned role or persona."),
    ("step_repetition", "The agent unnecessarily repeated an identical step or action it had already taken."),
    ("loss_of_conversation_history", "The agent lost track of, or failed to use, earlier context it should have remembered."),
    ("unaware_of_termination_conditions", "The agent didn't recognize that the task was complete (or should have stopped) and kept going, or stopped for the wrong reason."),
    # Phase 2 — Inter-Agent Misalignment
    ("conversation_reset", "The conversation or shared state unexpectedly reset, losing prior progress."),
    ("fail_to_ask_for_clarification", "The agent proceeded on ambiguous or insufficient input instead of asking for clarification."),
    ("task_derailment", "The agent drifted away from the original task into unrelated work."),
    ("information_withholding", "An agent had information another agent/step needed and didn't share it."),
    ("ignored_other_agent_input", "The agent ignored or discarded another agent's or tool's output."),
    ("reasoning_action_mismatch", "The agent's stated reasoning didn't match the action it actually took."),
    # Phase 3 — Task Verification & Termination
    ("premature_termination", "The agent stopped before the task was actually complete."),
    ("no_or_incomplete_verification", "The agent didn't verify its output/results before finishing, or verified only partially."),
    ("incorrect_verification", "The agent's verification logic itself was wrong and passed bad output as correct."),
    # AgentReplay extensions (single-agent / tool-calling failures MAST's
    # multi-agent framing doesn't name directly)
    ("tool_execution_error", "A tool/function call raised an exception or returned malformed/unexpected output."),
    ("unhandled_exception", "The agent process crashed with an unhandled exception not attributable to a tool call."),
    ("other", "The failure doesn't fit any category above."),
]

MAST_CATEGORY_KEYS: List[str] = [key for key, _ in MAST_CATEGORIES]


def render_taxonomy_for_prompt() -> str:
    """Render the taxonomy as a numbered list for the classifier's system prompt."""
    return "\n".join(f"- {key}: {description}" for key, description in MAST_CATEGORIES)
