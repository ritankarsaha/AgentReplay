"""Model scoreboard: replay one recorded decision against several models and report who would
repeat the mistake. Verdicts are deterministic (`evaluate_choice`); the models only pick."""

from __future__ import annotations

import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from controlplane import cassette, meta
from controlplane.ledger import LEDGER
from controlplane.pricing import cost_usd
from controlplane.learn.causation import TraceFacts
from controlplane.transact.choosers import (
    CHOOSER_MAX_TOKENS,
    ChoiceError,
    ChoiceTask,
    build_choice_prompt,
    evaluate_choice,
    parse_choice,
)

TASK_CLASS = "flight_selection"
ATTEMPTS = 2
REQUEST_TIMEOUT_S = 180.0

REPEATS = "repeats_mistake"
CORRECT = "correct"
ERROR = "error"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    provider: str
    base_url: str
    api_key_envs: Tuple[str, ...]

    def api_key(self) -> Optional[str]:
        return next((os.environ[e] for e in self.api_key_envs if os.environ.get(e)), None)


DEFAULT_MODELS: Tuple[ModelSpec, ...] = (
    ModelSpec("muse-spark-1.3", "meta", meta.DEFAULT_BASE_URL, ("META_API_KEY",)),
    ModelSpec("muse-spark-1.2", "meta", meta.DEFAULT_BASE_URL, ("META_API_KEY",)),
    ModelSpec("muse-spark-1.1", "meta", meta.DEFAULT_BASE_URL, ("META_API_KEY",)),
)


def task_from_facts(facts: TraceFacts) -> ChoiceTask:
    if not (facts.intent and facts.search and facts.reference_doc):
        raise ValueError("trace lacks the request, search results or reference document")
    return ChoiceTask(facts.intent, facts.search["output"]["results"], facts.reference_doc)


AskFn = Callable[[ModelSpec, Dict[str, str]], Tuple[str, Optional[dict]]]


def ask_model(spec: ModelSpec, prompt: Dict[str, str]) -> Tuple[str, Optional[dict]]:
    import openai

    key = spec.api_key()
    if not key:
        raise RuntimeError(f"no API key configured for {spec.provider} ({spec.name})")
    client = openai.OpenAI(api_key=key, base_url=spec.base_url, timeout=REQUEST_TIMEOUT_S, max_retries=0)
    response = client.chat.completions.create(
        model=spec.name,
        max_tokens=CHOOSER_MAX_TOKENS,
        messages=[{"role": "system", "content": prompt["system"]}, {"role": "user", "content": prompt["user"]}],
    )
    raw = response.usage
    usage = (
        {"prompt_tokens": getattr(raw, "prompt_tokens", 0), "completion_tokens": getattr(raw, "completion_tokens", 0)}
        if raw
        else None
    )
    LEDGER.record(spec.name, usage)
    return response.choices[0].message.content or "", usage


def _one_trial(spec: ModelSpec, task: ChoiceTask, prompt: Dict[str, str], trial: int, ask: AskFn) -> Dict[str, Any]:
    base = {"model": spec.name, "provider": spec.provider, "trial": trial, "task_class": TASK_CLASS}
    spent: Optional[float] = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            text, usage = cassette.run(
                f"score.{spec.name}.{trial}.{attempt}",
                {"model": spec.name, "prompt": prompt},
                lambda: ask(spec, prompt),
                valid=lambda reply: bool(reply[0]),
            )
        except Exception as exc:
            return {**base, "verdict": ERROR, "error": f"{type(exc).__name__}: {exc}"[:300], "cost_usd": spent}
        call_cost = cost_usd(spec.name, usage)
        spent = (spent or 0.0) + call_cost if call_cost is not None else spent
        try:
            picked = parse_choice(text, task.results)
            break
        except ChoiceError as exc:
            if attempt == ATTEMPTS:
                return {**base, "verdict": ERROR, "error": f"unusable output after {attempt} attempts: {exc}", "raw": text[:300], "cost_usd": spent}
    flight = picked["flight"] if picked else None
    judgment = evaluate_choice(task, flight)
    return {
        **base,
        "verdict": REPEATS if judgment["repeats_mistake"] else CORRECT,
        "flight": flight,
        "believed_depart": picked["believed_depart"] if picked else None,
        "reason": judgment["reason"],
        "model_reason": picked["reason"] if picked else "",
        "usage": usage,
        "attempts": attempt,
        "cost_usd": spent,
    }


def fan_out(
    task: ChoiceTask,
    *,
    models: Tuple[ModelSpec, ...] = DEFAULT_MODELS,
    trials: int = 3,
    ask: AskFn = ask_model,
    workers: int = 4,
) -> List[Dict[str, Any]]:
    prompt = build_choice_prompt(task)
    jobs = [(spec, t) for spec in models for t in range(trials)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda job: _one_trial(job[0], task, prompt, job[1], ask), jobs))


def to_model_runs(rows: List[Dict[str, Any]], *, source_run_id: str, span_id: str) -> List[dict]:
    return [
        {
            "source_run_id": source_run_id,
            "span_id": span_id,
            "model": r["model"],
            "output": {k: v for k, v in r.items() if k not in ("model",)},
            "verdict": r["verdict"],
            "cost_usd": r.get("cost_usd"),
        }
        for r in rows
    ]


def aggregate(model_runs: List[dict]) -> List[Dict[str, Any]]:
    """Per (task_class, model): trials, repeat count, correct rate. Errors are counted, never hidden."""
    buckets: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for row in model_runs:
        task_class = (row.get("output") or {}).get("task_class", TASK_CLASS)
        buckets[(task_class, row["model"])].append(row)
    table = []
    for (task_class, model), rows in sorted(buckets.items()):
        verdicts = [r["verdict"] for r in rows]
        scored = [v for v in verdicts if v != ERROR]
        costs = [r["cost_usd"] for r in rows if r.get("cost_usd") is not None]
        table.append(
            {
                "task_class": task_class,
                "model": model,
                "trials": len(rows),
                "repeats_mistake": verdicts.count(REPEATS),
                "correct": verdicts.count(CORRECT),
                "errors": verdicts.count(ERROR),
                "correct_rate": round(verdicts.count(CORRECT) / len(scored), 4) if scored else None,
                "repeats_the_mistake": (verdicts.count(REPEATS) > 0) if scored else None,
                "cost_usd": round(sum(costs), 6) if costs else None,
            }
        )
    return table


def render_table(table: List[Dict[str, Any]]) -> str:
    header = f"{'model':32s} {'repeats mistake?':17s} {'correct':8s} {'errors':6s} {'cost':8s}"
    lines = [header, "-" * len(header)]
    for row in table:
        flag = {True: "YES", False: "no", None: "n/a"}[row["repeats_the_mistake"]]
        cost = f"${row['cost_usd']:.4f}" if row["cost_usd"] is not None else "-"
        lines.append(
            f"{row['model']:32s} {flag:17s} {row['correct']}/{row['trials']:<6} {row['errors']:<6d} {cost:8s}"
        )
    return "\n".join(lines)
