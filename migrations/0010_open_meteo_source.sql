-- Open-Meteo becomes the live provider, and nothing simulated stays writable.
--
-- Why not OpenWeather, which 0002 seeded as the weather source: it requires an
-- account and an API key. Open-Meteo requires neither — no key, no signup,
-- ~10k calls/day — and serves both current weather and air quality. That is
-- the difference between a pipeline that runs tonight and one that runs after
-- someone finishes a signup flow. The openweather row stays as a drop-in
-- alternate for whenever a key exists; it is simply not active today.
--
-- The simulated_* sources are deactivated rather than deleted. 0009 created
-- them because crowd and noise have no free real source, and that is still
-- true — but the standing instruction for this build is that no number in this
-- database may be invented. An inactive source is honest documentation of what
-- was evaluated; an active one is an invitation for a worker to fill the gap
-- with something plausible. Those two categories stay empty and say so.

INSERT INTO activity_sources (name, description) VALUES
    ('open_meteo', 'Open-Meteo Forecast + Air Quality (no API key, CC-BY-4.0, non-commercial)')
ON CONFLICT (name) DO NOTHING;

UPDATE activity_sources SET is_active = TRUE  WHERE name = 'open_meteo';

-- No key configured, so nothing ingests from it. Flip back on with the key.
UPDATE activity_sources SET is_active = FALSE WHERE name = 'openweather';

-- No fake data: these must never be selected by an ingest worker.
UPDATE activity_sources SET is_active = FALSE WHERE is_simulated;

COMMENT ON COLUMN activity_sources.is_active IS
    'Ingest workers only ever write rows for active sources. Inactive rows are '
    'kept as a record of what was evaluated and why it was not used.';
