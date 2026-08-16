-- Baseline reference data.
--
-- Every insert is idempotent and keyed on a NATURAL key. The original
-- db/seeds.sql attached prompts to hardcoded category_id 1..5, which was only
-- correct because categories happened to be inserted in that order into an
-- empty table — re-seed in any other order and every prompt silently binds to
-- the wrong category. Here prompts join categories by name instead.

-- ============================
-- categories
-- ============================
INSERT INTO categories (name, description) VALUES
    ('traffic',   'Traffic flow and congestion levels'),
    ('crowd',     'Crowd density and movement'),
    ('noise',     'Environmental noise levels'),
    ('weather',   'Weather conditions'),
    ('pollution', 'Air quality and pollution levels')
ON CONFLICT (name) DO NOTHING;

-- ============================
-- activity_sources
-- ============================
INSERT INTO activity_sources (name, description) VALUES
    ('google_places', 'Google Places API'),
    ('waze',          'Waze traffic API'),
    ('openweather',   'Weather API'),
    ('custom_sensor', 'Local sensor data')
ON CONFLICT (name) DO NOTHING;

-- ============================
-- locations
-- ============================
INSERT INTO locations (name, lat, lng, radius_m, nearest_town)
SELECT v.name, v.lat, v.lng, v.radius_m, v.nearest_town
FROM (VALUES
    ('Main Square',   32.0500::double precision, 34.8550::double precision, 150, 'Yehud'),
    ('City Mall',     32.0480::double precision, 34.8600::double precision, 200, 'Yehud'),
    ('Train Station', 32.0450::double precision, 34.8500::double precision, 300, 'Yehud')
) AS v(name, lat, lng, radius_m, nearest_town)
WHERE NOT EXISTS (SELECT 1 FROM locations l WHERE l.name = v.name);

-- ============================
-- prompts  (joined to categories by name, never by hardcoded id)
-- ============================
INSERT INTO prompts (category_id, prompt_text)
SELECT c.id, v.prompt_text
FROM (VALUES
    ('traffic',   'Analyze the last 30 minutes of traffic data and summarize the trend.'),
    ('crowd',     'Analyze crowd density changes and describe the current situation.'),
    ('noise',     'Summarize noise level trends and identify anomalies.'),
    ('weather',   'Provide a weather trend summary for the last hour.'),
    ('pollution', 'Analyze pollution levels and describe any significant changes.')
) AS v(cat_name, prompt_text)
JOIN categories c ON c.name = v.cat_name
WHERE NOT EXISTS (
    SELECT 1 FROM prompts p WHERE p.category_id = c.id
);
