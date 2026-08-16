-- ai_calls: every AI request, including the ones that failed.
--
-- conclusions.ai_* records the calls that produced a conclusion. This table
-- records *attempts* — errors, timeouts, and rate-limit rejections included —
-- which is what a budget ceiling has to be enforced against. It is the single
-- source of truth for month-to-date spend.

CREATE TABLE ai_calls (
    id            SERIAL PRIMARY KEY,
    provider      VARCHAR(30)   NOT NULL,
    model         VARCHAR(60),
    purpose       VARCHAR(40),
    prompt_id     INTEGER REFERENCES prompts(id)    ON DELETE SET NULL,
    location_id   INTEGER REFERENCES locations(id)  ON DELETE SET NULL,
    category_id   INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      NUMERIC(10, 6) NOT NULL DEFAULT 0,
    latency_ms    INTEGER,
    ok            BOOLEAN        NOT NULL DEFAULT TRUE,
    error         TEXT,
    created_at    TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE ai_calls IS
    'Attempt log for the AI layer. Month-to-date sum(cost_usd) is what the '
    'budget gate reads before allowing another call.';

CREATE INDEX idx_ai_calls_created_at ON ai_calls (created_at DESC);

-- worker_logs is written by every worker and read by the ops endpoint and the
-- retention job; both filter on time.
CREATE INDEX idx_worker_logs_created_at ON worker_logs (created_at DESC);
CREATE INDEX idx_worker_logs_worker_time ON worker_logs (worker_name, created_at DESC);
