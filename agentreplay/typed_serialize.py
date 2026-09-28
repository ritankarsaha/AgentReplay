
from __future__ import annotations

import base64
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

_TYPE_KEY = "__agentreplay_type__"
_VALUE_KEY = "value"

_DECODERS = {
    "tuple": lambda raw: tuple(from_typed_json(v) for v in raw),
    "set": lambda raw: set(from_typed_json(v) for v in raw),
    "frozenset": lambda raw: frozenset(from_typed_json(v) for v in raw),
    "bytes": lambda raw: base64.b64decode(raw),
    "datetime": lambda raw: datetime.fromisoformat(raw),
    "date": lambda raw: date.fromisoformat(raw),
    "time": lambda raw: time.fromisoformat(raw),
    "decimal": lambda raw: Decimal(raw),
    "complex": lambda raw: complex(raw[0], raw[1]),
    "str_fallback": lambda raw: raw,
}


def _tag(type_name: str, value: Any) -> dict:
    return {_TYPE_KEY: type_name, _VALUE_KEY: value}


def to_typed_json(value: Any) -> Any:

    if isinstance(value, dict):
        return {k: to_typed_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_typed_json(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, tuple):
        return _tag("tuple", [to_typed_json(v) for v in value])
    if isinstance(value, frozenset):
        return _tag("frozenset", [to_typed_json(v) for v in value])
    if isinstance(value, set):
        return _tag("set", [to_typed_json(v) for v in value])
    if isinstance(value, bytes):
        return _tag("bytes", base64.b64encode(value).decode("ascii"))
    if isinstance(value, datetime):
        return _tag("datetime", value.isoformat())
    if isinstance(value, date):
        return _tag("date", value.isoformat())
    if isinstance(value, time):
        return _tag("time", value.isoformat())
    if isinstance(value, Decimal):
        return _tag("decimal", str(value))
    if isinstance(value, complex):
        return _tag("complex", [value.real, value.imag])
    for attr in ("model_dump", "dict"):
        method = getattr(value, attr, None)
        if callable(method):
            try:
                return to_typed_json(method())
            except Exception:
                break
    return _tag("str_fallback", str(value))


def from_typed_json(value: Any) -> Any:
    """Inverse of `to_typed_json`.

    Safe to call on data that was never typed-tagged — anything that isn't a
    dict matching the exact `{__agentreplay_type__, value}` shape with a
    recognized type name is returned unchanged (recursing into plain dicts/
    lists), so spans recorded before this module existed decode exactly as
    they always have.
    """
    if isinstance(value, dict):
        if set(value.keys()) == {_TYPE_KEY, _VALUE_KEY} and value[_TYPE_KEY] in _DECODERS:
            return _DECODERS[value[_TYPE_KEY]](value[_VALUE_KEY])
        return {k: from_typed_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [from_typed_json(v) for v in value]
    return value
