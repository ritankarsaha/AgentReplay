CREATE TABLE login_events (
    id VARCHAR PRIMARY KEY,
    project_id VARCHAR NOT NULL,
    email VARCHAR NOT NULL,
    name VARCHAR,
    image VARCHAR,
    provider VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_login_events_project_id ON login_events (project_id);
CREATE INDEX ix_login_events_created_at ON login_events (created_at);

ALTER TABLE login_events ENABLE ROW LEVEL SECURITY;
