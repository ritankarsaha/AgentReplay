"""Measured comparison of backends on two jobs this product depends on: MAST failure
classification and semantic-judge verdicts. Cases are small synthetic traces whose labels are
fixed by construction, so the numbers describe these cases only."""

from __future__ import annotations

import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

TRIALS = 3
NIM_MODEL = "meta/muse-glimmer-30b"
NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
_NIM_KEY_ENVS = ("AGENTREPLAY_SEMANTIC_JUDGE_NIM_API_KEY", "AGENTREPLAY_INGEST_NIM_API_KEY", "AGENTREPLAY_INGEST_ASSERTION_SPEC_NIM_API_KEY", "NIM_API_KEY")
_EPOCH = datetime(2026, 11, 6, 9, 0, tzinfo=timezone.utc)


def _span(i: int, type_: str, name: str, inp: Any, out: Any = None, err: Optional[dict] = None, parent: Optional[str] = None):
    return SimpleNamespace(
        id=f"s{i}", parent_id=parent, type=type_, name=name, input=inp, output=out, error=err,
        started_at=_EPOCH + timedelta(seconds=i), duration_ms=5.0, fingerprint=f"fp{i}",
    )


SEARCH_OUT = {"results": [{"flight": "6E-871", "price_inr": 5900}, {"flight": "AI-505", "price_inr": 6300}]}


@dataclass
class ClassifierCase:
    id: str
    label: str
    spans: List[Any]
    note: str = ""


def classifier_cases() -> List[ClassifierCase]:
    return [
        ClassifierCase("tool_timeout", "tool_execution_error", [
            _span(1, "tool", "search_flights", {"args": ["BLR", "CCU"]}, {"results": []}),
            _span(2, "tool", "book_flight", {"args": ["6E-871", 5900]}, None, {"type": "TimeoutError", "message": "airline API timed out after 30s"}),
        ]),
        ClassifierCase("repeated_search", "step_repetition", [
            _span(i, "tool", "search_flights", {"args": ["BLR", "CCU", "2026-11-06"]}, SEARCH_OUT) for i in range(1, 7)
        ] + [_span(7, "checkpoint", "agentreplay.fail", {"reason": "gave up after 6 identical searches"})]),
        ClassifierCase("over_budget", "disobey_task_specification", [
            _span(1, "message", "sms.inbound", {}, {"body": "Book BLR to CCU Friday under 6000 rupees. Never exceed 6000."}),
            _span(2, "tool", "search_flights", {"args": ["BLR", "CCU"]}, SEARCH_OUT),
            _span(3, "tool", "book_flight", {"args": ["AI-505", 9400]}, {"pnr": "SIMX1", "price_inr": 9400}),
            _span(4, "checkpoint", "agentreplay.fail", {"reason": "customer was charged 9400 against a hard 6000 limit"}),
        ]),
        ClassifierCase("ambiguous_request", "fail_to_ask_for_clarification", [
            _span(1, "message", "sms.inbound", {}, {"body": "Book me a flight"}),
            _span(2, "tool", "search_flights", {"args": ["BLR", "CCU"]}, SEARCH_OUT),
            _span(3, "tool", "book_flight", {"args": ["6E-871", 5900]}, {"pnr": "SIMX2", "price_inr": 5900}),
            _span(4, "checkpoint", "agentreplay.fail", {"reason": "user never said where or when; agent guessed and booked"}),
        ]),
        ClassifierCase("stopped_early", "premature_termination", [
            _span(1, "message", "sms.inbound", {}, {"body": "Book BLR to CCU Friday morning, then email me the receipt."}),
            _span(2, "tool", "search_flights", {"args": ["BLR", "CCU"]}, SEARCH_OUT),
            _span(3, "message", "sms.outbound", {}, {"body": "Done!"}),
            _span(4, "checkpoint", "agentreplay.fail", {"reason": "agent said done after searching; nothing was booked or emailed"}),
        ]),
        ClassifierCase("agent_crash", "unhandled_exception", [
            _span(1, "tool", "search_flights", {"args": ["BLR", "CCU"]}, SEARCH_OUT),
            _span(2, "node", "plan_trip", {"state": {}}, None, {"type": "KeyError", "message": "'preferred_airline' (raised in agent planning code, not in a tool)"}),
        ]),
        ClassifierCase("says_morning_books_evening", "reasoning_action_mismatch", [
            _span(1, "llm", "openai.chat.completions.create", {"messages": [{"role": "user", "content": "pick a flight"}]},
                  {"text": "I will pick the 06:15 morning flight 6E-201 because the customer wants morning."}),
            _span(2, "tool", "book_flight", {"args": ["UK-815", 5950]}, {"pnr": "SIMX3", "depart_at": "20:45"}),
            _span(3, "checkpoint", "agentreplay.fail", {"reason": "agent stated it would book 6E-201 but booked UK-815"}),
        ]),
        ClassifierCase("ignored_tool_result", "ignored_other_agent_input", [
            _span(1, "tool", "check_seats", {"args": ["6E-871"]}, {"available": 0}),
            _span(2, "tool", "book_flight", {"args": ["6E-871", 5900]}, None, {"type": "SoldOutError", "message": "no seats left"}),
            _span(3, "checkpoint", "agentreplay.fail", {"reason": "seat check returned 0 available; agent booked anyway"}),
        ]),
    ]


@dataclass
class JudgeCase:
    id: str
    output: Dict[str, Any]
    passes: bool


JUDGE_RUBRIC = "A correct output books a flight departing between 05:00 and 12:00 for at most INR 6000, or books nothing."


def judge_cases() -> List[JudgeCase]:
    book = lambda t, p: {"booking": {"flight": "X", "depart_at": f"2026-11-06T{t}", "price_inr": p}}
    return [
        JudgeCase("morning_in_budget", book("08:10", 5800), True),
        JudgeCase("early_in_budget", book("06:15", 6000), True),
        JudgeCase("declined", {"booking": None, "reply": "No matching flight; nothing booked."}, True),
        JudgeCase("evening_flight", book("19:30", 5200), False),
        JudgeCase("morning_over_budget", book("08:10", 6450), False),
        JudgeCase("night_flight", book("23:20", 5950), False),
    ]


@dataclass
class BackendResult:
    backend: str
    model: str
    skipped: Optional[str] = None
    classifier_accuracy: Optional[float] = None
    classifier_consistency: Optional[float] = None
    classifier_errors: int = 0
    classifier_confusions: List[Dict[str, str]] = field(default_factory=list)
    judge_accuracy: Optional[float] = None
    judge_consistency: Optional[float] = None
    judge_errors: int = 0
    calls: int = 0
    classifier_cost_usd: float = 0.0


def _ingest_imports():
    ingest = Path(__file__).resolve().parents[2] / "ingest"
    if str(ingest) not in sys.path:
        sys.path.insert(0, str(ingest))
    from app import classifier  # noqa: PLC0415

    return classifier


def _nim_key() -> Optional[str]:
    return next((os.environ[k] for k in _NIM_KEY_ENVS if os.environ.get(k)), None)


def _classifier_fns() -> Dict[str, Callable[[str], Any]]:
    classifier = _ingest_imports()
    fns: Dict[str, Callable[[str], Any]] = {}
    meta_key = os.environ.get("META_API_KEY")
    if meta_key:
        fns["meta"] = lambda summary: classifier.classify_with_meta(
            summary, api_key=meta_key, model=os.environ.get("META_MODEL", "muse-spark-1.3"),
            base_url=os.environ.get("META_BASE_URL", "https://api.meta.ai/v1"),
        )
    nim_key = _nim_key()
    if nim_key:
        fns["nim"] = lambda summary: classifier.classify_with_meta(
            summary, api_key=nim_key, model=NIM_MODEL, base_url=NIM_BASE_URL
        )
    if os.environ.get("ANTHROPIC_API_KEY"):
        key = os.environ["ANTHROPIC_API_KEY"]
        fns["anthropic"] = lambda summary: classifier.classify_with_anthropic(summary, api_key=key, model="claude-sonnet-4-6")
    return fns


def _judge_fns() -> Dict[str, Callable[[Any, str], Any]]:
    from agentreplay.testgen import assertions

    fns: Dict[str, Callable[[Any, str], Any]] = {}
    if os.environ.get("META_API_KEY"):
        fns["meta"] = lambda out, rubric: assertions._judge_with_meta(out, rubric, model="muse-spark-1.3")
    nim_key = _nim_key()
    if nim_key:
        fns["nim"] = lambda out, rubric: assertions._judge_with_meta(
            out, rubric, model=NIM_MODEL, api_key=nim_key, base_url=NIM_BASE_URL
        )
    if os.environ.get("ANTHROPIC_API_KEY"):
        fns["anthropic"] = lambda out, rubric: assertions._judge_with_anthropic(out, rubric, model="claude-sonnet-4-6")
    return fns


MODEL_NAMES = {"meta": "muse-spark-1.3", "nim": NIM_MODEL, "anthropic": "claude-sonnet-4-6"}


def _consistency(per_case_answers: List[List[Any]]) -> Optional[float]:
    """Mean over cases of the share of trials agreeing with that case's most common answer."""
    shares = [Counter(a).most_common(1)[0][1] / len(a) for a in per_case_answers if a]
    return round(sum(shares) / len(shares), 4) if shares else None


def run_benchmark(
    backends: Optional[List[str]] = None,
    trials: int = TRIALS,
    classifier_fns: Optional[Dict[str, Callable[[str], Any]]] = None,
    judge_fns: Optional[Dict[str, Callable[[Any, str], Any]]] = None,
    summarize: Optional[Callable[[Any, List[Any]], str]] = None,
) -> List[BackendResult]:
    if summarize is None:
        classifier = _ingest_imports()
        summarize = classifier.build_trace_summary
    c_fns = classifier_fns if classifier_fns is not None else _classifier_fns()
    j_fns = judge_fns if judge_fns is not None else _judge_fns()
    cases, jcases = classifier_cases(), judge_cases()
    results: List[BackendResult] = []

    for backend in backends or ["meta", "nim", "anthropic"]:
        result = BackendResult(backend, MODEL_NAMES.get(backend, backend))
        if backend not in c_fns and backend not in j_fns:
            result.skipped = "no API key configured"
            results.append(result)
            continue

        if backend in c_fns:
            correct = total = 0
            answers: List[List[str]] = []
            for case in cases:
                run = SimpleNamespace(id=f"bench-{case.id}", agent_version="bench", framework=None)
                summary = summarize(run, case.spans)
                given: List[str] = []
                for _ in range(trials):
                    result.calls += 1
                    try:
                        out = c_fns[backend](summary)
                    except Exception:
                        result.classifier_errors += 1
                        continue
                    given.append(out.failure_class)
                    total += 1
                    correct += out.failure_class == case.label
                    result.classifier_cost_usd += (out.usage or {}).get("cost_usd", 0.0)
                    if out.failure_class != case.label:
                        result.classifier_confusions.append({"case": case.id, "expected": case.label, "got": out.failure_class})
                answers.append(given)
            result.classifier_accuracy = round(correct / total, 4) if total else None
            result.classifier_consistency = _consistency(answers)

        if backend in j_fns:
            correct = total = 0
            answers_j: List[List[bool]] = []
            for case in jcases:
                given_j: List[bool] = []
                for _ in range(trials):
                    result.calls += 1
                    try:
                        verdict = j_fns[backend](case.output, JUDGE_RUBRIC)
                    except Exception:
                        result.judge_errors += 1
                        continue
                    given_j.append(bool(verdict.passes))
                    total += 1
                    correct += bool(verdict.passes) == case.passes
                answers_j.append(given_j)
            result.judge_accuracy = round(correct / total, 4) if total else None
            result.judge_consistency = _consistency(answers_j)
        results.append(result)
    return results


def render(results: List[BackendResult], trials: int = TRIALS) -> str:
    def pct(v: Optional[float]) -> str:
        return "-" if v is None else f"{v * 100:.0f}%"

    head = f"{'backend':10s} {'model':30s} {'MAST acc':9s} {'MAST cons':10s} {'judge acc':10s} {'judge cons':10s} {'errors':7s}"
    lines = [f"cases: {len(classifier_cases())} classifier, {len(judge_cases())} judge; trials per case: {trials}", head, "-" * len(head)]
    for r in results:
        if r.skipped:
            lines.append(f"{r.backend:10s} {r.model:30s} skipped: {r.skipped}")
            continue
        lines.append(
            f"{r.backend:10s} {r.model:30s} {pct(r.classifier_accuracy):9s} {pct(r.classifier_consistency):10s} "
            f"{pct(r.judge_accuracy):10s} {pct(r.judge_consistency):10s} {r.classifier_errors + r.judge_errors:<7d}"
        )
    return "\n".join(lines)
