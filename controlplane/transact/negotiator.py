"""Buyer side of the negotiation. The seller is the deterministic rules engine in `world/`."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Protocol

from agentreplay.guard import emit_span
from controlplane import cassette
from world.seller import LEVERS, MAX_ROUNDS

PRIORITY = ["flex_window", "non_refundable", "fee_waiver", "no_checked_bag", "partner_wallet"]
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
BUYER_MAX_TOKENS = 4096


class BuyerError(Exception):
    """The buyer produced no valid move."""


@dataclass
class BuyerMove:
    levers: List[str]
    target_price_inr: int
    rationale: str = ""


class Buyer(Protocol):
    name: str

    def propose(self, ctx: dict) -> BuyerMove: ...


class ScriptedBuyer:
    """Deterministic buyer: offers two concessions in round one, then one more each round."""

    name = "scripted"

    def propose(self, ctx: dict) -> BuyerMove:
        accepted = set(ctx.get("accepted_levers", []))
        rejected = set(ctx.get("rejected_levers", []))
        remaining = [lever for lever in PRIORITY if lever not in accepted and lever not in rejected]
        batch = 2 if ctx["round"] == 1 else 1
        return BuyerMove(remaining[:batch], ctx["goal_price_inr"], "scripted concession ladder")


class MetaBuyer:
    """Muse Spark chooses the concessions. Output is validated; invalid output raises `BuyerError`."""

    name = "meta"

    def __init__(self, chat: Optional[Callable[..., str]] = None) -> None:
        self._chat = chat

    def propose(self, ctx: dict) -> BuyerMove:
        from controlplane import meta

        chat = self._chat or meta.chat
        prompt = (
            "You negotiate a flight fare for a customer against a seller.\n"
            f"Customer intent: {ctx['intent_text']}\n"
            f"List price: {ctx['list_price_inr']} INR. Goal price: {ctx['goal_price_inr']} INR. "
            f"Round {ctx['round']} of {MAX_ROUNDS}.\n"
            f"Concessions you may offer (lever: INR the seller takes off): {json.dumps(LEVERS)}\n"
            f"Already accepted: {ctx.get('accepted_levers', [])}. "
            f"Seller refused: {ctx.get('rejected_levers', [])}. "
            f"Seller's last message: {ctx.get('seller_message', '(none)')}\n"
            "The seller accepts any target at or above its computed price, so aim at your goal price "
            "and do not state a target above it. Offer only concessions the customer would accept.\n"
            'Reply with only JSON: {"levers": [names], "target_price_inr": int, "rationale": str}.'
        )
        text = cassette.run(
            f"buyer.round{ctx['round']}",
            {"prompt": prompt},
            lambda: chat(
                prompt, system="You are a careful negotiating agent. Output JSON only.", max_tokens=BUYER_MAX_TOKENS
            ),
            valid=bool,
        )
        match = _JSON_OBJECT.search(text or "")
        if not match:
            raise BuyerError("no JSON object in model output")
        try:
            parsed = json.loads(match.group(0))
            levers = [str(item) for item in parsed["levers"]]
            target = int(parsed["target_price_inr"])
        except (ValueError, KeyError, TypeError) as exc:
            raise BuyerError(f"malformed move: {exc}") from exc
        unknown = [lever for lever in levers if lever not in LEVERS]
        if unknown or target <= 0:
            raise BuyerError(f"invalid move: unknown levers {unknown}, target {target}")
        return BuyerMove(levers, target, str(parsed.get("rationale", ""))[:300])


NegotiateCall = Callable[[str, List[str], int], dict]


def run_negotiation(
    negotiate: NegotiateCall,
    session: dict,
    buyer: Buyer,
    *,
    intent_text: str,
    goal_price_inr: int,
) -> dict:
    """Run rounds until the seller accepts or gives a final offer; returns the last reply."""
    ctx = {
        "intent_text": intent_text,
        "list_price_inr": session["list_price_inr"],
        "goal_price_inr": goal_price_inr,
        "accepted_levers": [],
        "rejected_levers": [],
    }
    reply: dict = {}
    for round_number in range(1, MAX_ROUNDS + 1):
        ctx["round"] = round_number
        fallback = False
        try:
            move = buyer.propose(ctx)
        except BuyerError:
            move, fallback = ScriptedBuyer().propose(ctx), True
        reply = negotiate(session["session_id"], move.levers, move.target_price_inr)
        emit_span(
            "negotiation",
            f"negotiate.round{round_number}",
            {
                "session_id": session["session_id"],
                "round": round_number,
                "offered_levers": move.levers,
                "target_price_inr": move.target_price_inr,
                "buyer": "scripted" if fallback else buyer.name,
                "buyer_fallback": fallback,
                "rationale": move.rationale,
            },
            {**reply, "simulated_seller": True},
        )
        ctx["accepted_levers"] = reply["accepted_levers"]
        ctx["rejected_levers"] = sorted(set(ctx["rejected_levers"]) | set(reply["rejected_levers"]))
        ctx["seller_message"] = reply["message"]
        if reply["status"] != "counter":
            break
    return reply
