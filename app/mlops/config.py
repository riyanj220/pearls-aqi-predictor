"""Configuration for local and Hopsworks MLOps backends."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import (
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


class FeatureStoreBackend(StrEnum):
    """Supported feature-store backends."""

    LOCAL = "local"
    HOPSWORKS = "hopsworks"


class ModelRegistryBackend(StrEnum):
    """Supported model-registry backends."""

    LOCAL = "local"
    HOPSWORKS = "hopsworks"


class MLOpsSettings(BaseSettings):
    """Environment-driven Phase 9 configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    feature_store_backend: FeatureStoreBackend = (
        FeatureStoreBackend.LOCAL
    )

    model_registry_backend: ModelRegistryBackend = (
        ModelRegistryBackend.LOCAL
    )

    mlops_dry_run: bool = True

    hopsworks_api_key: SecretStr | None = None
    hopsworks_project: str | None = None
    hopsworks_host: str | None = None
    hopsworks_port: int = Field(
        default=443,
        ge=1,
        le=65535,
    )

    hopsworks_engine: str = "python"
    hopsworks_hostname_verification: bool = True

    hopsworks_feature_group_version: int = Field(
        default=1,
        ge=1,
    )

    hopsworks_feature_view_version: int = Field(
        default=1,
        ge=1,
    )

    hopsworks_model_name: str = (
        "pearls_aqi_pm25_forecaster"
    )

    @field_validator(
        "hopsworks_project",
        "hopsworks_host",
        "hopsworks_model_name",
        mode="before",
    )
    @classmethod
    def normalize_optional_strings(
        cls,
        value: object,
    ) -> object:
        """Strip configured string values."""

        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None

        return value

    @field_validator("hopsworks_engine")
    @classmethod
    def validate_engine(
        cls,
        value: str,
    ) -> str:
        """Keep the local integration on the Python engine."""

        normalized = value.strip().lower()

        if normalized != "python":
            raise ValueError(
                "HOPSWORKS_ENGINE must be 'python' "
                "for this local project."
            )

        return normalized

    @model_validator(mode="after")
    def validate_backend_credentials(
        self,
    ) -> "MLOpsSettings":
        """Require credentials only when Hopsworks is enabled."""

        hopsworks_required = any(
            (
                self.feature_store_backend
                == FeatureStoreBackend.HOPSWORKS,
                self.model_registry_backend
                == ModelRegistryBackend.HOPSWORKS,
            )
        )

        if not hopsworks_required:
            return self

        missing_fields: list[str] = []

        if self.hopsworks_api_key is None:
            missing_fields.append(
                "HOPSWORKS_API_KEY"
            )

        if not self.hopsworks_project:
            missing_fields.append(
                "HOPSWORKS_PROJECT"
            )

        if missing_fields:
            raise ValueError(
                "Missing required Hopsworks configuration: "
                + ", ".join(missing_fields)
            )

        return self

    @property
    def uses_hopsworks(self) -> bool:
        """Return whether either remote backend is enabled."""

        return any(
            (
                self.feature_store_backend
                == FeatureStoreBackend.HOPSWORKS,
                self.model_registry_backend
                == ModelRegistryBackend.HOPSWORKS,
            )
        )

    def safe_summary(self) -> dict[str, object]:
        """Return configuration without exposing credentials."""

        return {
            "feature_store_backend": (
                self.feature_store_backend.value
            ),
            "model_registry_backend": (
                self.model_registry_backend.value
            ),
            "dry_run": self.mlops_dry_run,
            "hopsworks_project": self.hopsworks_project,
            "hopsworks_host": (
                self.hopsworks_host
                or "Hopsworks Serverless/default"
            ),
            "hopsworks_port": self.hopsworks_port,
            "hopsworks_engine": self.hopsworks_engine,
            "hostname_verification": (
                self.hopsworks_hostname_verification
            ),
            "feature_group_version": (
                self.hopsworks_feature_group_version
            ),
            "feature_view_version": (
                self.hopsworks_feature_view_version
            ),
            "model_name": self.hopsworks_model_name,
            "api_key_configured": (
                self.hopsworks_api_key is not None
            ),
        }


@lru_cache(maxsize=1)
def get_mlops_settings() -> MLOpsSettings:
    """Load and cache the MLOps settings."""

    return MLOpsSettings()