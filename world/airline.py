from __future__ import annotations

import hashlib
import html
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import data
from .seller import Quote, Seller, SellerReply


class AirlineError(Exception):
    pass


@dataclass
class Booking:
    pnr: str
    flight_id: str
    depart_at: str
    price_inr: float
    terms: List[str]
    passenger: str

    def to_dict(self) -> dict:
        return {
            "pnr": self.pnr,
            "flight": self.flight_id,
            "depart_at": self.depart_at,
            "price_inr": self.price_inr,
            "terms": self.terms,
            "passenger": self.passenger,
            "simulated": True,
        }


@dataclass
class AirlineSite:
    """Deterministic simulated airline; no network, no real inventory."""

    seller: Seller = field(default_factory=Seller)
    bookings: List[Booking] = field(default_factory=list)

    @property
    def schedule_version(self) -> int:
        return data.SCHEDULE_VERSION

    def search(self, origin: str, destination: str, date: str) -> dict:
        if (origin, destination, date) != (data.ORIGIN, data.DESTINATION, data.TRAVEL_DATE):
            return {"results": [], "schedule_version": self.schedule_version, "simulated": True}
        ordered = sorted(data.FLIGHTS, key=lambda f: (not f.sponsored, f.depart))
        results = [
            {
                "flight": f.id,
                "airline": f.airline,
                "depart_at": f.depart_at,
                "arrive_at": f.arrive_at,
                "price_inr": f.list_price_inr,
                "sponsored": f.sponsored,
                "rank": rank,
            }
            for rank, f in enumerate(ordered, start=1)
        ]
        return {"results": results, "schedule_version": self.schedule_version, "simulated": True}

    def fare_detail(self, flight_id: str) -> dict:
        flight = self._flight(flight_id)
        return {
            "flight": flight.id,
            "airline": flight.airline,
            "depart_at": flight.depart_at,
            "arrive_at": flight.arrive_at,
            "price_inr": flight.list_price_inr,
            "sponsored": flight.sponsored,
            "refundable": True,
            "simulated": True,
        }

    def read_doc(self, doc_id: str) -> dict:
        if doc_id != data.FARE_RULES_DOC_ID:
            raise AirlineError(f"unknown document '{doc_id}'")
        return {
            "doc_id": data.FARE_RULES_DOC_ID,
            "title": "BLR-CCU fare rules",
            "text": data.FARE_RULES_TEXT,
            "updated_at": data.FARE_RULES_UPDATED_AT,
            "source_version": data.FARE_RULES_SOURCE_VERSION,
        }

    def open_negotiation(self, flight_id: str) -> dict:
        return self.seller.open(self._flight(flight_id)).to_dict()

    def negotiate(self, session_id: str, levers: List[str], target_price_inr: int) -> SellerReply:
        return self.seller.respond(session_id, levers, target_price_inr)

    def book(self, flight_id: str, price_inr: float, passenger: str = "traveller", quote_id: Optional[str] = None) -> Booking:
        flight = self._flight(flight_id)
        terms: List[str] = []
        if quote_id is not None:
            quote = self.seller.quote(quote_id)
            if quote is None or quote.flight_id != flight.id:
                raise AirlineError("quote does not match this flight")
            if price_inr != quote.price_inr:
                raise AirlineError(f"price {price_inr} does not match quote {quote.price_inr}")
            terms = list(quote.levers)
        elif price_inr != flight.list_price_inr:
            raise AirlineError(f"price {price_inr} does not match list price {flight.list_price_inr}")
        seed = f"{flight.id}:{len(self.bookings)}:{price_inr}"
        booking = Booking(
            pnr="SIM" + hashlib.sha256(seed.encode()).hexdigest()[:6].upper(),
            flight_id=flight.id,
            depart_at=flight.depart_at,
            price_inr=price_inr,
            terms=terms,
            passenger=passenger,
        )
        self.bookings.append(booking)
        return booking

    @classmethod
    def confirmation_html(cls, booking: dict) -> str:
        """Confirmation page for a `Booking.to_dict()` payload (works on recorded bookings too)."""
        flight = cls._flight(booking["flight"])
        rows = [
            ("PNR", booking["pnr"]),
            ("Flight", f"{flight.airline} {flight.id}"),
            ("Route", f"{data.ORIGIN} → {data.DESTINATION}"),
            ("Departure", booking["depart_at"].replace("T", " ")),
            ("Fare paid", f"₹{booking['price_inr']:,.0f}"),
            ("Passenger", booking["passenger"]),
        ]
        cells = "".join(
            f"<tr><th>{html.escape(k)}</th><td id=\"{html.escape(k.lower().replace(' ', '-'))}\">{html.escape(v)}</td></tr>"
            for k, v in rows
        )
        return (
            "<!doctype html><html><head><meta charset=\"utf-8\"><title>Booking confirmed</title><style>"
            "body{font-family:Helvetica,Arial,sans-serif;background:#f4f6f8;margin:0;padding:32px}"
            ".card{max-width:560px;background:#fff;border:1px solid #d7dde3;border-radius:8px;padding:24px}"
            "h1{font-size:22px;margin:0 0 4px}.sim{color:#8a5a00;font-size:12px;margin-bottom:16px}"
            "th{text-align:left;color:#5a6670;padding:8px 24px 8px 0;font-weight:600}td{padding:8px 0;font-size:18px}"
            "</style></head><body><div class=\"card\"><h1>Booking confirmed</h1>"
            "<div class=\"sim\">Simulated airline sandbox. No real booking or payment.</div>"
            f"<table>{cells}</table></div></body></html>"
        )

    @staticmethod
    def _flight(flight_id: str) -> data.Flight:
        flight = data.FLIGHTS_BY_ID.get(flight_id)
        if flight is None:
            raise AirlineError(f"unknown flight '{flight_id}'")
        return flight
