from __future__ import annotations

import os
import subprocess
import uuid
from typing import List, Optional

from . import _state, nondeterminism, patching
from .checkpoint import checkpoint
from .collector import get_collector
from .config import DEFAULT_ENDPOINT, Config, RedactFn
from .exceptions import AgentReplayError, ConfigurationError
from .exporter import DEFAULT_FLUSH_INTERVAL, DEFAULT_MAX_BATCH_SIZE, BackgroundExporter
from .fail import fail, track
from .redaction import DEFAULT_PII_FIELD_NAMES, redact_fields, redact_pii
from .span import Span
from .tool import tool
from .version import __version__

__all__ = [
    "init",
    "get_config",
    "is_initialized",
    "get_run_id",
    "get_recorded_spans",
    "flush",
    "shutdown",
    "Config",
    "Span",
    "tool",
    "checkpoint",
    "fail",
    "track",
    "AgentReplayError",
    "ConfigurationError",
    "redact_fields",
    "redact_pii",
    "DEFAULT_PII_FIELD_NAMES",
    "__version__",
]


def _detect_git_sha() -> Optional[str]:
    """Best-effort short git SHA of the current working tree (CLAUDE.md §3.4).

    Returns None if `git` isn't available, this isn't a git repo, or
    anything else goes wrong — agent_version is optional metadata, never
    worth failing init() over.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def init(
    api_key: Optional[str] = None,
    project_id: Optional[str] = None,
    endpoint: Optional[str] = None,
    environment: Optional[str] = None,
    redact: Optional[RedactFn] = None,
    enabled: bool = True,
    flush_interval: float = DEFAULT_FLUSH_INTERVAL,
    max_batch_size: int = DEFAULT_MAX_BATCH_SIZE,
    agent_version: Optional[str] = None,
    framework: Optional[str] = None,
    capture_nondeterminism: Optional[bool] = None,
) -> Config:
    """Initialize the AgentReplay SDK.

    Explicit arguments take precedence over the AGENTREPLAY_API_KEY,
    AGENTREPLAY_PROJECT_ID, AGENTREPLAY_ENDPOINT, AGENTREPLAY_ENVIRONMENT,
    AGENTREPLAY_AGENT_VERSION, AGENTREPLAY_FRAMEWORK, and
    AGENTREPLAY_CAPTURE_NONDETERMINISM environment variables. Pass
    enabled=False to run in local no-op mode without credentials (e.g.
    tests/CI).

    `agent_version`/`framework` populate `runs.agent_version`/`runs.framework`
    (CLAUDE.md §3.4 "Run metadata") for every span sent by this process. If
    `agent_version` isn't given (directly or via env var), it defaults to the
    current git SHA (best-effort, None if unavailable).

    `capture_nondeterminism` (default False, opt-in) monkeypatches
    `time`/`random`/`os.environ.get` to record each call as a
    `type="checkpoint"` span (CLAUDE.md §3.1#4) — see `agentreplay.nondeterminism`
    for what's captured and why it's off by default.

    When enabled, starts a background thread that batches recorded spans
    and POSTs them to `endpoint` every `flush_interval` seconds (or sooner,
    in batches of `max_batch_size`). Call agentreplay.flush() to force an
    immediate export, or agentreplay.shutdown() to stop the background
    thread and flush what remains (also run automatically at interpreter exit).
    """
    resolved_api_key = api_key or os.environ.get("AGENTREPLAY_API_KEY")
    resolved_project_id = project_id or os.environ.get("AGENTREPLAY_PROJECT_ID")
    resolved_endpoint = endpoint or os.environ.get("AGENTREPLAY_ENDPOINT", DEFAULT_ENDPOINT)
    resolved_environment = environment or os.environ.get("AGENTREPLAY_ENVIRONMENT", "development")
    resolved_agent_version = (
        agent_version or os.environ.get("AGENTREPLAY_AGENT_VERSION") or _detect_git_sha()
    )
    resolved_framework = framework or os.environ.get("AGENTREPLAY_FRAMEWORK")
    resolved_capture_nondeterminism = (
        capture_nondeterminism
        if capture_nondeterminism is not None
        else os.environ.get("AGENTREPLAY_CAPTURE_NONDETERMINISM", "").lower() in ("1", "true", "yes")
    )

    if enabled and (not resolved_api_key or not resolved_project_id):
        raise ConfigurationError(
            "agentreplay.init() requires 'api_key' and 'project_id' "
            "(directly or via AGENTREPLAY_API_KEY / AGENTREPLAY_PROJECT_ID env vars). "
            "Pass enabled=False to run in local no-op mode without these."
        )

    config = Config(
        api_key=resolved_api_key,
        project_id=resolved_project_id,
        endpoint=resolved_endpoint,
        environment=resolved_environment,
        enabled=enabled,
        redact=redact,
        agent_version=resolved_agent_version,
        framework=resolved_framework,
        capture_nondeterminism=resolved_capture_nondeterminism,
    )
    _state.set_config(config)
    _state.set_run_id(str(uuid.uuid4()))
    patching.patch_all()

    if config.enabled and config.capture_nondeterminism:
        nondeterminism.patch_nondeterminism()
    else:
        nondeterminism.unpatch_nondeterminism()

    existing_exporter = _state.get_exporter()
    if existing_exporter is not None:
        existing_exporter.shutdown()

    if config.enabled:
        exporter = BackgroundExporter(
            config, flush_interval=flush_interval, max_batch_size=max_batch_size
        )
        exporter.start()
        _state.set_exporter(exporter)
    else:
        _state.set_exporter(None)

    return config


def get_config() -> Config:
    return _state.get_config()


def is_initialized() -> bool:
    return _state.is_initialized()


def get_run_id() -> str:
    """Return the run_id generated by the current agentreplay.init() call."""
    return _state.get_run_id()


def get_recorded_spans() -> List[Span]:
    """Return all spans currently buffered, not yet exported (debugging aid)."""
    return get_collector().get_all()


def flush() -> None:
    """Force an immediate export of any buffered spans. No-op if disabled."""
    exporter = _state.get_exporter()
    if exporter is not None:
        exporter.flush()


def shutdown() -> None:
    """Flush buffered spans and stop the background exporter. No-op if disabled."""
    exporter = _state.get_exporter()
    if exporter is not None:
        exporter.shutdown()
        _state.set_exporter(None)
