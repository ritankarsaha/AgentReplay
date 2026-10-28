FROM python:3.11-slim AS base

WORKDIR /app

# Build deps only needed transiently for asyncpg/etc wheels on slim images.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Build context is the monorepo root (see fly.toml: dockerfile points here,
# context is repo root) — ingest/app/testgen.py imports agentreplay.testgen.*
# directly at runtime, so the SDK package has to ship in this image too, not
# just ingest/'s own code.
COPY pyproject.toml LICENSE NOTICE README.md ./
COPY agentreplay ./agentreplay
RUN pip install --no-cache-dir .

COPY ingest/pyproject.toml ./ingest/pyproject.toml
COPY ingest/app ./ingest/app
COPY ingest/migrations ./ingest/migrations
COPY ingest/alembic.ini ./ingest/alembic.ini
RUN pip install --no-cache-dir ./ingest

RUN useradd --create-home --uid 1000 appuser
USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
