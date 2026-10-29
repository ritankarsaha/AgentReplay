"""Phase 2 checkpoint: SMS in, negotiation, wrong (evening) purchase, every step a span, replayable.

    python -m controlplane.scripts.phase2_check             # Muse Spark negotiates (needs META_API_KEY)
    python -m controlplane.scripts.phase2_check --scripted  # offline, deterministic buyer
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections import Counter

import agentreplay
from agentreplay import _state
from agentreplay.collector import get_collector
from agentreplay.replay import replay_mode
from controlplane.blobs import BlobStore
from controlplane.transact.negotiator import MetaBuyer, ScriptedBuyer
from controlplane.transact.travelbot import TravelBot

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

SMS = "Book BLR→CCU Friday morning, under ₹6000."


def _check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'ok' if ok else 'FAIL'}] {label}{': ' + detail if detail else ''}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scripted", action="store_true", help="use the deterministic buyer instead of Muse Spark")
    args = parser.parse_args()

    seen = []
    original_add = type(get_collector()).add

    def add(self, span):
        seen.append(span)
        original_add(self, span)

    type(get_collector()).add = add
    blobs = BlobStore(tempfile.mkdtemp(prefix="phase2_blobs_"))
    buyer = ScriptedBuyer() if args.scripted else MetaBuyer()
    agentreplay.init(api_key="phase2-check", endpoint="http://127.0.0.1:9", flush_interval=3600, agent_version="phase2")
    result = TravelBot(buyer=buyer, blobs=blobs).run(SMS)
    agentreplay.set_tool_guard(None)

    counts = Counter(s.type for s in seen)
    print("spans:", dict(counts))
    for span in (s for s in seen if s.type == "negotiation"):
        out = span.output
        print(
            f"  round {span.input['round']} [{span.input['buyer']}] offered {span.input['offered_levers']} "
            f"-> {out['status']} ₹{out['price_inr']:,}  ({out['message']})"
        )

    ok = [
        _check("inbound SMS is the first span", seen[0].type == "message" and seen[0].name == "sms.inbound"),
        _check("sponsored flag recorded on search results", any(r["sponsored"] for s in seen if s.name == "search_flights" for r in s.output["results"])),
        _check("stale doc read recorded", any(s.type == "data_read" and s.output["source_version"] < s.output["live_schedule_version"] for s in seen)),
        _check("negotiated below list price", result.price_inr < 5900, f"₹5,900 -> ₹{result.price_inr:,}"),
        _check("booked the wrong (evening) flight", result.mismatch and result.booking["depart_at"].endswith("19:30"), f"{result.flight} departing {result.booking['depart_at'][-5:]}"),
        _check("booking screenshot captured", result.screenshot["image"] is not None, str(result.screenshot["image"] and result.screenshot["image"]["bytes"]) + " bytes"),
    ]

    trace = [s.to_dict() for s in seen]
    _state.reset()
    replay_bot = TravelBot(buyer=buyer, blobs=blobs)
    with replay_mode(trace) as session:
        replayed = replay_bot.run(SMS)
    ok.append(_check("strict replay reproduces the booking with zero live calls", replayed.booking == result.booking and replay_bot.site.bookings == [] and session.remaining_count() == 0))

    print("PASS" if all(ok) else "FAIL")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
