from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app import models  # noqa: F401 — registers ORM models on Base.metadata
from app.config import get_settings
from app.db import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Always migrate against the configured app database, not alembic.ini's placeholder.
# `%` must be escaped as `%%` — ConfigParser (used internally by alembic.Config)
# treats `%` as interpolation syntax, and percent-encoded passwords (e.g. `%40`)
# would otherwise raise "invalid interpolation syntax".
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connect_args = {}
    settings = get_settings()
    if settings.database_url.startswith("postgresql+asyncpg"):
        if settings.database_ssl_mode != "disable":
            connect_args["ssl"] = "require"
        # See app/db.py make_engine() — required for the Supabase pooler
        # (pgbouncer, transaction mode); harmless against a direct connection.
        connect_args["statement_cache_size"] = 0

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
