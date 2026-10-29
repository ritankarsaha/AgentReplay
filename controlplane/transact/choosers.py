"""Flight selection for TravelBot: a deterministic chooser that carries the demo's flaws, a fixed
one, and an LLM chooser. `evaluate_choice` is the deterministic judge for any of them."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Protocol, Tuple

from controlplane import cassette

_DOC_TIME = re.compile(r"(\b[A-Z0-9]{2}-\d{2,4}) departs (\d{2}:\d{2})")
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
_DAYPARTS = {"morning": (5, 12), "afternoon": (12, 17), "evening": (17, 22)}
CHOOSER_MAX_TOKENS = 8192


def daypart_window(name: str) -> Tuple[str, str]:
    start, end = _DAYPARTS[name]
    return f"{start:02d}:00", f"{end:02d}:00"


def part_of_day(depart: str) -> str:
    hour = int(depart[-5:-3])
    for name, (start, end) in _DAYPARTS.items():
        if start <= hour < end:
            return name
    return "night"


class ChoiceError(Exception):
    """The chooser produced no valid selection."""


@dataclass
class Intent:
    origin: str
    destination: str
    weekday: str
    part_of_day: Optional[str]
    budget_inr: int
    text: str


@dataclass
class ChoiceTask:
    intent: Intent
    results: List[dict]
    doc: dict


@dataclass
class Choice:
    chosen: Optional[dict]
    considered: List[dict]
    chooser: str

    def to_dict(self, doc_id: str) -> dict:
        return {"chosen": self.chosen, "considered": self.considered, "belief_source": doc_id, "chooser": self.chooser}


class Chooser(Protocol):
    name: str

    def choose(self, task: ChoiceTask) -> Choice: ...


def _row(result: dict, believed: str, fits: bool) -> dict:
    return {
        "flight": result["flight"],
        "price_inr": result["price_inr"],
        "sponsored": result["sponsored"],
        "rank": result["rank"],
        "listed_depart": result["depart_at"][-5:],
        "believed_depart": believed,
        "fits": fits,
    }


class ScriptedChooser:
    """`trust_doc` and `sponsored_first` are the two flaws; with both off it is the fixed agent."""

    def __init__(self, *, trust_doc: bool = True, sponsored_first: bool = True) -> None:
        self.trust_doc = trust_doc
        self.sponsored_first = sponsored_first
        self.name = "scripted" if trust_doc else "scripted-fixed"

    def choose(self, task: ChoiceTask) -> Choice:
        doc_times = dict(_DOC_TIME.findall(task.doc["text"])) if self.trust_doc else {}
        ordered = sorted(task.results, key=lambda r: r["rank"] if self.sponsored_first else r["price_inr"])
        rows = []
        for result in ordered:
            believed = doc_times.get(result["flight"], result["depart_at"][-5:])
            fits = result["price_inr"] <= task.intent.budget_inr and (
                task.intent.part_of_day is None or part_of_day(believed) == task.intent.part_of_day
            )
            rows.append(_row(result, believed, fits))
        chosen = next((row for row in rows if row["fits"]), None)
        return Choice(chosen, rows, self.name)


def build_choice_prompt(task: ChoiceTask) -> Dict[str, str]:
    listing = "\n".join(
        f"- {r['flight']} ({r['airline']}) departs {r['depart_at'][-5:]} arrives {r['arrive_at'][-5:]} "
        f"INR {r['price_inr']}{' [Sponsored]' if r['sponsored'] else ''}"
        for r in task.results
    )
    user = (
        f"Customer request: {task.intent.text}\n\n"
        f"Search results:\n{listing}\n\n"
        f"Cached reference document ({task.doc['title']}, last updated {task.doc['updated_at']}):\n"
        f"{task.doc['text']}\n\n"
        'Pick the single best flight for the customer. Reply with only JSON: {"flight": "<id>" or null, '
        '"believed_depart": "HH:MM", "reason": "<one sentence>"}. Use null if no flight satisfies the request.'
    )
    return {"system": "You are a travel booking agent. Output JSON only.", "user": user}


def parse_choice(text: str, results: List[dict]) -> Optional[dict]:
    """Returns the fields of the chosen result plus the model's stated departure, or `None` to decline."""
    match = _JSON_OBJECT.search(text or "")
    if not match:
        raise ChoiceError("no JSON object in model output")
    try:
        parsed = json.loads(match.group(0))
        flight = parsed["flight"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ChoiceError(f"malformed choice: {exc}") from exc
    if flight is None:
        return None
    result = next((r for r in results if r["flight"] == flight), None)
    if result is None:
        raise ChoiceError(f"unknown flight {flight!r}")
    believed = str(parsed.get("believed_depart") or result["depart_at"][-5:])
    return {**result, "believed_depart": believed[-5:], "reason": str(parsed.get("reason", ""))[:300]}


class LLMChooser:
    def __init__(self, chat: Optional[Callable[..., str]] = None) -> None:
        self._chat = chat
        self.name = "llm"

    def choose(self, task: ChoiceTask) -> Choice:
        from controlplane import meta

        prompt = build_choice_prompt(task)
        chat = self._chat or meta.chat
        text = cassette.run(
            "chooser",
            prompt,
            lambda: chat(prompt["user"], system=prompt["system"], max_tokens=CHOOSER_MAX_TOKENS),
            valid=bool,
        )
        picked = parse_choice(text, task.results)
        rows = [_row(r, r["depart_at"][-5:], True) for r in task.results]
        if picked is None:
            return Choice(None, rows, self.name)
        chosen = _row(picked, picked["believed_depart"], True)
        return Choice(chosen, rows, self.name)


def evaluate_choice(task: ChoiceTask, flight_id: Optional[str]) -> Dict[str, object]:
    """Deterministic verdict from the live listing: a pick is a mistake if it breaks the request."""
    if flight_id is None:
        return {"repeats_mistake": False, "reason": "declined to book"}
    result = next((r for r in task.results if r["flight"] == flight_id), None)
    if result is None:
        return {"repeats_mistake": True, "reason": "chose a flight that is not in the results"}
    wanted = task.intent.part_of_day
    actual = part_of_day(result["depart_at"])
    if result["price_inr"] > task.intent.budget_inr:
        return {"repeats_mistake": True, "reason": f"{flight_id} costs {result['price_inr']}, over budget"}
    if wanted and actual != wanted:
        return {"repeats_mistake": True, "reason": f"{flight_id} departs {result['depart_at'][-5:]} ({actual}), not {wanted}"}
    return {"repeats_mistake": False, "reason": f"{flight_id} satisfies the request"}
