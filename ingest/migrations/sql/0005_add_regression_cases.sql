CREATE TABLE regression_cases (
    id VARCHAR PRIMARY KEY,
    project_id VARCHAR NOT NULL,
    source_run_id VARCHAR,
    title VARCHAR NOT NULL,
    entrypoint VARCHAR NOT NULL,
    recorded_input JSONB,
    tool_spans JSONB NOT NULL DEFAULT '[]',
    assertion_spec JSONB,
    priority VARCHAR NOT NULL DEFAULT 'P1',
    status VARCHAR NOT NULL DEFAULT 'proposed',
    evidence_level VARCHAR NOT NULL DEFAULT 'native_structured',
    source_case_key VARCHAR,
    incident_id VARCHAR,
    external_url VARCHAR,
    observed_at TIMESTAMPTZ,
    created_by VARCHAR,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_regression_cases_project_id ON regression_cases (project_id);
CREATE INDEX ix_regression_cases_source_run_id ON regression_cases (source_run_id);

ALTER TABLE regression_cases ENABLE ROW LEVEL SECURITY;

CREATE TABLE test_results (
    id VARCHAR PRIMARY KEY,
    case_id VARCHAR NOT NULL REFERENCES regression_cases (id) ON DELETE CASCADE,
    agent_version VARCHAR,
    trials INTEGER NOT NULL,
    passes INTEGER NOT NULL,
    pass_rate FLOAT NOT NULL,
    verdict VARCHAR NOT NULL,
    details JSONB NOT NULL DEFAULT '[]',
    judged_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_test_results_case_id ON test_results (case_id);

ALTER TABLE test_results ENABLE ROW LEVEL SECURITY;
