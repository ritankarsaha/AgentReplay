"""Server-side verification of signed scope manifests.

Mirrors `controlplane/govern/identity.py` (Ed25519 over canonical JSON of the
manifest minus `signature`; agent_id = "agt_" + sha256(raw public key)[:16]).
`tests/test_govern.py` pins both to a shared golden vector.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def decode_public_key(public_key: str) -> bytes:
    raw = _unb64(public_key)
    if len(raw) != 32:
        raise ValueError("public key must be 32 raw bytes")
    return raw


def agent_id_for(public_key: str) -> str:
    return "agt_" + hashlib.sha256(decode_public_key(public_key)).hexdigest()[:16]


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def verify_manifest_signature(public_key: str, manifest: dict) -> bool:
    payload = {k: v for k, v in manifest.items() if k != "signature"}
    if isinstance(payload.get("allowed_tools"), list):
        payload["allowed_tools"] = sorted(payload["allowed_tools"])
    try:
        Ed25519PublicKey.from_public_bytes(decode_public_key(public_key)).verify(
            _unb64(str(manifest.get("signature", ""))), canonical_json(payload)
        )
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True
