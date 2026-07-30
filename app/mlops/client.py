"""Isolated Hopsworks SDK connection adapter."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import (
    PackageNotFoundError,
    version,
)
from typing import Any

from app.mlops.config import (
    FeatureStoreBackend,
    MLOpsSettings,
    ModelRegistryBackend,
    get_mlops_settings,
)


class HopsworksConfigurationError(ValueError):
    """Raised when Hopsworks configuration is invalid."""


class HopsworksDependencyError(RuntimeError):
    """Raised when the Hopsworks SDK is unavailable."""


class HopsworksConnectionError(RuntimeError):
    """Raised when Hopsworks cannot be reached."""


@dataclass(frozen=True)
class HopsworksResources:
    """Resolved Hopsworks project resources."""

    project: Any
    feature_store: Any | None
    model_registry: Any | None
    sdk_version: str
    project_name: str
    feature_store_name: str | None


def get_hopsworks_sdk_version() -> str:
    """Return the installed Hopsworks SDK version."""

    try:
        return version("hopsworks")
    except PackageNotFoundError as error:
        raise HopsworksDependencyError(
            "The 'hopsworks' package is not installed. "
            "Install the SDK version matching your "
            "Hopsworks deployment."
        ) from error


def connect_to_hopsworks(
    settings: MLOpsSettings | None = None,
) -> HopsworksResources:
    """Connect and resolve configured Hopsworks resources."""

    resolved_settings = (
        settings
        or get_mlops_settings()
    )

    if not resolved_settings.uses_hopsworks:
        raise HopsworksConfigurationError(
            "Hopsworks connection was requested while "
            "both backends are configured as local."
        )

    if resolved_settings.hopsworks_api_key is None:
        raise HopsworksConfigurationError(
            "HOPSWORKS_API_KEY is required."
        )

    if not resolved_settings.hopsworks_project:
        raise HopsworksConfigurationError(
            "HOPSWORKS_PROJECT is required."
        )

    sdk_version = get_hopsworks_sdk_version()

    try:
        import hopsworks

        login_arguments: dict[str, object] = {
            "port": resolved_settings.hopsworks_port,
            "project": (
                resolved_settings.hopsworks_project
            ),
            "api_key_value": (
                resolved_settings
                .hopsworks_api_key
                .get_secret_value()
            ),
            "hostname_verification": (
                resolved_settings
                .hopsworks_hostname_verification
            ),
            "engine": resolved_settings.hopsworks_engine,
        }

        if resolved_settings.hopsworks_host:
            login_arguments["host"] = (
                resolved_settings.hopsworks_host
            )

        project = hopsworks.login(
            **login_arguments
        )

        feature_store = None
        model_registry = None

        if (
            resolved_settings.feature_store_backend
            == FeatureStoreBackend.HOPSWORKS
        ):
            feature_store = (
                project.get_feature_store()
            )

        if (
            resolved_settings.model_registry_backend
            == ModelRegistryBackend.HOPSWORKS
        ):
            model_registry = (
                project.get_model_registry()
            )

        project_name = str(
            getattr(
                project,
                "name",
                resolved_settings.hopsworks_project,
            )
        )

        feature_store_name = None

        if feature_store is not None:
            feature_store_name = str(
                getattr(
                    feature_store,
                    "name",
                    "",
                )
            ) or None

        return HopsworksResources(
            project=project,
            feature_store=feature_store,
            model_registry=model_registry,
            sdk_version=sdk_version,
            project_name=project_name,
            feature_store_name=feature_store_name,
        )

    except (
        HopsworksConfigurationError,
        HopsworksDependencyError,
    ):
        raise

    except Exception as error:
        raise HopsworksConnectionError(
            "Could not connect to Hopsworks or resolve "
            "the configured project resources."
        ) from error