"""SAM 3.1 text-prompt segmentation through the Meta Responses API.

SAM localizes visual concepts, not text fields: "departure time" returns nothing on the booking
page, while "blue rounded rectangle" returns the box around the highlighted departure chip.
Only boxes are used; the encoded masks in the reply are ignored.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
from typing import Any, Dict, List, Optional

import httpx

from controlplane import cassette, meta
from controlplane.ledger import LEDGER

SAM_MODEL = meta.SAM_MODEL
DEPARTURE_PROMPT = "blue rounded rectangle"
TIMEOUT_S = 120.0
_BOX = re.compile(r"<\|box;([^|]*)\|>")


def parse_boxes(text: str) -> List[Dict[str, int]]:
    boxes = []
    for raw in _BOX.findall(text or ""):
        fields = dict(part.split("=", 1) for part in raw.split(";") if "=" in part)
        try:
            boxes.append({k: int(fields[k]) for k in ("x1", "y1", "x2", "y2", "w", "h")})
        except (KeyError, ValueError):
            continue
    return boxes


def segment(
    png: bytes,
    prompt: str = DEPARTURE_PROMPT,
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    http: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    request = {"png_sha256": hashlib.sha256(png).hexdigest(), "prompt": prompt}
    return cassette.run("sam", request, lambda: _segment(png, prompt, api_key, base_url, http))


def _segment(
    png: bytes, prompt: str, api_key: Optional[str], base_url: Optional[str], http: Optional[httpx.Client]
) -> Dict[str, Any]:
    key = api_key or os.environ.get("META_API_KEY")
    if not key:
        raise meta.MetaNotConfigured("META_API_KEY is not set (see .env.example)")
    url = (base_url or os.environ.get("META_BASE_URL") or meta.DEFAULT_BASE_URL).rstrip("/") + "/responses"
    body = {
        "model": SAM_MODEL,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(png).decode()},
                ],
            }
        ],
    }
    client = http or httpx.Client(timeout=TIMEOUT_S)
    try:
        response = client.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
    finally:
        if http is None:
            client.close()
    response.raise_for_status()
    text = "".join(
        part.get("text", "")
        for item in response.json().get("output", [])
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )
    LEDGER.record(SAM_MODEL, None, cost=None)
    return {"model": SAM_MODEL, "prompt": prompt, "boxes": parse_boxes(text)}
