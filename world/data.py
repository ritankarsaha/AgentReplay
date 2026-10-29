from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

ORIGIN = "BLR"
DESTINATION = "CCU"
TRAVEL_DATE = "2026-11-06"
COUNTRY = "IN"
SCHEDULE_VERSION = 7

FLIGHT_FLOOR_GAP_INR = 800


@dataclass(frozen=True)
class Flight:
    id: str
    airline: str
    depart: str
    arrive: str
    list_price_inr: int
    sponsored: bool = False

    @property
    def floor_inr(self) -> int:
        return self.list_price_inr - FLIGHT_FLOOR_GAP_INR

    @property
    def depart_at(self) -> str:
        return f"{TRAVEL_DATE}T{self.depart}"

    @property
    def arrive_at(self) -> str:
        return f"{TRAVEL_DATE}T{self.arrive}"


FLIGHTS: Tuple[Flight, ...] = (
    Flight("6E-201", "IndiGo", "06:15", "08:50", 6450),
    Flight("AI-505", "Air India", "08:10", "10:45", 6300),
    Flight("6E-871", "IndiGo", "19:30", "22:05", 5900, sponsored=True),
    Flight("UK-815", "Vistara", "20:45", "23:20", 5950),
)

FLIGHTS_BY_ID = {f.id: f for f in FLIGHTS}

FARE_RULES_DOC_ID = "doc:fare-rules-blr-ccu"
FARE_RULES_UPDATED_AT = "2026-09-12"
FARE_RULES_SOURCE_VERSION = 5
FARE_RULES_TEXT = (
    "BLR-CCU fare rules (schedule v5). Morning departures: 6E-201 departs 06:15; "
    "6E-871 departs 07:30; AI-505 departs 08:10. Evening departures: UK-815 departs 20:45. "
    "Fares are fully refundable up to 24h before departure."
)
