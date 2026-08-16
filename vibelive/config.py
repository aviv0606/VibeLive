"""Centralized settings. Every tunable lives here, sourced from env or .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- database ---
    database_url: str = "postgresql://vibelive:secret@localhost:5432/vibelive"
    api_pool_max: int = 5
    worker_pool_max: int = 3
    db_command_timeout: float = 10.0

    # --- api ---
    log_level: str = "INFO"
    cors_origins: str = "*"
    # The explorer exposes an arbitrary-SQL endpoint. Fine on localhost, an open
    # door on a public host — leave this false anywhere reachable from outside.
    enable_explorer: bool = True
    explorer_statement_timeout_ms: int = 5000

    # --- workers ---
    enabled_workers: str = "open_meteo_weather,open_meteo_pollution"
    # Open-Meteo refreshes weather roughly every 15 minutes and air quality
    # hourly. Polling faster than the source updates costs quota and returns
    # the same observation, which dedup_key then discards — so these intervals
    # are set to the provider's cadence, not to how often we would like data.
    weather_interval_seconds: int = 600
    pollution_interval_seconds: int = 1800
    worker_max_backoff_seconds: float = 900.0

    # --- http ---
    http_timeout_seconds: float = 20.0
    http_user_agent: str = "VibeLive/0.1 (self-hosted urban activity monitor)"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def enabled_worker_list(self) -> list[str]:
        return [w.strip() for w in self.enabled_workers.split(",") if w.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
