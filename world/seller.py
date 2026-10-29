from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .data import Flight

MAX_ROUNDS = 4
SETTLEMENT_MARGIN_INR = 100

LEVERS: Dict[str, int] = {
    "flex_window": 350,
    "non_refundable": 250,
    "no_checked_bag": 200,
    "partner_wallet": 150,
    "fee_waiver": 100,
}


@dataclass(frozen=True)
class Quote:
    id: str
    flight_id: str
    price_inr: int
    levers: List[str]


@dataclass
class Session:
    id: str
    flight_id: str
    list_price_inr: int
    floor_inr: int
    round: int = 0
    accepted: List[str] = field(default_factory=list)
    closed: bool = False

    @property
    def settlement_floor_inr(self) -> int:
        return self.floor_inr + SETTLEMENT_MARGIN_INR

    def current_price(self) -> int:
        return self.list_price_inr - sum(LEVERS[lever] for lever in self.accepted)

    def to_dict(self) -> dict:
        return {
            "session_id": self.id,
            "flight": self.flight_id,
            "list_price_inr": self.list_price_inr,
            "max_rounds": MAX_ROUNDS,
            "levers": dict(LEVERS),
            "simulated": True,
        }


@dataclass
class SellerReply:
    session_id: str
    round: int
    status: str
    price_inr: int
    list_price_inr: int
    accepted_levers: List[str]
    new_concessions: List[dict]
    rejected_levers: Dict[str, str]
    quote_id: Optional[str] = None
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "round": self.round,
            "status": self.status,
            "price_inr": self.price_inr,
            "list_price_inr": self.list_price_inr,
            "accepted_levers": self.accepted_levers,
            "new_concessions": self.new_concessions,
            "rejected_levers": self.rejected_levers,
            "quote_id": self.quote_id,
            "message": self.message,
            "simulated": True,
        }


Phraser = Callable[[SellerReply], str]


class Seller:
    """Rules-engine consolidator. Every number is computed here; `phraser` only words the reply."""

    def __init__(self, phraser: Optional[Phraser] = None) -> None:
        self._sessions: Dict[str, Session] = {}
        self._quotes: Dict[str, Quote] = {}
        self._phraser = phraser

    def open(self, flight: Flight) -> Session:
        session = Session(
            id=f"neg-{len(self._sessions) + 1}",
            flight_id=flight.id,
            list_price_inr=flight.list_price_inr,
            floor_inr=flight.floor_inr,
        )
        self._sessions[session.id] = session
        return session

    def quote(self, quote_id: str) -> Optional[Quote]:
        return self._quotes.get(quote_id)

    def respond(self, session_id: str, levers: List[str], target_price_inr: int) -> SellerReply:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"unknown negotiation session '{session_id}'")
        if session.closed:
            return self._reply(session, "closed", {}, [], message_override="negotiation already closed")

        session.round += 1
        rejected: Dict[str, str] = {}
        granted: List[dict] = []
        for lever in levers:
            value = LEVERS.get(lever)
            if value is None:
                rejected[lever] = "unknown_lever"
            elif lever in session.accepted:
                continue
            elif session.current_price() - value < session.settlement_floor_inr:
                rejected[lever] = "below_floor"
            else:
                session.accepted.append(lever)
                granted.append({"lever": lever, "amount_inr": value})

        price = session.current_price()
        if target_price_inr >= price:
            status, final_price = "accepted", int(target_price_inr)
        elif session.round >= MAX_ROUNDS:
            status, final_price = "final", price
        else:
            status, final_price = "counter", price

        quote_id = None
        if status != "counter":
            session.closed = True
            quote_id = "q-" + hashlib.sha256(f"{session.id}:{final_price}".encode()).hexdigest()[:8]
            self._quotes[quote_id] = Quote(quote_id, session.flight_id, final_price, list(session.accepted))
        return self._reply(session, status, rejected, granted, price_override=final_price, quote_id=quote_id)

    def _reply(
        self,
        session: Session,
        status: str,
        rejected: Dict[str, str],
        granted: List[dict],
        *,
        price_override: Optional[int] = None,
        quote_id: Optional[str] = None,
        message_override: Optional[str] = None,
    ) -> SellerReply:
        reply = SellerReply(
            session_id=session.id,
            round=session.round,
            status=status,
            price_inr=price_override if price_override is not None else session.current_price(),
            list_price_inr=session.list_price_inr,
            accepted_levers=list(session.accepted),
            new_concessions=granted,
            rejected_levers=rejected,
            quote_id=quote_id,
        )
        reply.message = message_override or phrase(reply, self._phraser)
        return reply


def template_message(reply: SellerReply) -> str:
    price = f"₹{reply.price_inr:,}"
    if reply.status == "accepted":
        return f"Deal at {price}. Quote {reply.quote_id} is yours."
    if reply.status == "final":
        return f"Final offer {price} after {reply.round} rounds. Take it or leave it."
    refused = f" I can't do {', '.join(sorted(reply.rejected_levers))}." if reply.rejected_levers else ""
    return f"I can offer {price} with {', '.join(reply.accepted_levers) or 'no concessions'}.{refused}"


def phrase(reply: SellerReply, phraser: Optional[Phraser] = None) -> str:
    """LLM wording is accepted only if it states the exact price; otherwise the template is used."""
    fallback = template_message(reply)
    if phraser is None:
        return fallback
    try:
        text = phraser(reply)
    except Exception:
        return fallback
    price_forms = (f"{reply.price_inr:,}", str(reply.price_inr))
    return text if text and any(form in text for form in price_forms) else fallback
