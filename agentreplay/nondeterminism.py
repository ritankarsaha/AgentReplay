"""Opt-in capture of environment nondeterminism (CLAUDE.md §3.1#4).

Mode A (Strict Replay, chunk 3.x) needs every nondeterministic value an
agent observes during a recorded run — not just LLM/tool I/O — to be
reproducible. This module monkeypatches the few stdlib sources of
nondeterminism agents commonly read directly:

- `time.time` / `time.time_ns` / `time.monotonic` / `time.monotonic_ns`
- `random`'s module-level functions (`random`, `randint`, `uniform`,
  `randrange`, `choice`, `sample`, `getrandbits`, `shuffle`)
- `os.environ.get` (also covers `os.getenv`, which delegates to it)

Each call is recorded as a `type="checkpoint"` span (reusing the Span
schema, no new table) named after the call site (e.g. `"time.time"`,
`"random.randint"`, `"os.environ.get"`), with a per-call-site sequence
number in `input["seq"]` and the returned value in `output["value"]`. The
fingerprint is `(name, seq)`-based so the replay engine can match "the Nth
call to time.time() in this run" the same way it matches LLM/tool calls
(§3.4).

**Opt-in, off by default** (`agentreplay.init(capture_nondeterminism=True)`
or `AGENTREPLAY_CAPTURE_NONDETERMINISM=1`): patching `time`/`random`/`os`
globally adds overhead to every call in the process, including ones made by
unrelated libraries, and env var values can be secrets.

**Safety:** env var values are checked against a small built-in list of
sensitive-looking substrings (`key`, `secret`, `password`, `token`, ...) in
the *variable name* and replaced with `"[REDACTED]"` before `config.redact`
even runs — this redaction is unconditional, not opt-out.

**Known limitations (acceptable for v1, smaller/uglier per CLAUDE.md §10):**
- `time.perf_counter`/`time.perf_counter_ns` are deliberately NOT patched —
  the SDK itself uses them for span duration timing, so patching them would
  recursively multiply spans.
- `os.environ["KEY"]` / `os.environ.__getitem__` is not captured (only
  `.get()`/`os.getenv()`, which delegate to it) — patching dunder methods
  requires a class-level patch affecting every `_Environ` instance.
- `datetime.now()`/`datetime.utcnow()` are not patched — `datetime.datetime`
  is a C type and doesn't support attribute assignment.
"""

from __future__ import annotations

import os
import random
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from . import _state
from .collector import get_collector
from .fingerprint import compute_fingerprint
from .serialize import safe_serialize
from .span import Span

_patched = False
_originals: dict = {}

_TIME_FUNCS = ["time", "time_ns", "monotonic", "monotonic_ns"]
_RANDOM_FUNCS = ["random", "randint", "uniform", "randrange", "choice", "sample", "getrandbits"]

_SENSITIVE_ENV_SUBSTRINGS = (
    "key",
    "secret",
    "password",
    "pwd",
    "token",
    "credential",
    "auth",
    "cert",
)


def _is_sensitive_env_name(name: str) -> bool:
    lowered = name.lower()
    return any(s in lowered for s in _SENSITIVE_ENV_SUBSTRINGS)


def _record(
    name: str,
    *,
    input_extra: Optional[dict] = None,
    output_value: Any = None,
    redact_env: bool = False,
) -> None:
    if not _state.is_initialized() or not _state.get_config().enabled:
        return

    try:
        config = _state.get_config()
        seq = _state.next_nondeterminism_seq(name)

        recorded_input: dict = {"seq": seq}
        if input_extra:
            recorded_input.update(safe_serialize(input_extra))

        output_serialized = safe_serialize(output_value)
        if redact_env and isinstance(output_serialized, dict):
            output_serialized = {
                k: ("[REDACTED]" if _is_sensitive_env_name(k) else v)
                for k, v in output_serialized.items()
            }
        recorded_output = {"value": output_serialized}

        if config.redact is not None:
            recorded_input = config.redact(recorded_input)
            recorded_output = config.redact(recorded_output)

        fingerprint = compute_fingerprint({"nondeterminism": name, "seq": seq})
        span = Span(
            id=str(uuid.uuid4()),
            run_id=_state.get_run_id(),
            parent_id=_state.peek_parent_span_id(),
            type="checkpoint",
            name=name,
            input=recorded_input,
            output=recorded_output,
            error=None,
            started_at=datetime.now(timezone.utc),
            duration_ms=0.0,
            fingerprint=fingerprint,
        )
        get_collector().add(span)
    except Exception:
        # Recording must never break the host application.
        print(f"agentreplay: failed to record nondeterminism checkpoint ({name})", file=sys.stderr)


def _wrap_value_func(name: str, original: Callable) -> Callable:
    """Wrap a no-arg-or-simple `*() -> value` function (the `time` funcs)."""

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        _record(name, output_value=result)
        return result

    return wrapper


def _wrap_random_func(name: str, original: Callable) -> Callable:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        _record(name, input_extra={"args": list(args), "kwargs": kwargs}, output_value=result)
        return result

    return wrapper


def _wrap_shuffle(original: Callable) -> Callable:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        # random.shuffle mutates its first argument in place and returns None.
        shuffled = args[0] if args else None
        _record("random.shuffle", output_value=shuffled)
        return result

    return wrapper


def _wrap_environ_get(original: Callable) -> Callable:
    def wrapper(key: str, default: Any = None, *args: Any, **kwargs: Any) -> Any:
        result = original(key, default, *args, **kwargs)
        _record("os.environ.get", input_extra={"key": key}, output_value={key: result}, redact_env=True)
        return result

    return wrapper


def patch_nondeterminism() -> None:
    """Monkeypatch `time`/`random`/`os.environ.get` to record checkpoint spans. Idempotent."""
    global _patched
    if _patched:
        return

    for fn_name in _TIME_FUNCS:
        original = getattr(time, fn_name)
        _originals[("time", fn_name)] = original
        setattr(time, fn_name, _wrap_value_func(f"time.{fn_name}", original))

    for fn_name in _RANDOM_FUNCS:
        original = getattr(random, fn_name)
        _originals[("random", fn_name)] = original
        setattr(random, fn_name, _wrap_random_func(f"random.{fn_name}", original))

    shuffle_original = random.shuffle
    _originals[("random", "shuffle")] = shuffle_original
    random.shuffle = _wrap_shuffle(shuffle_original)

    environ_get_original = os.environ.get
    _originals[("os.environ", "get")] = environ_get_original
    os.environ.get = _wrap_environ_get(environ_get_original)  # type: ignore[method-assign]

    _patched = True


def unpatch_nondeterminism() -> None:
    """Undo `patch_nondeterminism()`. Idempotent."""
    global _patched
    if not _patched:
        return

    for fn_name in _TIME_FUNCS:
        setattr(time, fn_name, _originals.pop(("time", fn_name)))

    for fn_name in _RANDOM_FUNCS:
        setattr(random, fn_name, _originals.pop(("random", fn_name)))

    random.shuffle = _originals.pop(("random", "shuffle"))
    os.environ.get = _originals.pop(("os.environ", "get"))  # type: ignore[method-assign]

    _patched = False
