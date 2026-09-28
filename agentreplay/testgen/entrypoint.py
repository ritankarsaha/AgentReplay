
from __future__ import annotations

import inspect
from typing import Any, Callable

from .._async_call import call_maybe_async


def call_entrypoint_with_input(func: Callable[..., Any], recorded_input: Any) -> Any:

    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return call_maybe_async(func())

    params = list(sig.parameters.values())
    if not params:
        return call_maybe_async(func())

    first = params[0]
    if first.kind is inspect.Parameter.KEYWORD_ONLY:
        return call_maybe_async(func(**{first.name: recorded_input}))
    return call_maybe_async(func(recorded_input))
