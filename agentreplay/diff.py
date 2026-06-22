"""Structural diff between an expected (recorded) and actual (live) payload.

Used by `ReplayDivergence` (CLAUDE.md §3.4, chunk 3.3) to answer "your agent
diverged here" with a concrete, field-level difference instead of a raw
repr dump of two unrelated dicts. Lives in core (not `agentreplay.replay`)
for the same reason the replay exceptions do: `agentreplay/tool.py` (core)
needs it too, and core must not depend on the optional `agentreplay.replay`
subpackage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

MISSING = object()
"""Sentinel: a dict key / list index present on one side of a diff but not the other."""

NEVER_RECORDED = object()
"""Sentinel `expected` value: this call site has no recorded calls at all
(as opposed to having recorded calls that were all already consumed)."""


@dataclass
class FieldDiff:
    """One leaf-level difference, at a JSON-path-like `path` (e.g. `$.messages[0].content`)."""

    path: str
    expected: Any
    actual: Any

    def __repr__(self) -> str:
        return f"{self.path}: {_format_value(self.expected)} -> {_format_value(self.actual)}"


def _format_value(value: Any) -> str:
    if value is MISSING:
        return "<absent>"
    if value is NEVER_RECORDED:
        return "<call site never recorded>"
    return repr(value)


def diff_payloads(expected: Any, actual: Any, path: str = "$") -> List[FieldDiff]:
    """Recursively diff two JSON-like values into a flat list of leaf-level differences.

    `expected`/`actual` are dicts/lists/scalars (the shapes `Span.input`
    and a live request payload already are). Equal values recurse with no
    diff emitted; differing dict keys or list indices are reported with
    `MISSING` on whichever side lacks them. `expected is NEVER_RECORDED`
    short-circuits to a single root-level diff rather than recursing.
    """
    if expected is NEVER_RECORDED:
        return [FieldDiff(path, expected, actual)]

    if isinstance(expected, dict) and isinstance(actual, dict):
        diffs: List[FieldDiff] = []
        for key in sorted(set(expected) | set(actual), key=str):
            sub_path = f"{path}.{key}"
            exp_val = expected.get(key, MISSING)
            act_val = actual.get(key, MISSING)
            if exp_val is MISSING or act_val is MISSING:
                if exp_val != act_val:
                    diffs.append(FieldDiff(sub_path, exp_val, act_val))
            elif exp_val != act_val:
                diffs.extend(diff_payloads(exp_val, act_val, sub_path))
        return diffs

    if isinstance(expected, list) and isinstance(actual, list):
        diffs = []
        for i in range(max(len(expected), len(actual))):
            sub_path = f"{path}[{i}]"
            exp_val = expected[i] if i < len(expected) else MISSING
            act_val = actual[i] if i < len(actual) else MISSING
            if exp_val is MISSING or act_val is MISSING:
                diffs.append(FieldDiff(sub_path, exp_val, act_val))
            elif exp_val != act_val:
                diffs.extend(diff_payloads(exp_val, act_val, sub_path))
        return diffs

    if expected != actual:
        return [FieldDiff(path, expected, actual)]
    return []


def format_diff(diffs: List[FieldDiff]) -> str:
    """Render a diff list as an indented, human-readable block (one line per field)."""
    if not diffs:
        return "  (no field-level differences — payloads are structurally identical)"
    return "\n".join(f"  {d}" for d in diffs)
