-- Sources and locations: honesty flags and cost levers.
--
-- is_simulated is a correctness feature, not decoration. Crowd density and
-- noise have no free data source (Waze is partner-only; Google Places exposes
-- no popular-times endpoint), so those categories are synthetic. Three weeks
-- from now nobody will remember which numbers were real unless the database
-- says so — and simulated rows must never be narrated by the AI or used as a
-- baseline that real anomaly detection compares against.
--
-- is_active on locations is the single biggest cost lever in the system:
-- external API calls scale with active locations x active sources.

ALTER TABLE activity_sources
    ADD COLUMN is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN is_simulated BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN activity_sources.is_simulated IS
    'Data from this source is synthetic. Never narrated by the AI, never used '
    'as an anomaly baseline, always badged in the UI.';

INSERT INTO activity_sources (name, description) VALUES
    ('tomtom',          'TomTom Traffic API (flow segments + incidents)'),
    ('simulated_crowd', 'Synthetic crowd density — no free real source exists'),
    ('simulated_noise', 'Synthetic noise levels — no free real source exists')
ON CONFLICT (name) DO NOTHING;

UPDATE activity_sources SET is_simulated = TRUE  WHERE name LIKE 'simulated\_%';

-- Kept as rows rather than deleted: they are honest documentation of what was
-- evaluated, and harmless FK targets.
UPDATE activity_sources SET is_active = FALSE
 WHERE name IN ('waze', 'google_places');

COMMENT ON TABLE activity_sources IS
    'Ingestion sources. waze and google_places are inactive: Waze has no public '
    'API and Google Places has no official popular-times endpoint.';

ALTER TABLE locations
    ADD COLUMN is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN external_ids JSONB;

COMMENT ON COLUMN locations.external_ids IS
    'Per-provider identifiers for this location, e.g. {"tomtom_segment": "..."}.';

ALTER TABLE locations ADD CONSTRAINT locations_name_key UNIQUE (name);
