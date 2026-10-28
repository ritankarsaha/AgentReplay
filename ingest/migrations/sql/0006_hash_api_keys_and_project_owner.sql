-- Mirror of versions/0006_hash_api_keys_and_project_owner.py (review copy).
-- Irreversible with data intact: the plaintext projects.api_key is dropped.

ALTER TABLE projects ADD COLUMN api_key_hash VARCHAR;
ALTER TABLE projects ADD COLUMN api_key_prefix VARCHAR;
ALTER TABLE projects ADD COLUMN owner_email VARCHAR;

UPDATE projects
SET api_key_hash = encode(sha256(convert_to(api_key, 'UTF8')), 'hex'),
    api_key_prefix = left(api_key, 11);

ALTER TABLE projects ALTER COLUMN api_key_hash SET NOT NULL;
CREATE UNIQUE INDEX ix_projects_api_key_hash ON projects (api_key_hash);
CREATE INDEX ix_projects_owner_email ON projects (owner_email);

DROP INDEX ix_projects_api_key;
ALTER TABLE projects DROP COLUMN api_key;
