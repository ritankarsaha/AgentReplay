"""Best-effort exception-type resolution for replayed failures (Day 3 backlog).

`ReplayedError` (raised when a replayed call/tool originally failed) only
ever carries `.original_type`/`.original_message` as strings — it never
raises the real exception class, because reconstructing one generally needs
SDK-internal constructor args we don't have from a recorded payload (e.g.
`anthropic.APIStatusError` requires a `response`/`body`, not just a
message). What CLAUDE.md's Day 3 backlog actually asks for is "exact
exception-type fidelity for assertion-spec generation" (Day 4) — i.e.
*knowing* which real class a failure was, not *being* that class. This
module builds a name -> class registry so `ReplayedError.original_exception_class`
can answer that, without changing what replay raises or risking a fragile
dynamic-subclass trick.

Covers two failure sources: Anthropic/OpenAI SDK exceptions (LLM call
failures, looked up lazily so core never requires those packages) and
Python builtins (tool-function failures — a `@agentreplay.tool`-decorated
function can raise anything, most commonly `ValueError`/`KeyError`/etc.).
"""

from __future__ import annotations

import builtins
import importlib
from functools import lru_cache
from typing import Dict, Optional, Tuple, Type

# Known SDK exception class names, looked up by (module, attribute) so a
# package that isn't installed is skipped rather than erroring. Anthropic is
# tried first, so if both define a same-named class (e.g. "RateLimitError"),
# anthropic's wins — an arbitrary but documented tie-break, since a payload
# only ever carries the bare class *name*, not which module it came from.
_SDK_EXCEPTION_NAMES: Tuple[str, ...] = (
    "APIError",
    "APIStatusError",
    "APIConnectionError",
    "APITimeoutError",
    "APIResponseValidationError",
    "RateLimitError",
    "AuthenticationError",
    "BadRequestError",
    "PermissionDeniedError",
    "NotFoundError",
    "ConflictError",
    "UnprocessableEntityError",
    "InternalServerError",
)
_SDK_MODULES: Tuple[str, ...] = ("anthropic", "openai")


@lru_cache(maxsize=1)
def _build_registry() -> Dict[str, Type[BaseException]]:
    registry: Dict[str, Type[BaseException]] = {
        name: cls
        for name, cls in vars(builtins).items()
        if isinstance(cls, type) and issubclass(cls, BaseException)
    }

    for module_path in _SDK_MODULES:
        try:
            module = importlib.import_module(module_path)
        except ImportError:
            continue
        for name in _SDK_EXCEPTION_NAMES:
            cls = getattr(module, name, None)
            if isinstance(cls, type) and issubclass(cls, BaseException):
                registry.setdefault(name, cls)

    return registry


def resolve_exception_class(type_name: Optional[str]) -> Optional[Type[BaseException]]:
    """Look up the real exception class for a recorded `error.type` name.

    Returns `None` if `type_name` is falsy or unrecognized — always safe to
    call, never raises, never requires anthropic/openai to be installed.
    """
    if not type_name:
        return None
    return _build_registry().get(type_name)
