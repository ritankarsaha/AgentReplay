"""Agent identity and signed scope manifests

Each agent has an Ed25519 keypair; `agent_id` is derived from the public key.
A manifest is canonical JSON signed with the agent's key (held by its owner)
and verified against the registered public key.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from cryptography.exceptions import InvalidSignature as _CryptoInvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

DEFAULT_TTL = timedelta(days=30)
KNOWN_CONSTRAINTS = {"max_spend_inr": (int, float), "max_bookings_per_task": (int,), "geography": (str,)}


class ManifestError(Exception):
    """Manifest failed verification."""


class InvalidSignature(ManifestError):
    pass


class ManifestExpired(ManifestError):
    pass


class ManifestNotYetValid(ManifestError):
    pass


class InvalidManifest(ManifestError):
    pass


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True)
class KeyPair:
    private_key: str
    public_key: str

    @property
    def agent_id(self) -> str:
        return agent_id_for(self.public_key)


def generate_keypair() -> KeyPair:
    private = Ed25519PrivateKey.generate()
    raw_private = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    raw_public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return KeyPair(private_key=_b64(raw_private), public_key=_b64(raw_public))


def agent_id_for(public_key: str) -> str:
    return "agt_" + hashlib.sha256(_unb64(public_key)).hexdigest()[:16]


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass
class ScopeManifest:
    agent_id: str
    version: int
    allowed_tools: List[str]
    constraints: Dict[str, Any]
    issued_at: str
    expires_at: Optional[str]
    signature: str = ""

    def payload(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "version": self.version,
            "allowed_tools": sorted(self.allowed_tools),
            "constraints": self.constraints,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    def to_dict(self) -> dict:
        return {**self.payload(), "signature": self.signature}

    @classmethod
    def from_dict(cls, data: dict) -> "ScopeManifest":
        try:
            manifest = cls(
                agent_id=data["agent_id"],
                version=int(data["version"]),
                allowed_tools=list(data["allowed_tools"]),
                constraints=dict(data.get("constraints") or {}),
                issued_at=data["issued_at"],
                expires_at=data.get("expires_at"),
                signature=data.get("signature", ""),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidManifest(f"malformed manifest: {exc}") from exc
        validate_constraints(manifest.constraints)
        return manifest

    def signing_bytes(self) -> bytes:
        return canonical_json(self.payload())


def validate_constraints(constraints: Dict[str, Any]) -> None:
    for key, value in constraints.items():
        types = KNOWN_CONSTRAINTS.get(key)
        if types is None:
            raise InvalidManifest(f"unknown constraint '{key}'")
        if isinstance(value, bool) or not isinstance(value, types):
            raise InvalidManifest(f"constraint '{key}' has invalid type {type(value).__name__}")
        if isinstance(value, (int, float)) and value < 0:
            raise InvalidManifest(f"constraint '{key}' must be non-negative")


def sign_manifest(
    keypair: KeyPair,
    *,
    allowed_tools: List[str],
    constraints: Optional[Dict[str, Any]] = None,
    version: int = 1,
    ttl: Optional[timedelta] = DEFAULT_TTL,
    issued_at: Optional[datetime] = None,
) -> ScopeManifest:
    constraints = dict(constraints or {})
    validate_constraints(constraints)
    issued = issued_at or datetime.now(timezone.utc)
    manifest = ScopeManifest(
        agent_id=keypair.agent_id,
        version=version,
        allowed_tools=sorted(set(allowed_tools)),
        constraints=constraints,
        issued_at=_iso(issued),
        expires_at=_iso(issued + ttl) if ttl is not None else None,
    )
    private = Ed25519PrivateKey.from_private_bytes(_unb64(keypair.private_key))
    manifest.signature = _b64(private.sign(manifest.signing_bytes()))
    return manifest


def verify_manifest(
    manifest: ScopeManifest, public_key: str, *, now: Optional[datetime] = None
) -> None:
    """Raise a `ManifestError` subclass unless the manifest is authentic and currently valid."""
    if manifest.agent_id != agent_id_for(public_key):
        raise InvalidSignature("manifest agent_id does not match the verifying key")
    try:
        public = Ed25519PublicKey.from_public_bytes(_unb64(public_key))
        public.verify(_unb64(manifest.signature), manifest.signing_bytes())
    except (_CryptoInvalidSignature, ValueError) as exc:
        raise InvalidSignature("manifest signature is invalid") from exc
    current = now or datetime.now(timezone.utc)
    if current < _parse(manifest.issued_at):
        raise ManifestNotYetValid("manifest is not valid yet")
    if manifest.expires_at is not None and current >= _parse(manifest.expires_at):
        raise ManifestExpired("manifest has expired")
