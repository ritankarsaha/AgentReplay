from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

RedactFn = Callable[[dict], dict]

# The hosted ingest API. Override with AGENTREPLAY_ENDPOINT / init(endpoint=...)
# to self-host or to point at a local `uvicorn app.main:app`.
DEFAULT_ENDPOINT = "https://agentreplay-ingest.fly.dev"


@dataclass(frozen=True)
class Config:
    api_key: Optional[str] = None
    project_id: Optional[str] = None
    endpoint: str = DEFAULT_ENDPOINT
    environment: str = "development"
    enabled: bool = True
    redact: Optional[RedactFn] = None
    agent_version: Optional[str] = None
    framework: Optional[str] = None
    capture_nondeterminism: bool = False
