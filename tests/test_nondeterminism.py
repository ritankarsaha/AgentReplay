from __future__ import annotations

import os
import random
import time

import agentreplay
from agentreplay import nondeterminism


def _checkpoints(name=None):
    spans = [s for s in agentreplay.get_recorded_spans() if s.type == "checkpoint"]
    if name is not None:
        spans = [s for s in spans if s.name == name]
    return spans


def test_disabled_by_default_no_patching_no_spans():
    agentreplay.init(api_key="key", project_id="proj")

    assert nondeterminism._patched is False

    time.time()
    random.random()
    os.environ.get("PATH")

    assert _checkpoints() == []


def test_capture_records_time_calls():
    agentreplay.init(api_key="key", project_id="proj", capture_nondeterminism=True)

    assert nondeterminism._patched is True

    value = time.time()

    spans = _checkpoints("time.time")
    assert len(spans) == 1
    assert spans[0].input == {"seq": 0}
    assert spans[0].output == {"value": value}
    assert spans[0].parent_id is None
    assert spans[0].duration_ms == 0.0
    assert isinstance(spans[0].fingerprint, str)


def test_capture_records_sequential_seq_per_call_site():
    agentreplay.init(api_key="key", project_id="proj", capture_nondeterminism=True)

    time.time()
    time.time()
    time.monotonic()

    time_spans = _checkpoints("time.time")
    monotonic_spans = _checkpoints("time.monotonic")

    assert [s.input["seq"] for s in time_spans] == [0, 1]
    assert [s.input["seq"] for s in monotonic_spans] == [0]
    # different seq -> different fingerprint
    assert time_spans[0].fingerprint != time_spans[1].fingerprint


def test_capture_records_random_calls_with_args():
    agentreplay.init(api_key="key", project_id="proj", capture_nondeterminism=True)

    value = random.randint(1, 10)

    spans = _checkpoints("random.randint")
    assert len(spans) == 1
    assert spans[0].input == {"seq": 0, "args": [1, 10], "kwargs": {}}
    assert spans[0].output == {"value": value}
    assert 1 <= value <= 10


def test_capture_records_shuffle_output_as_mutated_list():
    agentreplay.init(api_key="key", project_id="proj", capture_nondeterminism=True)

    items = [1, 2, 3, 4, 5]
    random.shuffle(items)

    spans = _checkpoints("random.shuffle")
    assert len(spans) == 1
    assert spans[0].output == {"value": items}


def test_capture_records_env_var_reads():
    os.environ["AGENTREPLAY_TEST_VAR"] = "hello"
    try:
        agentreplay.init(api_key="key", project_id="proj", capture_nondeterminism=True)

        value = os.environ.get("AGENTREPLAY_TEST_VAR")
        assert value == "hello"

        spans = _checkpoints("os.environ.get")
        assert len(spans) == 1
        assert spans[0].input["key"] == "AGENTREPLAY_TEST_VAR"
        assert spans[0].output == {"value": {"AGENTREPLAY_TEST_VAR": "hello"}}
    finally:
        del os.environ["AGENTREPLAY_TEST_VAR"]


def test_capture_redacts_sensitive_env_var_names_unconditionally():
    os.environ["MY_SECRET_API_KEY"] = "super-secret"
    try:
        agentreplay.init(api_key="key", project_id="proj", capture_nondeterminism=True)

        os.environ.get("MY_SECRET_API_KEY")

        spans = _checkpoints("os.environ.get")
        assert spans[0].output == {"value": {"MY_SECRET_API_KEY": "[REDACTED]"}}
    finally:
        del os.environ["MY_SECRET_API_KEY"]


def test_os_getenv_delegates_to_patched_environ_get():
    os.environ["AGENTREPLAY_TEST_VAR"] = "world"
    try:
        agentreplay.init(api_key="key", project_id="proj", capture_nondeterminism=True)

        value = os.getenv("AGENTREPLAY_TEST_VAR")
        assert value == "world"

        spans = _checkpoints("os.environ.get")
        assert len(spans) == 1
        assert spans[0].output == {"value": {"AGENTREPLAY_TEST_VAR": "world"}}
    finally:
        del os.environ["AGENTREPLAY_TEST_VAR"]


def test_custom_redact_applied_on_top_of_env_redaction():
    os.environ["AGENTREPLAY_TEST_VAR"] = "hello"

    def redact(payload):
        if "value" in payload and isinstance(payload["value"], dict):
            return {"value": {k: "[CUSTOM]" for k in payload["value"]}}
        return payload

    try:
        agentreplay.init(api_key="key", project_id="proj", capture_nondeterminism=True, redact=redact)

        os.environ.get("AGENTREPLAY_TEST_VAR")

        spans = _checkpoints("os.environ.get")
        assert spans[0].output == {"value": {"AGENTREPLAY_TEST_VAR": "[CUSTOM]"}}
    finally:
        del os.environ["AGENTREPLAY_TEST_VAR"]


def test_disabled_mode_records_nothing_even_with_capture_flag():
    agentreplay.init(enabled=False, capture_nondeterminism=True)

    assert nondeterminism._patched is False

    time.time()
    assert _checkpoints() == []


def test_patch_and_unpatch_are_idempotent():
    nondeterminism.patch_nondeterminism()
    original = time.time
    nondeterminism.patch_nondeterminism()
    assert time.time is original  # second patch is a no-op

    nondeterminism.unpatch_nondeterminism()
    restored = time.time
    nondeterminism.unpatch_nondeterminism()
    assert time.time is restored  # second unpatch is a no-op


def test_env_var_capture_via_capture_nondeterminism_env_var(monkeypatch):
    monkeypatch.setenv("AGENTREPLAY_CAPTURE_NONDETERMINISM", "1")

    agentreplay.init(api_key="key", project_id="proj")

    assert nondeterminism._patched is True
