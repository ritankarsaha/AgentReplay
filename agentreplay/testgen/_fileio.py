

from __future__ import annotations

import sys
from pathlib import Path


def warn_if_overwriting_different_content(path: Path, new_content: str) -> None:
    """Print a stderr warning if `path` exists with content different from `new_content`."""
    if not path.exists():
        return
    try:
        existing = path.read_text()
    except OSError:
        return
    if existing != new_content:
        print(f"agentreplay: overwriting existing file with different content: {path}", file=sys.stderr)
