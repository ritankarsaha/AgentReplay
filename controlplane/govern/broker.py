"""Access broker with sandbox connectors

Issues scoped, revocable tokens for fake connectors (airline, card). The
connectors are simulated; token issuance, expiry, revocation and the audit
trail (a `policy` span per authorization, a `tool` span per connector call)
are real.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Protocol

from agentreplay.guard import GuardDecision, emit_span

DEFAULT_TOKEN_TTL = timedelta(hours=1)
TOKEN_PREFIX = "atk_"


class AccessDenied(Exception):
    def __init__(self, rule: str, reason: str) -> None:
        self.rule = rule
        self.reason = reason
        super().__init__(f"access denied [{rule}]: {reason}")


@dataclass
class TokenRecord:
    id: str
    agent_id: str
    connector: str
    scopes: List[str]
    issued_at: datetime
    expires_at: Optional[datetime]
    revoked_at: Optional[datetime] = None


@dataclass(frozen=True)
class IssuedToken:
    token: str
    record: TokenRecord


class TokenStore(Protocol):
    def put(self, record: TokenRecord) -> None: ...
    def get(self, token_id: str) -> Optional[TokenRecord]: ...
    def revoke(self, token_id: str, at: datetime) -> bool: ...


class InMemoryTokenStore:
    def __init__(self) -> None:
        self._rows: Dict[str, TokenRecord] = {}

    def put(self, record: TokenRecord) -> None:
        self._rows[record.id] = record

    def get(self, token_id: str) -> Optional[TokenRecord]:
        return self._rows.get(token_id)

    def revoke(self, token_id: str, at: datetime) -> bool:
        row = self._rows.get(token_id)
        if row is None:
            return False
        if row.revoked_at is None:
            row.revoked_at = at
        return True


def token_id_for(token: str) -> str:
    """Only the hash is stored; the bearer secret is shown once at issuance."""
    return hashlib.sha256(token.encode()).hexdigest()


class Broker:
    def __init__(
        self,
        store: Optional[TokenStore] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.store = store or InMemoryTokenStore()
        self._clock = clock

    def issue(
        self,
        agent_id: str,
        connector: str,
        scopes: List[str],
        ttl: Optional[timedelta] = DEFAULT_TOKEN_TTL,
    ) -> IssuedToken:
        token = TOKEN_PREFIX + secrets.token_urlsafe(24)
        now = self._clock()
        record = TokenRecord(
            id=token_id_for(token),
            agent_id=agent_id,
            connector=connector,
            scopes=sorted(set(scopes)),
            issued_at=now,
            expires_at=now + ttl if ttl is not None else None,
        )
        self.store.put(record)
        return IssuedToken(token=token, record=record)

    def revoke(self, token: str) -> bool:
        return self.store.revoke(token_id_for(token), self._clock())

    def authorize(self, token: str, connector: str, scope: str) -> TokenRecord:
        """Check a token for one use; records a `policy` span; raises `AccessDenied`."""
        name = f"broker.{connector}.{scope}"
        record = self.store.get(token_id_for(token))
        decision = self._decide(record, connector, scope)
        details = dict(decision.details)
        if record is not None:
            details.update(agent_id=record.agent_id, token_id=record.id[:12])
        emit_span(
            "policy",
            name,
            {"connector": connector, "scope": scope},
            GuardDecision(decision.allowed, decision.rule, decision.reason, details).to_dict(),
        )
        if not decision.allowed:
            raise AccessDenied(decision.rule, decision.reason)
        assert record is not None
        return record

    def _decide(self, record: Optional[TokenRecord], connector: str, scope: str) -> GuardDecision:
        if record is None:
            return GuardDecision(False, "token_unknown", "token is not recognized")
        if record.revoked_at is not None:
            return GuardDecision(False, "token_revoked", "token was revoked")
        if record.expires_at is not None and self._clock() >= record.expires_at:
            return GuardDecision(False, "token_expired", "token has expired")
        if record.connector != connector:
            return GuardDecision(False, "connector_mismatch", f"token is not valid for '{connector}'")
        if scope not in record.scopes:
            return GuardDecision(False, "scope_missing", f"token lacks scope '{scope}'")
        return GuardDecision(True, "allowed", "token valid")


class AirlineConnector:
    """Simulated airline API. Deterministic fake data; not a real integration."""

    name = "airline"
    simulated = True

    def __init__(self, broker: Broker, token: str) -> None:
        self._broker = broker
        self._token = token

    def search_flights(self, origin: str, destination: str, date: str) -> List[dict]:
        self._broker.authorize(self._token, self.name, "search")
        return [
            {"flight": f"SIM-{origin}{destination}-1", "date": date, "price_inr": 5900},
            {"flight": f"SIM-{origin}{destination}-2", "date": date, "price_inr": 6400},
        ]

    def book_flight(self, flight: str, price_inr: float) -> dict:
        self._broker.authorize(self._token, self.name, "book")
        return {"pnr": "SIM" + hashlib.sha256(flight.encode()).hexdigest()[:6].upper(), "flight": flight, "price_inr": price_inr, "simulated": True}


class CardConnector:
    """Simulated card network. No real payment rails."""

    name = "card"
    simulated = True

    def __init__(self, broker: Broker, token: str) -> None:
        self._broker = broker
        self._token = token

    def charge(self, amount_inr: float, memo: str = "") -> dict:
        self._broker.authorize(self._token, self.name, "charge")
        return {"charge_id": "SIMCH-" + hashlib.sha256(f"{amount_inr}{memo}".encode()).hexdigest()[:8], "amount_inr": amount_inr, "simulated": True}
