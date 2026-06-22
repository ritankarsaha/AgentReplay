from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATABASE_URL = "postgresql+asyncpg://agentreplay:agentreplay@localhost:5432/agentreplay"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
# Free NIM endpoint, same one `examples/resume_bot.py`/`examples/langgraph_demo.py`
# use as an Anthropic stand-in when no real key is available (PROGRESS.md
# Blockers) — the classifier (chunk 3.6) supports the same swap, since
# CLAUDE.md's NIM cost-cutting track explicitly scopes itself to "the
# CLASSIFIER ONLY (3.6)".
DEFAULT_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_NIM_MODEL = "meta/llama-3.1-70b-instruct"

# Resolve relative to this file (ingest/app/config.py -> ingest/.env) so
# Settings() works regardless of the process's current working directory.
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """Ingest API configuration, loaded from env vars / `ingest/.env`.

    All env vars are prefixed `AGENTREPLAY_INGEST_`, e.g.
    `AGENTREPLAY_INGEST_DATABASE_URL`. Other env vars (e.g. the root `.env`'s
    `SUPABASE_*` keys) are ignored rather than rejected.
    """

    model_config = SettingsConfigDict(
        env_prefix="AGENTREPLAY_INGEST_", env_file=ENV_FILE, extra="ignore"
    )

    database_url: str = DEFAULT_DATABASE_URL
    environment: str = "development"

    # SQL echo is useful for local debugging, never in prod.
    sql_echo: bool = False

    database_ssl_mode: str = "require"

    cors_origins: str = "http://localhost:3000"

    # Celery + classifier (chunk 3.6, CLAUDE.md §3.6). `redis_url` doubles as
    # both Celery broker and result backend — one moving part, not two.
    redis_url: str = DEFAULT_REDIS_URL

    # "sonnet" (default, matches CLAUDE.md §3.6's "Sonnet + MAST taxonomy")
    # or "nim" (CLAUDE.md §5 NIM cost-cutting track, scoped to the classifier
    # only). Swappable purely via config — no code change, per that track's
    # own `CLASSIFIER_BACKEND=sonnet|nim` flag (N.2).
    classifier_backend: str = "sonnet"
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = DEFAULT_ANTHROPIC_MODEL
    nim_api_key: Optional[str] = None
    nim_base_url: str = DEFAULT_NIM_BASE_URL
    nim_model: str = DEFAULT_NIM_MODEL

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def classifier_configured(self) -> bool:
        """Whether enough config exists to actually call a model.

        `routers/spans.py` checks this before enqueueing a classification
        task — a missing key is a normal, expected local-dev state (no
        `ANTHROPIC_API_KEY` available yet, see PROGRESS.md Blockers), not an
        error worth crashing ingestion over.
        """
        if self.classifier_backend == "nim":
            return bool(self.nim_api_key)
        return bool(self.anthropic_api_key)


def get_settings() -> Settings:
    return Settings()
