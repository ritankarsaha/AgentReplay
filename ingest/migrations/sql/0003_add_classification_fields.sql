ALTER TABLE runs ADD COLUMN classification_status VARCHAR NOT NULL DEFAULT 'none';
ALTER TABLE runs ADD COLUMN diagnosis JSONB;
