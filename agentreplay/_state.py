from __future__ import annotations

import threading
from typing import Optional

from .config import Config
from .exceptions import ConfigurationError
from .exporter import BackgroundExporter

_lock = threading.Lock()
_config: Optional[Config] = None
_run_id: Optional[str] = None
_exporter: Optional[BackgroundExporter] = None


def set_config(config: Config) -> None:
    global _config
    with _lock:
        _config = config


def get_config() -> Config:
    if _config is None:
        raise ConfigurationError(
            "agentreplay is not initialized. Call agentreplay.init() first."
        )
    return _config


def is_initialized() -> bool:
    return _config is not None


def set_run_id(run_id: str) -> None:
    global _run_id
    with _lock:
        _run_id = run_id


def get_run_id() -> str:
    if _run_id is None:
        raise ConfigurationError(
            "agentreplay is not initialized. Call agentreplay.init() first."
        )
    return _run_id


def set_exporter(exporter: Optional[BackgroundExporter]) -> None:
    global _exporter
    with _lock:
        _exporter = exporter


def get_exporter() -> Optional[BackgroundExporter]:
    return _exporter


def reset() -> None:
    """Clear global state. Intended for tests."""
    global _config, _run_id, _exporter
    with _lock:
        if _exporter is not None:
            _exporter.shutdown()
        _config = None
        _run_id = None
        _exporter = None
