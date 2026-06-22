from __future__ import annotations

from agentreplay.diff import MISSING, NEVER_RECORDED, FieldDiff, diff_payloads, format_diff


def test_identical_dicts_produce_no_diff():
    assert diff_payloads({"a": 1, "b": "x"}, {"a": 1, "b": "x"}) == []


def test_changed_scalar_field_reported():
    diffs = diff_payloads({"model": "gpt-4o"}, {"model": "gpt-4o-mini"})
    assert len(diffs) == 1
    assert diffs[0].path == "$.model"
    assert diffs[0].expected == "gpt-4o"
    assert diffs[0].actual == "gpt-4o-mini"


def test_added_and_removed_keys_reported_with_missing_sentinel():
    diffs = diff_payloads({"a": 1}, {"a": 1, "b": 2})
    assert len(diffs) == 1
    assert diffs[0].path == "$.b"
    assert diffs[0].expected is MISSING
    assert diffs[0].actual == 2

    diffs2 = diff_payloads({"a": 1, "b": 2}, {"a": 1})
    assert len(diffs2) == 1
    assert diffs2[0].path == "$.b"
    assert diffs2[0].expected == 2
    assert diffs2[0].actual is MISSING


def test_recurses_into_nested_dicts():
    expected = {"messages": [{"role": "user", "content": "hi"}]}
    actual = {"messages": [{"role": "user", "content": "bye"}]}
    diffs = diff_payloads(expected, actual)
    assert len(diffs) == 1
    assert diffs[0].path == "$.messages[0].content"
    assert diffs[0].expected == "hi"
    assert diffs[0].actual == "bye"


def test_recurses_into_lists_with_different_lengths():
    diffs = diff_payloads({"tags": ["a", "b"]}, {"tags": ["a"]})
    assert len(diffs) == 1
    assert diffs[0].path == "$.tags[1]"
    assert diffs[0].expected == "b"
    assert diffs[0].actual is MISSING


def test_multiple_differences_all_reported():
    expected = {"model": "m1", "max_tokens": 10}
    actual = {"model": "m2", "max_tokens": 10, "stream": True}
    diffs = diff_payloads(expected, actual)
    paths = {d.path for d in diffs}
    assert paths == {"$.model", "$.stream"}


def test_never_recorded_sentinel_short_circuits():
    diffs = diff_payloads(NEVER_RECORDED, {"model": "m"})
    assert len(diffs) == 1
    assert diffs[0].path == "$"
    assert diffs[0].expected is NEVER_RECORDED
    assert diffs[0].actual == {"model": "m"}


def test_format_diff_empty_list():
    assert "no field-level differences" in format_diff([])


def test_format_diff_nonempty_renders_each_entry():
    diffs = [FieldDiff("$.model", "m1", "m2")]
    text = format_diff(diffs)
    assert "$.model" in text
    assert "m1" in text
    assert "m2" in text


def test_field_diff_repr_handles_sentinels():
    assert "<absent>" in repr(FieldDiff("$.x", MISSING, 1))
    assert "<call site never recorded>" in repr(FieldDiff("$", NEVER_RECORDED, {}))
