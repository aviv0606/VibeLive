"""Open-Meteo ingest: current weather and current air quality.

Chosen over OpenWeather because it needs no API key and no account, which is
the difference between a pipeline that runs tonight and one that runs after
someone finishes a signup flow. Free tier is roughly 10k calls/day, CC-BY-4.0,
non-commercial.

**All locations ship in one request.** Open-Meteo accepts comma-separated
coordinate lists and answers with an array in request order, so a cycle costs
one HTTP call regardless of how many locations are active. The array index is
the only reliable join back to the location — the payload's own `location_id`
field is an index into the request, and it is omitted entirely for the first
entry — so a length mismatch is treated as a hard error rather than being
zipped over.

**What this data honestly is.** Open-Meteo serves a weather *model* on a grid
of roughly 1-11 km, and the response echoes the grid point it snapped to. Three
locations a kilometre apart snap to the same cell and return byte-identical
numbers. Those rows are still real measurements, they are simply not
independent per-location observations, and the snapped coordinates go into
raw_json so that is auditable later rather than inferred.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from vibelive.config import get_settings
from vibelive.workers.base import Worker
from vibelive.workers.store import (
    Observation,
    active_source_id,
    category_id,
    active_locations,
    insert_observations,
)

logger = logging.getLogger(__name__)

SOURCE_NAME = "open_meteo"

# api field -> the metric name we store. Ours are short and unit-suffixed so a
# reading is self-describing in the explorer without a join.
WEATHER_METRICS = {
    "temperature_2m": "temp_c",
    "apparent_temperature": "feels_like_c",
    "relative_humidity_2m": "humidity_pct",
    "precipitation": "precip_mm",
    "cloud_cover": "cloud_pct",
    "wind_speed_10m": "wind_kmh",
    "wind_gusts_10m": "wind_gust_kmh",
    "surface_pressure": "pressure_hpa",
}

AIR_METRICS = {
    "european_aqi": "aqi_eu",
    "pm2_5": "pm2_5",
    "pm10": "pm10",
    "nitrogen_dioxide": "no2",
    "sulphur_dioxide": "so2",
    "ozone": "o3",
    "carbon_monoxide": "co",
}


class OpenMeteoWorker(Worker):
    """Shared shape of the two Open-Meteo pollers."""

    category_name: str = ""
    base_url: str = ""
    metrics: dict[str, str] = {}

    def __init__(self, interval_seconds: float) -> None:
        self.interval_seconds = interval_seconds
        self._client: httpx.AsyncClient | None = None

    async def setup(self) -> None:
        settings = get_settings()
        self._client = httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            headers={"User-Agent": settings.http_user_agent},
        )

    async def teardown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def run_once(self) -> str:
        source_id = await active_source_id(SOURCE_NAME)
        if source_id is None:
            return f"source {SOURCE_NAME} is inactive — nothing ingested"

        cat_id = await category_id(self.category_name)
        if cat_id is None:
            raise RuntimeError(f"category {self.category_name!r} missing from the database")

        locations = await active_locations()
        if not locations:
            return "no active locations — nothing to poll"

        entries = await self._fetch(locations)
        observations = self._to_observations(entries, locations, cat_id, source_id)
        inserted = await insert_observations(observations)

        skipped = len(observations) - inserted
        note = f", {skipped} already stored" if skipped else ""
        return (
            f"{len(locations)} locations, {len(observations)} readings, "
            f"{inserted} new{note}"
        )

    async def _fetch(self, locations: list[dict]) -> list[dict]:
        assert self._client is not None, "setup() was not called"

        params = {
            "latitude": ",".join(str(loc["lat"]) for loc in locations),
            "longitude": ",".join(str(loc["lng"]) for loc in locations),
            "current": ",".join(self.metrics),
            # Pinned: _observed_at below reads utc_offset_seconds to convert, so
            # this stays correct even if it changes, but there is no reason to.
            "timezone": "UTC",
        }
        response = await self._client.get(self.base_url, params=params)
        response.raise_for_status()
        payload = response.json()

        # One coordinate returns an object; many return an array.
        entries = payload if isinstance(payload, list) else [payload]
        if len(entries) != len(locations):
            raise RuntimeError(
                f"asked for {len(locations)} locations, got {len(entries)} back — "
                "refusing to guess which reading belongs to which location"
            )
        return entries

    def _to_observations(
        self,
        entries: list[dict],
        locations: list[dict],
        cat_id: int,
        source_id: int,
    ) -> list[Observation]:
        observations: list[Observation] = []

        for location, entry in zip(locations, entries):
            current = entry.get("current")
            if not current:
                raise RuntimeError(f"no `current` block for location {location['id']}")

            observed_at = _observed_at(entry, current)
            units = entry.get("current_units", {})

            for api_field, metric in self.metrics.items():
                value = current.get(api_field)
                if value is None:
                    # A field the model has no value for right now. Recording it
                    # as 0 would be an invented measurement.
                    logger.debug("%s: no %s for location %s", self.name, api_field, location["id"])
                    continue

                observations.append(
                    Observation(
                        location_id=location["id"],
                        category_id=cat_id,
                        source_id=source_id,
                        category_name=self.category_name,
                        source_name=SOURCE_NAME,
                        metric=metric,
                        unit=(units.get(api_field) or None),
                        value=float(value),
                        observed_at=observed_at,
                        raw={
                            "api_field": api_field,
                            "requested_lat": location["lat"],
                            "requested_lng": location["lng"],
                            # The grid point actually answered. Two locations
                            # sharing these are not independent observations.
                            "grid_lat": entry.get("latitude"),
                            "grid_lng": entry.get("longitude"),
                            "elevation_m": entry.get("elevation"),
                            "refresh_interval_s": current.get("interval"),
                        },
                    )
                )

        return observations


def _observed_at(entry: dict, current: dict) -> datetime:
    """Provider observation instant, as an aware UTC datetime.

    Open-Meteo returns a naive local timestamp plus the offset that makes it
    local. Converting via that offset rather than assuming UTC keeps the
    timestamp correct if the `timezone` parameter is ever changed — and
    observed_at is what every trend window is computed on, so a silently wrong
    one would corrupt analysis rather than error.
    """
    raw_time = current.get("time")
    if not raw_time:
        raise RuntimeError("payload has no current.time")

    naive = datetime.fromisoformat(raw_time)
    offset = int(entry.get("utc_offset_seconds") or 0)
    return naive.replace(tzinfo=timezone.utc) - timedelta(seconds=offset)


class WeatherWorker(OpenMeteoWorker):
    name = "open_meteo_weather"
    category_name = "weather"
    base_url = "https://api.open-meteo.com/v1/forecast"
    metrics = WEATHER_METRICS


class AirQualityWorker(OpenMeteoWorker):
    name = "open_meteo_pollution"
    category_name = "pollution"
    base_url = "https://air-quality-api.open-meteo.com/v1/air-quality"
    metrics = AIR_METRICS
