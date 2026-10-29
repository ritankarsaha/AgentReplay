-- Mirror of versions/0008_incident_details.py (review copy). Additive and reversible.

ALTER TABLE incidents ADD COLUMN details JSONB NOT NULL DEFAULT '{}';
