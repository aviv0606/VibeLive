-- conclusions: record where a conclusion came from, and what it cost.
--
-- Provenance columns let you reconstruct why a conclusion says what it says.
-- The AI telemetry columns exist because the project's stated constraint is
-- "AI spend near zero" — without recorded tokens and cost there is no way to
-- verify that claim, only to hope.

ALTER TABLE conclusions
    ADD COLUMN metric            VARCHAR(40),
    ADD COLUMN window_start      TIMESTAMPTZ,
    ADD COLUMN window_end        TIMESTAMPTZ,
    ADD COLUMN sample_count      INTEGER,
    ADD COLUMN avg_value         DOUBLE PRECISION,
    ADD COLUMN prev_avg_value    DOUBLE PRECISION,
    ADD COLUMN data_hash         TEXT,
    ADD COLUMN prompt_id         INTEGER REFERENCES prompts(id) ON DELETE SET NULL,
    ADD COLUMN ai_provider       VARCHAR(30),
    ADD COLUMN ai_model          VARCHAR(60),
    ADD COLUMN ai_input_tokens   INTEGER,
    ADD COLUMN ai_output_tokens  INTEGER,
    ADD COLUMN ai_cost_usd       NUMERIC(10, 6),
    ADD COLUMN ai_skipped_reason TEXT;

COMMENT ON COLUMN conclusions.trend_magnitude IS
    'Unitless fraction: (cur_avg - prev_avg) / abs(prev_avg). 0.29 means +29%. '
    'Multiply by 100 for display.';
COMMENT ON COLUMN conclusions.data_hash IS
    'Fingerprint of the aggregate. Unchanged hash + small delta => skip the AI '
    'call and carry the previous ai_text forward.';
COMMENT ON COLUMN conclusions.ai_skipped_reason IS
    'Why no AI call was made for this row: no_material_change, cooldown, '
    'budget_exceeded, simulated_source, insufficient_samples.';

-- Re-running the trend worker over the same window must be a no-op, not a
-- duplicate row.
CREATE UNIQUE INDEX idx_conclusions_window
    ON conclusions (location_id, category_id, metric, window_minutes, window_end);

CREATE INDEX idx_conclusions_pending_ai
    ON conclusions (created_at DESC) WHERE ai_text IS NULL;
