-- ============================
-- 1. categories
-- ============================
CREATE TABLE categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================
-- 2. locations
-- ============================
CREATE TABLE locations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(150),
    lat DOUBLE PRECISION NOT NULL,
    lng DOUBLE PRECISION NOT NULL,
    radius_m INTEGER DEFAULT 100,
    nearest_town VARCHAR(150),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_locations_lat_lng ON locations (lat, lng);

-- ============================
-- 3. activity_sources
-- ============================
CREATE TABLE activity_sources (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================
-- 4. human_activity (RAW DATA)
-- ============================
CREATE TABLE human_activity (
    id SERIAL PRIMARY KEY,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    source_id INTEGER REFERENCES activity_sources(id),
    value DOUBLE PRECISION,
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_human_activity_location_time
    ON human_activity (location_id, created_at);

CREATE INDEX idx_human_activity_category_time
    ON human_activity (category_id, created_at);

CREATE INDEX idx_human_activity_created_at
    ON human_activity (created_at);

-- ============================
-- 5. conclusions (AI OUTPUT)
-- ============================
CREATE TABLE conclusions (
    id SERIAL PRIMARY KEY,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    trend_direction VARCHAR(20),
    trend_magnitude DOUBLE PRECISION,
    window_minutes INTEGER,
    ai_text TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_conclusions_location_time
    ON conclusions (location_id, created_at);

-- ============================
-- 6. prompts (AI PROMPT TEMPLATES)
-- ============================
CREATE TABLE prompts (
    id SERIAL PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    prompt_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================
-- 7. events (GENERAL EVENTS)
-- ============================
CREATE TABLE events (
    id SERIAL PRIMARY KEY,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    category_id INTEGER REFERENCES categories(id),
    event_type VARCHAR(100),
    event_data JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================
-- 8. traffic_incidents (TRAFFIC-SPECIFIC EVENTS)
-- ============================
CREATE TABLE traffic_incidents (
    id SERIAL PRIMARY KEY,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    severity INTEGER,
    description TEXT,
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================
-- 9. worker_logs (WORKER DEBUGGING)
-- ============================
CREATE TABLE worker_logs (
    id SERIAL PRIMARY KEY,
    worker_name VARCHAR(100) NOT NULL,
    message TEXT,
    level VARCHAR(20),
    created_at TIMESTAMP DEFAULT NOW()
);
