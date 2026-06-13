

CREATE TABLE projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    api_key     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ix_projects_api_key ON projects (api_key);

CREATE TABLE runs (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL,
    agent_version   TEXT,
    framework       TEXT,
    started_at      TIMESTAMPTZ NOT NULL,

    last_seen_at    TIMESTAMPTZ NOT NULL,
    status          TEXT NOT NULL DEFAULT 'ok',  -- ok | failure | divergence
    failure_class   TEXT,
    root_span_id    TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_runs_project_id ON runs (project_id);
CREATE INDEX ix_runs_started_at ON runs (started_at);

CREATE TABLE spans (
    id            TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    parent_id     TEXT,
    type          TEXT NOT NULL,  -- llm | tool | node | checkpoint
    name          TEXT NOT NULL,
    input         JSONB NOT NULL DEFAULT '{}'::jsonb,
    output        JSONB,
    error         JSONB,
    started_at    TIMESTAMPTZ NOT NULL,
    duration_ms   DOUBLE PRECISION NOT NULL,
    fingerprint   TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_spans_run_id ON spans (run_id);
CREATE INDEX ix_spans_parent_id ON spans (parent_id);
CREATE INDEX ix_spans_fingerprint ON spans (fingerprint);
