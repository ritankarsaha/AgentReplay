"""Page capture for `screenshot` spans: real pixels via headless Chrome/Chromium when installed."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

CAPTURE_TIMEOUT_S = 30
_MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def find_browser() -> Optional[str]:
    explicit = os.environ.get("AGENTREPLAY_CHROME")
    if explicit:
        return explicit if Path(explicit).exists() else None
    for candidate in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(candidate)
        if found:
            return found
    return _MAC_CHROME if Path(_MAC_CHROME).exists() else None


def capture_png(html: str, size: Tuple[int, int] = (900, 560)) -> Optional[bytes]:
    """PNG of the rendered page, or `None` when no browser is available or the capture fails."""
    browser = find_browser()
    if browser is None:
        return None
    with tempfile.TemporaryDirectory(prefix="agentreplay_capture_") as tmp:
        page = Path(tmp) / "page.html"
        out = Path(tmp) / "page.png"
        page.write_text(html, encoding="utf-8")
        try:
            subprocess.run(
                [
                    browser,
                    "--headless=new",
                    "--disable-gpu",
                    "--hide-scrollbars",
                    f"--window-size={size[0]},{size[1]}",
                    f"--screenshot={out}",
                    page.as_uri(),
                ],
                check=True,
                capture_output=True,
                timeout=CAPTURE_TIMEOUT_S,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        return out.read_bytes() if out.exists() else None
