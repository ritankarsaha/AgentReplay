"""Narrated walkthrough: deterministic beats from the trace, one caption per beat.

Beat selection and every fact are computed from spans. Muse Spark only words the captions, and a
caption containing a number that is not in its beat's facts is replaced by the template caption.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from controlplane import meta
from controlplane.learn.causation import TraceFacts, ordered

Captioner = Callable[[List[Dict[str, Any]]], List[str]]
CAPTION_MAX_TOKENS = 4096
_NUMBER = re.compile(r"\d[\d,.:]*\d|\d")


def _norm(token: str) -> str:
    return token.replace(",", "").strip(".:")


def _numbers(text: str) -> set:
    return {_norm(t) for t in _NUMBER.findall(text)}


def _first(spans: List[dict], **match: str) -> Optional[dict]:
    return next((s for s in ordered(spans) if all(s.get(k) == v for k, v in match.items())), None)


def select_beats(spans: List[dict], facts: TraceFacts) -> List[Dict[str, Any]]:
    beats: List[Dict[str, Any]] = []

    def add(kind: str, title: str, span: dict, data: Dict[str, Any], caption: str, **extra: Any) -> None:
        beats.append({"kind": kind, "title": title, "span_id": span["id"], "facts": data, "caption": caption, **extra})

    if facts.message:
        body = facts.message["output"]["body"]
        add("intent", "The request", facts.message, {"request": body}, f"The user texts the agent: \"{body}\"")

    if facts.search:
        results = facts.search["output"]["results"]
        sponsored = next((r for r in results if r["sponsored"]), None)
        if sponsored:
            data = {
                "flight": sponsored["flight"],
                "rank": sponsored["rank"],
                "price_inr": sponsored["price_inr"],
                "departs": sponsored["depart_at"][-5:],
            }
            add(
                "sponsored", "A sponsored listing ranks first", facts.search, data,
                f"Search returns {len(results)} flights. {data['flight']} is a sponsored listing ranked "
                f"#{data['rank']} at INR {data['price_inr']:,}, departing {data['departs']}.",
            )

    if facts.data_read:
        out = facts.data_read["output"]
        data = {k: out[k] for k in ("doc_id", "doc_updated_at", "source_version", "live_schedule_version")}
        add(
            "stale_data", "The agent reads an out-of-date document", facts.data_read, data,
            f"It reads {data['doc_id']}, last updated {data['doc_updated_at']} on schedule "
            f"v{data['source_version']}. The live schedule is v{data['live_schedule_version']}.",
        )

    if facts.decision:
        chosen = (facts.decision["output"] or {}).get("chosen")
        if chosen:
            data = {k: chosen[k] for k in ("flight", "sponsored", "listed_depart", "believed_depart")}
            add(
                "decision", "It picks a flight", facts.decision, data,
                f"It chooses {data['flight']}, believing it departs {data['believed_depart']}. "
                f"The live listing says {data['listed_depart']}.",
            )

    if facts.negotiations:
        last = facts.negotiations[-1]["output"]
        data = {
            "rounds": len(facts.negotiations),
            "list_price_inr": last["list_price_inr"],
            "final_price_inr": last["price_inr"],
            "conceded": last["accepted_levers"],
        }
        flex = " It agrees to a flex window, which allows any departure that day." if "flex_window" in data["conceded"] else ""
        add(
            "negotiation", "It negotiates the price (simulated seller)", facts.negotiations[-1], data,
            f"After {data['rounds']} rounds against a simulated seller the price drops from INR "
            f"{data['list_price_inr']:,} to INR {data['final_price_inr']:,}.{flex}",
        )

    if facts.purchase:
        out = facts.purchase["output"]
        shot = ((facts.screenshot or {}).get("output") or {}).get("image") or {}
        data = {"flight": out["flight"], "departs": out["depart_at"][-5:], "price_inr": out["price_inr"], "booking_ref": out["pnr"]}
        wrong = f" The user asked for {facts.intent.part_of_day}." if facts.mismatch and facts.intent else ""
        add(
            "purchase", "It books the wrong flight" if facts.mismatch else "It books the flight", facts.purchase, data,
            f"It books {data['flight']} departing {data['departs']} for INR {data['price_inr']:,.0f} "
            f"(booking {data['booking_ref']}).{wrong}",
            screenshot_sha256=shot.get("sha256"),
            screenshot_span_id=(facts.screenshot or {}).get("id"),
        )

    violation = _first(spans, type="scope_violation")
    if violation:
        out = violation.get("output") or {}
        data = {"tool": violation["name"], "rule": out.get("rule"), "reason": out.get("reason")}
        add(
            "halt", "The scope guard stops it", violation, data,
            f"It then tries to fix the mistake by calling {data['tool']} again. The signed scope blocks it "
            f"({data['reason']}) and the run is halted.",
        )
    return beats


def _validated(caption: Any, beat: Dict[str, Any]) -> bool:
    if not isinstance(caption, str) or not caption.strip():
        return False
    return _numbers(caption) <= _numbers(json.dumps(beat["facts"], default=str) + beat["title"])


def meta_captioner(chat: Optional[Callable[..., str]] = None) -> Captioner:
    def caption(beats: List[Dict[str, Any]]) -> List[str]:
        brief = [{"index": i, "title": b["title"], "facts": b["facts"]} for i, b in enumerate(beats)]
        prompt = (
            "Write one caption of at most two plain sentences for each step of an AI agent incident. "
            "Use only the facts given for that step; do not add numbers or details. "
            'Reply with only JSON: {"captions": ["...", ...]} with exactly one caption per step, in order.\n\n'
            + json.dumps(brief, ensure_ascii=False, indent=2)
        )
        text = (chat or meta.chat)(
            prompt, system="You narrate incidents for a non-technical viewer.", max_tokens=CAPTION_MAX_TOKENS
        )
        match = re.search(r"\{.*\}", text or "", re.DOTALL)
        if not match:
            raise ValueError("no JSON in model output")
        captions = json.loads(match.group(0))["captions"]
        if not isinstance(captions, list):
            raise ValueError("captions is not a list")
        return captions

    return caption


def build_walkthrough(
    spans: List[dict], facts: TraceFacts, *, captioner: Optional[Captioner] = None, model: Optional[str] = None
) -> Dict[str, Any]:
    beats = select_beats(spans, facts)
    for beat in beats:
        beat["caption_source"] = "template"
    note = None
    if captioner and beats:
        try:
            captions = captioner(beats)
            if len(captions) != len(beats):
                raise ValueError(f"expected {len(beats)} captions, got {len(captions)}")
            for beat, caption in zip(beats, captions):
                if _validated(caption, beat):
                    beat["caption"], beat["caption_source"] = caption.strip(), model or meta.meta_model()
        except Exception as exc:
            note = f"model captions unavailable: {type(exc).__name__}: {exc}"[:200]
    return {
        "beats": beats,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "captions_by_model": sum(1 for b in beats if b["caption_source"] != "template"),
        "note": note,
    }
