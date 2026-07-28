"""Environment-based configuration for the Streamlit dashboard."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


class DashboardSettings(BaseSettings):
    """Configuration used by the Streamlit dashboard."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    fastapi_base_url: str = (
        "http://localhost:8000/api/v1"
    )

    dashboard_request_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=60,
    )

    dashboard_cache_ttl_seconds: int = Field(
        default=60,
        ge=0,
        le=3_600,
    )

    dashboard_title: str = (
        "Pearls AQI Predictor"
    )

    dashboard_default_timezone: str = (
        "Asia/Karachi"
    )

    dashboard_environment: str = (
        "development"
    )

    @field_validator("fastapi_base_url")
    @classmethod
    def normalize_api_url(
        cls,
        value: str,
    ) -> str:
        """Remove whitespace and a trailing slash."""

        normalized = value.strip().rstrip("/")

        if not normalized.startswith(
            ("http://", "https://")
        ):
            raise ValueError(
                "FASTAPI_BASE_URL must start with "
                "http:// or https://"
            )

        return normalized

    @field_validator("dashboard_environment")
    @classmethod
    def normalize_environment(
        cls,
        value: str,
    ) -> str:
        """Normalize the environment label."""

        return value.strip().lower()


@lru_cache(maxsize=1)
def get_dashboard_settings() -> DashboardSettings:
    """Return one cached dashboard settings instance."""

    return DashboardSettings()