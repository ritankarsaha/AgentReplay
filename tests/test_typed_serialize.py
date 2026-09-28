from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal

import pytest

from agentreplay.typed_serialize import from_typed_json, to_typed_json


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        1,
        1.5,
        "hello",
        [1, "a", None],
        {"a": 1, "b": [1, 2]},
    ],
)
def test_plain_json_values_round_trip_untouched(value):
    encoded = to_typed_json(value)
    assert encoded == value
    assert from_typed_json(encoded) == value


def test_tuple_round_trips_as_tuple():
    encoded = to_typed_json((1, "a", None))
    assert encoded == {"__agentreplay_type__": "tuple", "value": [1, "a", None]}
    decoded = from_typed_json(encoded)
    assert decoded == (1, "a", None)
    assert isinstance(decoded, tuple)


def test_nested_tuple_inside_dict_and_list_round_trips():
    value = {"points": [(1, 2), (3, 4)]}
    decoded = from_typed_json(to_typed_json(value))
    assert decoded == {"points": [(1, 2), (3, 4)]}
    assert all(isinstance(p, tuple) for p in decoded["points"])


def test_set_round_trips_as_set():
    decoded = from_typed_json(to_typed_json({1, 2, 3}))
    assert decoded == {1, 2, 3}
    assert isinstance(decoded, set)


def test_frozenset_round_trips_as_frozenset():
    decoded = from_typed_json(to_typed_json(frozenset({1, 2})))
    assert decoded == frozenset({1, 2})
    assert isinstance(decoded, frozenset)


def test_bytes_round_trips_as_bytes():
    decoded = from_typed_json(to_typed_json(b"\x00\x01binary"))
    assert decoded == b"\x00\x01binary"
    assert isinstance(decoded, bytes)


def test_datetime_round_trips_as_datetime():
    dt = datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc)
    decoded = from_typed_json(to_typed_json(dt))
    assert decoded == dt
    assert isinstance(decoded, datetime)


def test_date_round_trips_as_date():
    d = date(2026, 1, 1)
    decoded = from_typed_json(to_typed_json(d))
    assert decoded == d
    assert isinstance(decoded, date)
    assert not isinstance(decoded, datetime)


def test_time_round_trips_as_time():
    t = time(12, 30, 1)
    decoded = from_typed_json(to_typed_json(t))
    assert decoded == t
    assert isinstance(decoded, time)


def test_decimal_round_trips_as_decimal():
    decoded = from_typed_json(to_typed_json(Decimal("1.50")))
    assert decoded == Decimal("1.50")
    assert isinstance(decoded, Decimal)


def test_complex_round_trips_as_complex():
    decoded = from_typed_json(to_typed_json(2 + 3j))
    assert decoded == 2 + 3j
    assert isinstance(decoded, complex)


def test_opaque_object_falls_back_to_tagged_str():
    class Widget:
        def __repr__(self):
            return "Widget(42)"

    encoded = to_typed_json(Widget())
    assert encoded == {"__agentreplay_type__": "str_fallback", "value": "Widget(42)"}
    assert from_typed_json(encoded) == "Widget(42)"


def test_model_like_object_expands_via_dict_method():
    class Model:
        def dict(self):
            return {"a": (1, 2)}

    decoded = from_typed_json(to_typed_json(Model()))
    assert decoded == {"a": (1, 2)}
    assert isinstance(decoded["a"], tuple)


def test_legacy_untagged_output_passes_through_unchanged():
    # A span recorded before this module existed: a tuple recorded by the
    # old safe_serialize()-only path degraded to a plain list. Decoding it
    # must not crash or misinterpret it -- it stays a list, exactly as it
    # always replayed.
    legacy_output = {"items": [1, 2, 3]}
    assert from_typed_json(legacy_output) == legacy_output


def test_dict_with_unrecognized_type_tag_is_treated_as_plain_dict():
    # Defends against colliding with a real tool output that happens to use
    # these exact two key names with a type name we don't recognize.
    value = {"__agentreplay_type__": "totally_unknown", "value": [1, 2]}
    assert from_typed_json(value) == value


def test_does_not_mutate_fingerprint_relevant_input_shape():
    # Sanity check on the core invariant this module exists to preserve:
    # to_typed_json is never used on input/fingerprint payloads, so a tuple
    # in *input* still serializes the old (untyped) way elsewhere in the
    # codebase. This module only ever touches `output`.
    import inspect

    from agentreplay.tool import _build_tool_payload

    source = inspect.getsource(_build_tool_payload)
    assert "to_typed_json" not in source
    assert "safe_serialize" in source
