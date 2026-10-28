-- Mirror of versions/0007_control_plane_tables.py (review copy).
-- Additive and reversible. New span types / the `halted` run status need no DDL.

CREATE TABLE agents (
    id VARCHAR PRIMARY KEY,
    project_id VARCHAR NOT NULL,
    owner_id VARCHAR,
    name VARCHAR NOT NULL,
    public_key VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ix_agents_project_id ON agents (project_id);

CREATE TABLE scope_manifests (
    id VARCHAR PRIMARY KEY,
    agent_id VARCHAR NOT NULL REFERENCES agents (id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    manifest JSONB NOT NULL,
    signature VARCHAR NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);
CREATE INDEX ix_scope_manifests_agent_id ON scope_manifests (agent_id);

CREATE TABLE access_tokens (
    id VARCHAR PRIMARY KEY,
    agent_id VARCHAR NOT NULL REFERENCES agents (id) ON DELETE CASCADE,
    connector VARCHAR NOT NULL,
    scopes JSONB NOT NULL DEFAULT '[]',
    issued_at TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);
CREATE INDEX ix_access_tokens_agent_id ON access_tokens (agent_id);

CREATE TABLE trust_scores (
    id VARCHAR PRIMARY KEY,
    agent_id VARCHAR NOT NULL REFERENCES agents (id) ON DELETE CASCADE,
    score INTEGER NOT NULL,
    band VARCHAR NOT NULL,
    components JSONB NOT NULL DEFAULT '{}',
    computed_at TIMESTAMPTZ DEFAULT now(),
    trigger_run_id VARCHAR
);
CREATE INDEX ix_trust_scores_agent_id ON trust_scores (agent_id);
CREATE INDEX ix_trust_scores_computed_at ON trust_scores (computed_at);

CREATE TABLE incidents (
    id VARCHAR PRIMARY KEY,
    project_id VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    agent_id VARCHAR REFERENCES agents (id) ON DELETE SET NULL,
    kind VARCHAR NOT NULL,
    severity VARCHAR NOT NULL DEFAULT 'high',
    culprit_span_id VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ix_incidents_project_id ON incidents (project_id);
CREATE INDEX ix_incidents_run_id ON incidents (run_id);
CREATE INDEX ix_incidents_agent_id ON incidents (agent_id);

CREATE TABLE filings (
    id VARCHAR PRIMARY KEY,
    incident_id VARCHAR NOT NULL REFERENCES incidents (id) ON DELETE CASCADE,
    type VARCHAR NOT NULL,
    packet JSONB NOT NULL,
    trace_hash VARCHAR NOT NULL,
    simulated BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ix_filings_incident_id ON filings (incident_id);

CREATE TABLE model_runs (
    id VARCHAR PRIMARY KEY,
    project_id VARCHAR NOT NULL,
    source_run_id VARCHAR NOT NULL,
    span_id VARCHAR NOT NULL,
    model VARCHAR NOT NULL,
    output JSONB,
    verdict VARCHAR,
    cost_usd DOUBLE PRECISION,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ix_model_runs_project_id ON model_runs (project_id);
CREATE INDEX ix_model_runs_source_run_id ON model_runs (source_run_id);

ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE scope_manifests ENABLE ROW LEVEL SECURITY;
ALTER TABLE access_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE trust_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE incidents ENABLE ROW LEVEL SECURITY;
ALTER TABLE filings ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_runs ENABLE ROW LEVEL SECURITY;
