from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

RedactFn = Callable[[dict], dict]

DEFAULT_ENDPOINT = "https://ingest.agentreplay.dev"


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
