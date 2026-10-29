-- Mirror of versions/0008_incident_details.py (review copy). Additive and reversible.

ALTER TABLE incidents ADD COLUMN details JSONB NOT NULL DEFAULT '{}';
ALTER TABLE incidents ADD COLUMN share_token VARCHAR;
CREATE UNIQUE INDEX ix_incidents_share_token ON incidents (share_token);

CREATE TABLE blobs (
    project_id VARCHAR NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    mime VARCHAR NOT NULL,
    size INTEGER NOT NULL,
    data BYTEA NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (project_id, sha256)
);
ALTER TABLE blobs ENABLE ROW LEVEL SECURITY;
