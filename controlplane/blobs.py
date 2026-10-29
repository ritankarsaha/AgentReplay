"""Content-addressed blob store for payloads too large or binary for a span (screenshots, HTML)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional

DEFAULT_DIR = ".agentreplay/blobs"
_EXTENSIONS = {"image/png": ".png", "text/html": ".html", "image/svg+xml": ".svg"}


class BlobStore:
    def __init__(self, root: Optional[str] = None) -> None:
        self.root = Path(root or os.environ.get("AGENTREPLAY_BLOB_DIR") or DEFAULT_DIR)

    def put(self, payload: bytes, mime: str) -> dict:
        digest = hashlib.sha256(payload).hexdigest()
        path = self.root / f"{digest}{_EXTENSIONS.get(mime, '')}"
        if not path.exists():
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(payload)
            tmp.replace(path)
        return {"sha256": digest, "bytes": len(payload), "mime": mime, "uri": f"blob://sha256/{digest}"}

    def get(self, digest: str) -> Optional[bytes]:
        for path in self.root.glob(f"{digest}*"):
            if path.suffix != ".tmp":
                return path.read_bytes()
        return None
