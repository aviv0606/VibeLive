-- Categories
INSERT INTO categories (name, description) VALUES
('traffic', 'Traffic flow and congestion levels'),
('crowd', 'Crowd density and movement'),
('noise', 'Environmental noise levels'),
('weather', 'Weather conditions'),
('pollution', 'Air quality and pollution levels');

-- Activity sources
INSERT INTO activity_sources (name, description) VALUES
('google_places', 'Google Places API'),
('waze', 'Waze traffic API'),
('openweather', 'Weather API'),
('custom_sensor', 'Local sensor data');

-- Locations
INSERT INTO locations (name, lat, lng, radius_m, nearest_town) VALUES
('Main Square', 32.0500, 34.8550, 150, 'Yehud'),
('City Mall', 32.0480, 34.8600, 200, 'Yehud'),
('Train Station', 32.0450, 34.8500, 300, 'Yehud');

-- Prompts
INSERT INTO prompts (category_id, prompt_text) VALUES
(1, 'Analyze the last 30 minutes of traffic data and summarize the trend.'),
(2, 'Analyze crowd density changes and describe the current situation.'),
(3, 'Summarize noise level trends and identify anomalies.'),
(4, 'Provide a weather trend summary for the last hour.'),
(5, 'Analyze pollution levels and describe any significant changes.');
