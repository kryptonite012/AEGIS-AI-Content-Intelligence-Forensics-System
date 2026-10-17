"""Runtime configuration from environment variables (see .env.example)."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Mode(StrEnum):
    DEMO = "demo"
    RESEARCH = "research"
    CONNECTED_PRODUCTION = "connected-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AEGIS_", env_file=".env", extra="ignore")

    mode: Mode = Mode.DEMO
    environment: str = "development"  # development | test | production
    secret_key: str = Field(default="dev-only-insecure-secret-change-me-0123456789", min_length=32)
    database_url: str = "postgresql+psycopg://aegis:aegis-dev-only@localhost:5432/aegis"
    redis_url: str = "redis://localhost:6379/0"
    task_mode: str = "celery"  # celery | inline (inline: background thread, development/tests only)

    storage_backend: str = "local"  # local | s3
    storage_root: Path = Path("var/evidence")
    s3_bucket: str = "aegis-evidence"
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_object_lock: bool = False

    cors_origins: str = "http://localhost:3000"  # comma-separated
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    cookie_secure: bool = False

    max_upload_mb: int = 512
    max_text_upload_mb: int = 25
    upload_chunk_mb: int = 8
    require_malware_scan: bool = False
    clamav_host: str | None = None
    clamav_port: int = 3310

    login_rate_limit_per_minute: int = 10
    upload_rate_limit_per_hour: int = 120
    api_rate_limit_per_minute: int = 600

    allow_external_processing: bool = False  # deployment-wide kill switch for external providers

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def check_production_safety(self) -> list[str]:
        problems = []
        if self.is_production:
            if self.secret_key.startswith("dev-only"):
                problems.append("AEGIS_SECRET_KEY must be set to a strong random value in production")
            if self.task_mode == "inline":
                problems.append("AEGIS_TASK_MODE=inline is not permitted in production")
            if not self.cookie_secure:
                problems.append("AEGIS_COOKIE_SECURE must be true in production")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
