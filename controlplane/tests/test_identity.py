from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from controlplane.govern import identity as ident


def _manifest(keypair, **kwargs):
    return ident.sign_manifest(
        keypair,
        allowed_tools=["search_flights", "book_flight"],
        constraints={"max_spend_inr": 6000, "max_bookings_per_task": 1, "geography": "domestic"},
        **kwargs,
    )


def test_agent_id_is_derived_from_public_key():
    kp = ident.generate_keypair()
    assert kp.agent_id == ident.agent_id_for(kp.public_key)
    assert kp.agent_id.startswith("agt_")
    assert ident.generate_keypair().agent_id != kp.agent_id


def test_sign_and_verify_roundtrip():
    kp = ident.generate_keypair()
    manifest = _manifest(kp)
    ident.verify_manifest(manifest, kp.public_key)
    restored = ident.ScopeManifest.from_dict(manifest.to_dict())
    ident.verify_manifest(restored, kp.public_key)


def test_canonicalization_is_order_independent():
    assert ident.canonical_json({"b": 1, "a": [2, 1]}) == ident.canonical_json({"a": [2, 1], "b": 1})


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["constraints"].update(max_spend_inr=60000),
        lambda d: d["allowed_tools"].append("wire_money"),
        lambda d: d.update(version=2),
        lambda d: d.update(expires_at=None),
    ],
)
def test_tampering_breaks_signature(mutate):
    kp = ident.generate_keypair()
    data = _manifest(kp).to_dict()
    mutate(data)
    with pytest.raises(ident.InvalidSignature):
        ident.verify_manifest(ident.ScopeManifest.from_dict(data), kp.public_key)


def test_wrong_key_rejected():
    kp, other = ident.generate_keypair(), ident.generate_keypair()
    with pytest.raises(ident.InvalidSignature):
        ident.verify_manifest(_manifest(kp), other.public_key)


def test_garbage_signature_rejected():
    kp = ident.generate_keypair()
    manifest = _manifest(kp)
    manifest.signature = "not-a-signature"
    with pytest.raises(ident.InvalidSignature):
        ident.verify_manifest(manifest, kp.public_key)


def test_expiry_and_not_yet_valid():
    kp = ident.generate_keypair()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    manifest = _manifest(kp, issued_at=now, ttl=timedelta(days=1))
    ident.verify_manifest(manifest, kp.public_key, now=now + timedelta(hours=23))
    with pytest.raises(ident.ManifestExpired):
        ident.verify_manifest(manifest, kp.public_key, now=now + timedelta(days=1))
    with pytest.raises(ident.ManifestNotYetValid):
        ident.verify_manifest(manifest, kp.public_key, now=now - timedelta(seconds=1))


def test_no_expiry_manifest_is_valid_indefinitely():
    kp = ident.generate_keypair()
    manifest = _manifest(kp, ttl=None)
    assert manifest.expires_at is None
    ident.verify_manifest(manifest, kp.public_key, now=datetime(2099, 1, 1, tzinfo=timezone.utc))


@pytest.mark.parametrize(
    "constraints",
    [{"max_spend_inr": "lots"}, {"max_spend_inr": -1}, {"max_bookings_per_task": True}, {"surprise": 1}],
)
def test_invalid_constraints_rejected(constraints):
    kp = ident.generate_keypair()
    with pytest.raises(ident.InvalidManifest):
        ident.sign_manifest(kp, allowed_tools=["x"], constraints=constraints)


def test_malformed_manifest_dict():
    with pytest.raises(ident.InvalidManifest):
        ident.ScopeManifest.from_dict({"agent_id": "a"})


GOLDEN = {
    "public_key": "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg",
    "agent_id": "agt_56475aa75463474c",
    "manifest": {
        "agent_id": "agt_56475aa75463474c",
        "version": 1,
        "allowed_tools": ["book_flight", "search_flights"],
        "constraints": {"max_spend_inr": 6000, "max_bookings_per_task": 1, "geography": "domestic"},
        "issued_at": "2026-11-01T00:00:00Z",
        "expires_at": "2036-10-29T00:00:00Z",
        "signature": "rzVL3tI4gmRl_Tq9XKGmv59TzL1_WF6VAgHbRvI9z3kUkgx2Dnha4TqD_wosQBmjy2w6W-Q2EfVaWfDBoTanDw",
    },
}


def test_golden_vector_shared_with_ingest():
    """Same vector is pinned in ingest/tests/test_govern.py; both sides must agree on the wire format."""
    assert ident.agent_id_for(GOLDEN["public_key"]) == GOLDEN["agent_id"]
    manifest = ident.ScopeManifest.from_dict(GOLDEN["manifest"])
    ident.verify_manifest(manifest, GOLDEN["public_key"], now=datetime(2027, 1, 1, tzinfo=timezone.utc))
