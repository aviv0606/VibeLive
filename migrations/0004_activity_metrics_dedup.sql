-- human_activity: make multi-value readings representable, and make ingestion
-- idempotent. This is the migration the whole pipeline depends on.
--
-- Problem 1 — one `value` column cannot hold one reading.
--   A single OpenWeather call returns temperature, humidity, wind speed and
--   cloud cover: four numbers, one category. Without `metric` you either throw
--   three of them away or you cannot tell them apart afterwards.
--
-- Problem 2 — no dedup key means silent data corruption.
--   Upstream feeds refresh on their own schedule (OpenWeather roughly every
--   10 minutes). Polling faster than that returns the *same observation*
--   again. Stored twice, it is counted as two independent samples, which
--   biases every average and every trend magnitude computed downstream. The
--   failure is invisible: no error, just quietly wrong conclusions.

ALTER TABLE human_activity
    ADD COLUMN metric      VARCHAR(40)  NOT NULL DEFAULT 'value',
    ADD COLUMN unit        VARCHAR(20),
    ADD COLUMN observed_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    ADD COLUMN dedup_key   TEXT;

COMMENT ON COLUMN human_activity.metric IS
    'Which quantity this row holds, e.g. temp_c, humidity_pct, congestion_ratio.';
COMMENT ON COLUMN human_activity.unit IS
    'Display unit for value, e.g. C, %, dB, ratio. The AI needs this to write a sentence.';
COMMENT ON COLUMN human_activity.observed_at IS
    'When the source observed it. Distinct from created_at (when we ingested it). '
    'All trend windows are computed on observed_at.';
COMMENT ON COLUMN human_activity.dedup_key IS
    'source:location:category:metric:observation_epoch. NULL opts a row out of '
    'dedup (simulated and backfilled rows).';

-- Partial, so rows that deliberately have no dedup_key never collide.
CREATE UNIQUE INDEX idx_human_activity_dedup
    ON human_activity (dedup_key) WHERE dedup_key IS NOT NULL;

-- Serves the trend query's exact access pattern.
CREATE INDEX idx_human_activity_trend
    ON human_activity (category_id, location_id, metric, observed_at DESC);
