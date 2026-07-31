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

class ModelLoadingMode(StrEnum):
    """Supported inference model sources."""

    LOCAL_ARTIFACT = "LOCAL_ARTIFACT"
    HOPSWORKS_REGISTRY = "HOPSWORKS_REGISTRY"

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

    hopsworks_pm25_feature_group_name: str = (
    "pm25_hourly_observations"
    )

    hopsworks_weather_feature_group_name: str = (
        "weather_hourly_observations"
    )

    hopsworks_engineered_feature_group_name: str = (
        "pm25_hourly_features"
    )

    feature_pipeline_version: str = "phase_2_v1"
    source_data_version: str = "phase_1_v1"

    phase_1_canonical_dataset_path: str = (
    "data/processed/canonical_hourly_dataset.parquet"
    )

    phase_2_training_dataset_path: str = (
        "data/training/feature_dataset_full.parquet"
    )

    hopsworks_feature_view_name: str = (
    "pm25_reference_features"
    )

    hopsworks_training_dataset_name: str = (
        "pm25_72h_training_dataset"
    )

    hopsworks_training_dataset_version: int = Field(
        default=1,
        ge=1,
    )

    training_dataset_float_tolerance: float = Field(
        default=1e-8,
        gt=0,
    )

    hopsworks_pm25_feature_group_version: int = Field(
    default=1,
    ge=1,
    )

    hopsworks_weather_feature_group_version: int = Field(
        default=1,
        ge=1,
    )

    hopsworks_engineered_feature_group_version: int = Field(
        default=2,
        ge=1,
    )

    hopsworks_initial_model_version: int = Field(
        default=1,
        ge=1,
    )

    hopsworks_production_model_version: int = Field(
        default=1,
        ge=1,
    )

    model_loading_mode: ModelLoadingMode = (
        ModelLoadingMode.LOCAL_ARTIFACT
    )

    allow_cached_registry_fallback: bool = True
    allow_local_model_fallback: bool = True

    model_cache_directory: str = (
        "models/registry_cache"
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
            "pm25_feature_group_name": (
                self.hopsworks_pm25_feature_group_name
            ),
            "weather_feature_group_name": (
                self.hopsworks_weather_feature_group_name
            ),
            "engineered_feature_group_name": (
                self.hopsworks_engineered_feature_group_name
            ),
            "feature_pipeline_version": (
                self.feature_pipeline_version
            ),
            "source_data_version": (
                self.source_data_version
            ),

            "phase_1_canonical_dataset_path": (
                self.phase_1_canonical_dataset_path
            ),
            "phase_2_training_dataset_path": (
                self.phase_2_training_dataset_path
            ),

            "feature_view_name": (
                self.hopsworks_feature_view_name
            ),
            "training_dataset_name": (
                self.hopsworks_training_dataset_name
            ),
            "training_dataset_version": (
                self.hopsworks_training_dataset_version
            ),
            "training_dataset_float_tolerance": (
                self.training_dataset_float_tolerance
            ),

            "pm25_feature_group_version": (
                self.hopsworks_pm25_feature_group_version
            ),
            "weather_feature_group_version": (
                self.hopsworks_weather_feature_group_version
            ),
            "engineered_feature_group_version": (
                self.hopsworks_engineered_feature_group_version
            ),

            "initial_model_version": (
                self.hopsworks_initial_model_version
            ),
            "production_model_version": (
                self.hopsworks_production_model_version
            ),
            "model_cache_directory": (
                self.model_cache_directory
            ),

            "model_loading_mode": (
                self.model_loading_mode.value
            ),
            "allow_cached_registry_fallback": (
                self.allow_cached_registry_fallback
            ),
            "allow_local_model_fallback": (
                self.allow_local_model_fallback
            ),
        }


@lru_cache(maxsize=1)
def get_mlops_settings() -> MLOpsSettings:
    """Load and cache the MLOps settings."""

    return MLOpsSettings()