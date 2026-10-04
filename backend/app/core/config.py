"""Application settings loaded from environment variables.

All secrets come from environment / .env files — never hard-coded here.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Top-level settings sourced from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),  # allow model_path field without namespace warning
    )

    # ── PostgreSQL ─────────────────────────────────────────────────────────────
    database_url: str = "postgresql+psycopg://parcel:change_me@postgis:5432/parcelai"
    postgres_user: str = "parcel"
    postgres_password: str = "change_me"
    postgres_db: str = "parcelai"

    # ── Redis / Celery ─────────────────────────────────────────────────────────
    redis_url: str = "redis://redis:6379/0"

    # ── Processing ─────────────────────────────────────────────────────────────
    default_crs: str = "EPSG:32643"
    data_dir: str = "/data"
    model_path: str = "/models/parcelai_v1.pt"
    mock_model: bool = True

    # ── Tile servers ───────────────────────────────────────────────────────────
    titiler_url: str = "http://titiler:8000"
    martin_url: str = "http://martin:3000"

    # ── API ────────────────────────────────────────────────────────────────────
    cors_origins: list[str] = ["http://localhost:5173"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors(cls, v: str | list[str]) -> list[str]:
        """Allow comma-separated string in env var."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    # ── Google Earth Engine (optional) ─────────────────────────────────────────
    enable_gee: bool = False
    gee_project: str = ""
    gee_service_account: str = ""
    gee_key_file: str = "/run/secrets/gee-key.json"
    gee_bbox_precision: int = 3

    # ── WebODM (optional) ──────────────────────────────────────────────────────
    webodm_url: str = ""
    webodm_token: str = ""


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
