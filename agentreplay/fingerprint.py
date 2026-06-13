from __future__ import annotations

import hashlib
import json


def compute_fingerprint(payload: dict) -> str:
    """Stable hash of a request payload.

    Used by the replay engine (chunk 3.x) to match a recorded call against
    a new call by request shape, per CLAUDE.md §3.4.
    """
    normalized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
