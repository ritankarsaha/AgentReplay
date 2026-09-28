"""Shared helper for invoking an entrypoint that may be sync or async."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any


def call_maybe_async(result: Any) -> Any:
    """Await `result` to completion if it's awaitable, else return it unchanged."""
    if inspect.isawaitable(result):
        return asyncio.run(result)
    return result
