-- events / traffic_incidents: dedup and lifecycle.
--
-- An anomaly detector that runs every 10 minutes will re-detect the same spike
-- on every tick. Without a dedup key that produces an endless stream of
-- identical "events" and the table becomes noise. Incidents additionally need
-- a way to be *closed*: upstream feeds drop an incident when it clears rather
-- than telling you it ended, so last_seen_at is how we notice.

ALTER TABLE events
    ADD COLUMN severity    INTEGER,
    ADD COLUMN dedup_key   TEXT,
    ADD COLUMN started_at  TIMESTAMPTZ,
    ADD COLUMN resolved_at TIMESTAMPTZ,
    ADD COLUMN is_active   BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN events.dedup_key IS
    'location:category:metric:kind:time_bucket — makes a repeated detection of '
    'the same condition a no-op instead of a new row.';

CREATE UNIQUE INDEX idx_events_dedup
    ON events (dedup_key) WHERE dedup_key IS NOT NULL;

CREATE INDEX idx_events_location_time ON events (location_id, created_at DESC);
CREATE INDEX idx_events_active ON events (created_at DESC) WHERE is_active;

ALTER TABLE traffic_incidents
    ADD COLUMN external_id  TEXT,
    ADD COLUMN category_id  INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    ADD COLUMN last_seen_at TIMESTAMPTZ,
    ADD COLUMN is_active    BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN traffic_incidents.external_id IS
    'Upstream provider incident id. Dedups across polls.';
COMMENT ON COLUMN traffic_incidents.last_seen_at IS
    'Last poll in which the provider still reported this incident. Stale rows '
    'get is_active=false — providers drop cleared incidents silently.';

CREATE UNIQUE INDEX idx_traffic_incidents_external
    ON traffic_incidents (external_id) WHERE external_id IS NOT NULL;

CREATE INDEX idx_traffic_incidents_location_time
    ON traffic_incidents (location_id, created_at DESC);
