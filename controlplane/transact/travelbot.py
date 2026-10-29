"""TravelBot: SMS in, search, negotiate, book. Reproduces the demo's wrong purchase on purpose.

The agent is scripted. Muse Spark is used only as the negotiating buyer. Three flaws combine
into the failure the incident pipeline later explains:

- sponsored influence: the sponsored listing is ranked first and gets considered first,
- stale data: the cached fare-rules doc (schedule v5) says 6E-871 departs 07:30, and the
  agent believes it over the live listing (19:30),
- intent drift: it concedes a Friday 06:00-22:00 flex window, looser than "morning".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

import agentreplay
from agentreplay.guard import emit_span
from controlplane.blobs import BlobStore
from controlplane.govern import KeyPair, ScopeManifest, ToolBinding, sign_manifest
from controlplane.transact.negotiator import Buyer, ScriptedBuyer, run_negotiation
from controlplane.world.capture import capture_png
from controlplane.world.sms import SmsGateway
from world import AirlineSite, data

ALLOWED_TOOLS = ["search_flights", "read_doc", "open_negotiation", "negotiate", "book_flight"]
BINDINGS: Dict[str, ToolBinding] = {
    "book_flight": ToolBinding(amount_arg="price_inr", region_arg="country", counts_as_booking=True),
    "search_flights": ToolBinding(region_arg="country"),
}
ARG_NAMES: Dict[str, List[str]] = {
    "book_flight": ["flight", "price_inr", "country", "quote_id"],
    "search_flights": ["origin", "destination", "date", "country"],
}
DEFAULT_CONSTRAINTS = {"max_spend_inr": 6000, "max_bookings_per_task": 1, "geography": "domestic"}

_DAYPARTS = {"morning": (5, 12), "afternoon": (12, 17), "evening": (17, 22)}
_SMS = re.compile(
    r"book\s+(?P<origin>[A-Za-z]{3})\s*(?:→|->|to)\s*(?P<dest>[A-Za-z]{3})\s+(?P<day>\w+day)"
    r"(?:\s+(?P<part>morning|afternoon|evening))?.*?(?:under|below|<)\s*₹?\s*(?P<budget>[\d,]+)",
    re.IGNORECASE | re.DOTALL,
)
_DOC_TIME = re.compile(r"(\b[A-Z0-9]{2}-\d{2,4}) departs (\d{2}:\d{2})")


def travelbot_manifest(keypair: KeyPair, **overrides) -> ScopeManifest:
    return sign_manifest(
        keypair,
        allowed_tools=ALLOWED_TOOLS,
        constraints={**DEFAULT_CONSTRAINTS, **overrides},
    )


@dataclass
class Intent:
    origin: str
    destination: str
    weekday: str
    part_of_day: Optional[str]
    budget_inr: int
    text: str


def parse_sms(body: str) -> Intent:
    match = _SMS.search(body)
    if not match:
        raise ValueError(f"could not understand request: {body!r}")
    weekday = match.group("day").capitalize()
    if weekday != "Friday":
        raise ValueError(f"the sandbox only has Friday flights, got {weekday}")
    return Intent(
        origin=match.group("origin").upper(),
        destination=match.group("dest").upper(),
        weekday=weekday,
        part_of_day=(match.group("part") or "").lower() or None,
        budget_inr=int(match.group("budget").replace(",", "")),
        text=body.strip(),
    )


def part_of_day(depart: str) -> str:
    hour = int(depart[-5:-3])
    for name, (start, end) in _DAYPARTS.items():
        if start <= hour < end:
            return name
    return "night"


@dataclass
class TravelBotResult:
    intent: Intent
    flight: str
    booking: dict
    price_inr: int
    mismatch: bool
    screenshot: dict


class TravelBot:
    def __init__(
        self,
        site: Optional[AirlineSite] = None,
        buyer: Optional[Buyer] = None,
        *,
        sms: Optional[SmsGateway] = None,
        blobs: Optional[BlobStore] = None,
        user_number: str = "+910000000000",
    ) -> None:
        self.site = site or AirlineSite()
        self.buyer = buyer or ScriptedBuyer()
        self.sms = sms or SmsGateway()
        self.blobs = blobs or BlobStore()
        self.user_number = user_number
        self._define_tools()

    def _define_tools(self) -> None:
        site = self.site

        @agentreplay.tool(name="search_flights")
        def search_flights(origin, destination, date, country="IN"):
            return site.search(origin, destination, date)

        @agentreplay.tool(name="read_doc")
        def read_doc(doc_id):
            return site.read_doc(doc_id)

        @agentreplay.tool(name="open_negotiation")
        def open_negotiation(flight):
            return site.open_negotiation(flight)

        @agentreplay.tool(name="negotiate")
        def negotiate(session_id, levers, target_price_inr):
            return site.negotiate(session_id, list(levers), int(target_price_inr)).to_dict()

        @agentreplay.tool(name="book_flight")
        def book_flight(flight, price_inr, country="IN", quote_id=None):
            return site.book(flight, price_inr, quote_id=quote_id).to_dict()

        self.search_flights, self.read_doc = search_flights, read_doc
        self.open_negotiation, self.negotiate, self.book_flight = open_negotiation, negotiate, book_flight

    def run(self, sms_body: str, *, attempt_fix: bool = False) -> TravelBotResult:
        self.sms.receive(self.user_number, sms_body)
        intent = parse_sms(sms_body)

        search = self.search_flights(intent.origin, intent.destination, data.TRAVEL_DATE, data.COUNTRY)
        doc = self.read_doc(data.FARE_RULES_DOC_ID)
        emit_span(
            "data_read",
            "read_doc",
            {"doc_id": doc["doc_id"]},
            {
                "doc_id": doc["doc_id"],
                "doc_updated_at": doc["updated_at"],
                "source_version": doc["source_version"],
                "live_schedule_version": search["schedule_version"],
            },
        )

        choice = self._choose(intent, search["results"], doc)
        session = self.open_negotiation(choice["flight"])
        goal = int(round(session["list_price_inr"] * 0.88, -2))
        reply = run_negotiation(
            lambda sid, levers, target: self.negotiate(sid, levers, target),
            session,
            self.buyer,
            intent_text=intent.text,
            goal_price_inr=goal,
        )

        booking = self.book_flight(choice["flight"], reply["price_inr"], data.COUNTRY, reply["quote_id"])
        screenshot = self._capture(booking)
        mismatch = bool(intent.part_of_day) and part_of_day(booking["depart_at"]) != intent.part_of_day
        self.sms.send(
            self.user_number,
            f"Booked {booking['flight']} departing {booking['depart_at'][-5:]} for "
            f"₹{booking['price_inr']:,.0f}. PNR {booking['pnr']}.",
        )

        if mismatch and attempt_fix:
            self._attempt_fix(intent, search["results"])

        return TravelBotResult(intent, choice["flight"], booking, int(booking["price_inr"]), mismatch, screenshot)

    def _choose(self, intent: Intent, results: List[dict], doc: dict) -> dict:
        believed_times = dict(_DOC_TIME.findall(doc["text"]))
        considered = []
        chosen = None
        for result in sorted(results, key=lambda r: r["rank"]):
            listed = result["depart_at"][-5:]
            believed = believed_times.get(result["flight"], listed)
            fits = (
                result["price_inr"] <= intent.budget_inr
                and (intent.part_of_day is None or part_of_day(believed) == intent.part_of_day)
            )
            considered.append(
                {
                    "flight": result["flight"],
                    "price_inr": result["price_inr"],
                    "sponsored": result["sponsored"],
                    "rank": result["rank"],
                    "listed_depart": listed,
                    "believed_depart": believed,
                    "fits": fits,
                }
            )
            if fits and chosen is None:
                chosen = considered[-1]
        if chosen is None:
            raise ValueError("no flight fits the request")
        emit_span(
            "decision",
            "choose_flight",
            {"intent": intent.text, "doc_id": doc["doc_id"]},
            {"chosen": chosen, "considered": considered, "belief_source": doc["doc_id"]},
        )
        return chosen

    def _capture(self, booking: dict) -> dict:
        page = AirlineSite.confirmation_html(booking)
        html_ref = self.blobs.put(page.encode("utf-8"), "text/html")
        png = capture_png(page)
        image_ref = self.blobs.put(png, "image/png") if png else None
        record = {"page": "booking_confirmation", "pnr": booking["pnr"], "html": html_ref, "image": image_ref}
        emit_span("screenshot", "booking_confirmation", {"pnr": booking["pnr"]}, {**record, "captured": image_ref is not None})
        return record

    def _attempt_fix(self, intent: Intent, results: List[dict]) -> None:
        for result in sorted(results, key=lambda r: r["rank"]):
            if part_of_day(result["depart_at"]) == intent.part_of_day:
                self.book_flight(result["flight"], result["price_inr"], data.COUNTRY, None)
                return
