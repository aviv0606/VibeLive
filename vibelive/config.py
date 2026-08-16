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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
