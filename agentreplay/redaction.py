from __future__ import annotations

from typing import Any, FrozenSet, Iterable, Optional

from .config import RedactFn

DEFAULT_PII_FIELD_NAMES: FrozenSet[str] = frozenset(
    {
        "email",
        "e-mail",
        "phone",
        "phone_number",
        "ssn",
        "social_security_number",
        "password",
        "passwd",
        "secret",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "auth_token",
        "authorization",
        "credit_card",
        "card_number",
        "cvv",
        "address",
        "dob",
        "date_of_birth",
    }
)

REDACTED_VALUE = "[REDACTED]"


def redact_fields(field_names: Optional[Iterable[str]] = None, *, replacement: str = REDACTED_VALUE) -> RedactFn:
    """Build a `Config.redact` callback that masks values of known PII/secret fields.

    Walks a span's input/output dict recursively (including nested lists),
    replacing the value of any dict key whose name matches (case-insensitive)
    one of `field_names` (default: `DEFAULT_PII_FIELD_NAMES`) with `replacement`.
    """
    names = {n.lower() for n in (field_names if field_names is not None else DEFAULT_PII_FIELD_NAMES)}

    def _walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: (replacement if isinstance(k, str) and k.lower() in names else _walk(v))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [_walk(v) for v in value]
        return value

    def _redact(payload: dict) -> dict:
        return _walk(payload)

    return _redact


redact_pii: RedactFn = redact_fields()
