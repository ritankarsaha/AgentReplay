"""API-key generation/hashing and a small in-process rate limiter.

Keys are shown to the user exactly once (at creation/rotation) and only a
sha256 digest is stored. API keys are high-entropy random tokens, not
user-chosen passwords, so a fast unsalted hash is the right tool here (same
approach as GitHub/Stripe token storage) -- a slow KDF would only add
latency to every ingest request.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from fastapi import HTTPException, status

KEY_PREFIX_LEN = 11  # "ar_" + 8 chars: enough to recognise a key in a UI, useless to attackers


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def generate_api_key() -> Tuple[str, str, str]:
    """Return `(plaintext_key, sha256_hex, display_prefix)`."""
    key = f"ar_{secrets.token_urlsafe(32)}"
    return key, hash_api_key(key), key[:KEY_PREFIX_LEN]


def generate_project_id() -> str:
    return f"proj_{secrets.token_hex(6)}"


class RateLimiter:
    """Sliding-window limiter keyed by an arbitrary string.

    In-process only: with N uvicorn workers/machines the effective limit is
    N x the configured one. That's an accepted v1 tradeoff (abuse brake, not
    billing-grade metering); swap the storage for Redis (already a
    dependency for Celery) if exact global limits are needed.
    """

    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, *, limit: int, window_seconds: float, label: str = "requests") -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = max(1, int(window_seconds - (now - hits[0])))
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    f"Rate limit exceeded ({limit} {label} per {int(window_seconds)}s)",
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()
