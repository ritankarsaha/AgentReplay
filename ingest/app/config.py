from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATABASE_URL = "postgresql+asyncpg://agentreplay:agentreplay@localhost:5432/agentreplay"

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

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


def get_settings() -> Settings:
    return Settings()
