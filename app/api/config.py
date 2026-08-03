"""Environment-based configuration for the FastAPI service."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import (
    Field,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)

from app.core.config import PROJECT_ROOT


class APISettings(BaseSettings):
    """Configuration used by the Phase 7 API service."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="PEARLS_API_",
        case_sensitive=False,
        extra="ignore",
    )

    application_name: str = (
        "Pearls AQI Predictor API"
    )

    application_description: str = (
        "72-hour PM2.5-based AQI forecast for the "
        "Zafar Memon DHA reference location in Karachi."
    )

    application_version: str = "1.0.0"
    environment: str = "development"

    api_prefix: str = "/api/v1"

    host: str = "0.0.0.0"

    port: int = Field(
        default=8000,
        ge=1,
        le=65_535,
    )

    allowed_cors_origins: tuple[str, ...] = (
        "http://localhost:3000",
        "http://localhost:8501",
    )

    # Artifact source configuration.
    artifact_backend: Literal[
        "local",
        "azure_blob",
    ] = "local"

    artifact_type: str = "aqi"

    azure_storage_account: str | None = None

    azure_storage_container: str = "artifacts"

    phase_6_blob_cache_directory: Path = (
        PROJECT_ROOT
        / ".cache"
        / "api"
        / "aqi"
        / "latest"
    )

    # Existing local artifact location.
    phase_6_latest_directory: Path = (
        PROJECT_ROOT
        / "aqi"
        / "latest"
    )

    phase_6_forecast_filename: str = (
        "live_pm25_aqi_forecast.parquet"
    )

    phase_6_alert_episodes_filename: str = (
        "alert_episodes.json"
    )

    phase_6_summary_filename: str = (
        "aqi_forecast_summary.json"
    )

    phase_6_metadata_filename: str = (
        "aqi_metadata.json"
    )

    phase_6_validation_filename: str = (
        "phase_6_validation_report.json"
    )

    artifact_cache_seconds: int = Field(
        default=60,
        ge=0,
    )

    forecast_staleness_threshold_hours: float = Field(
        default=12.0,
        gt=0,
    )

    forecast_aging_threshold_hours: float = Field(
        default=6.0,
        gt=0,
    )

    log_level: str = "INFO"

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(
        cls,
        value: str,
    ) -> str:
        """Normalize the versioned API prefix."""

        normalized_value = value.strip()

        if not normalized_value.startswith("/"):
            normalized_value = (
                f"/{normalized_value}"
            )

        return normalized_value.rstrip("/")

    @field_validator("environment")
    @classmethod
    def normalize_environment(
        cls,
        value: str,
    ) -> str:
        """Normalize the environment name."""

        return value.strip().lower()

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(
        cls,
        value: str,
    ) -> str:
        """Normalize and validate the logging level."""

        normalized_value = value.strip().upper()

        allowed_levels = {
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }

        if normalized_value not in allowed_levels:
            raise ValueError(
                f"Unsupported log level: {value}"
            )

        return normalized_value

    @field_validator(
        "artifact_backend",
        mode="before",
    )
    @classmethod
    def normalize_artifact_backend(
        cls,
        value: object,
    ) -> str:
        """Normalize and validate the artifact backend."""

        normalized_value = str(
            value
        ).strip().lower()

        allowed_backends = {
            "local",
            "azure_blob",
        }

        if (
            normalized_value
            not in allowed_backends
        ):
            raise ValueError(
                "artifact_backend must be "
                "'local' or 'azure_blob'."
            )

        return normalized_value

    @field_validator(
        "artifact_type",
        mode="before",
    )
    @classmethod
    def normalize_artifact_type(
        cls,
        value: object,
    ) -> str:
        """Normalize the durable artifact type."""

        normalized_value = str(
            value
        ).strip().lower()

        if not normalized_value:
            raise ValueError(
                "artifact_type cannot be empty."
            )

        if (
            "/" in normalized_value
            or "\\" in normalized_value
        ):
            raise ValueError(
                "artifact_type must contain one "
                "path segment."
            )

        return normalized_value

    @field_validator(
        "azure_storage_account",
        mode="before",
    )
    @classmethod
    def normalize_storage_account(
        cls,
        value: object,
    ) -> str | None:
        """Normalize an optional Azure Storage account."""

        if value is None:
            return None

        normalized_value = str(
            value
        ).strip()

        return normalized_value or None

    @field_validator(
        "azure_storage_container",
        mode="before",
    )
    @classmethod
    def normalize_storage_container(
        cls,
        value: object,
    ) -> str:
        """Normalize the Azure Blob container name."""

        normalized_value = str(
            value
        ).strip()

        if not normalized_value:
            raise ValueError(
                "azure_storage_container "
                "cannot be empty."
            )

        return normalized_value

    @field_validator(
        "phase_6_latest_directory",
        mode="before",
    )
    @classmethod
    def resolve_phase_6_latest_directory(
        cls,
        value: object,
    ) -> Path:
        """
        Resolve the local Phase 6 artifact directory.

        Relative paths from the environment are interpreted
        relative to the project root rather than the current
        working directory.
        """

        path = Path(
            str(value)
        ).expanduser()

        if not path.is_absolute():
            path = PROJECT_ROOT / path

        return path.resolve()

    @field_validator(
        "phase_6_blob_cache_directory",
        mode="before",
    )
    @classmethod
    def resolve_blob_cache_directory(
        cls,
        value: object,
    ) -> Path:
        """Resolve the Blob materialization cache."""

        path = Path(
            str(value)
        ).expanduser()

        if not path.is_absolute():
            path = PROJECT_ROOT / path

        return path.resolve()

    @model_validator(mode="after")
    def validate_artifact_source(
        self,
    ) -> "APISettings":
        """Validate backend-specific configuration."""

        if (
            self.artifact_backend
            == "azure_blob"
            and not self.azure_storage_account
        ):
            raise ValueError(
                "azure_storage_account is required "
                "when artifact_backend=azure_blob."
            )

        return self

    @property
    def active_phase_6_directory(
        self,
    ) -> Path:
        """Return the directory used by the API repository."""

        if self.artifact_backend == "azure_blob":
            return self.phase_6_blob_cache_directory

        return self.phase_6_latest_directory

    @property
    def forecast_path(self) -> Path:
        """Return the active Phase 6 forecast path."""

        return (
            self.active_phase_6_directory
            / self.phase_6_forecast_filename
        )

    @property
    def alert_episodes_path(self) -> Path:
        """Return the active alert-episode artifact path."""

        return (
            self.active_phase_6_directory
            / self.phase_6_alert_episodes_filename
        )

    @property
    def summary_path(self) -> Path:
        """Return the active forecast-summary path."""

        return (
            self.active_phase_6_directory
            / self.phase_6_summary_filename
        )

    @property
    def metadata_path(self) -> Path:
        """Return the active AQI metadata path."""

        return (
            self.active_phase_6_directory
            / self.phase_6_metadata_filename
        )

    @property
    def validation_report_path(self) -> Path:
        """Return the active Phase 6 validation-report path."""

        return (
            self.active_phase_6_directory
            / self.phase_6_validation_filename
        )


@lru_cache(maxsize=1)
def get_api_settings() -> APISettings:
    """Return one cached settings instance."""

    return APISettings()