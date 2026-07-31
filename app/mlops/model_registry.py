"""Hopsworks Model Registry integration."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib

from app.mlops.client import (
    HopsworksResources,
)
from app.mlops.config import (
    MLOpsSettings,
)


class ModelRegistryError(RuntimeError):
    """Raised when model-registry operations fail."""


@dataclass(frozen=True)
class RegisteredModelResult:
    """Registered model metadata."""

    name: str
    version: int
    status: str
    checksum_sha256: str
    model_directory: str

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe metadata."""

        return {
            "name": self.name,
            "version": self.version,
            "status": self.status,
            "checksum_sha256": (
                self.checksum_sha256
            ),
            "model_directory": (
                self.model_directory
            ),
        }


@dataclass(frozen=True)
class ResolvedProductionModel:
    """Explicitly resolved production model."""

    name: str
    version: int
    status: str
    downloaded_directory: Path
    model_artifact_path: Path
    feature_columns_path: Path
    metadata_path: Path
    checksum_sha256: str

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe metadata."""

        return {
            "name": self.name,
            "version": self.version,
            "status": self.status,
            "downloaded_directory": str(
                self.downloaded_directory
            ),
            "model_artifact_path": str(
                self.model_artifact_path
            ),
            "feature_columns_path": str(
                self.feature_columns_path
            ),
            "metadata_path": str(
                self.metadata_path
            ),
            "checksum_sha256": (
                self.checksum_sha256
            ),
        }


def calculate_sha256(
    path: Path,
) -> str:
    """Calculate a file SHA-256 checksum."""

    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(
            lambda: file.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def load_json_object(
    path: Path,
) -> dict[str, Any]:
    """Load a JSON object."""

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(payload, dict):
        raise ModelRegistryError(
            f"{path} must contain a JSON object."
        )

    return payload


def prepare_model_package(
    *,
    project_root: Path,
    settings: MLOpsSettings,
) -> tuple[Path, str]:
    """Prepare the approved local model for registration."""

    source_files = {
        "best_model.joblib": (
            project_root
            / "models"
            / "best_model.joblib"
        ),
        "model_feature_columns.json": (
            project_root
            / "models"
            / "model_feature_columns.json"
        ),
        "model_metadata.json": (
            project_root
            / "models"
            / "model_metadata.json"
        ),
        "model_selection_report.json": (
            project_root
            / "models"
            / "model_selection_report.json"
        ),
    }

    missing_files = [
        str(path)
        for path in source_files.values()
        if not path.exists()
    ]

    if missing_files:
        raise ModelRegistryError(
            "Missing approved model artifacts: "
            f"{missing_files}"
        )

    model_checksum = calculate_sha256(
        source_files["best_model.joblib"]
    )

    package_directory = (
        project_root
        / "models"
        / "registry_package"
        / (
            f"{settings.hopsworks_model_name}_"
            f"v{settings.hopsworks_initial_model_version}"
        )
    )

    if package_directory.exists():
        shutil.rmtree(
            package_directory
        )

    package_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    for filename, source_path in (
        source_files.items()
    ):
        shutil.copy2(
            source_path,
            package_directory / filename,
        )

    model_metadata = load_json_object(
        source_files["model_metadata.json"]
    )

    registry_metadata = {
        "model_name": (
            settings.hopsworks_model_name
        ),
        "requested_version": (
            settings.hopsworks_initial_model_version
        ),
        "model_status": "PRODUCTION",
        "artifact_checksum_sha256": (
            model_checksum
        ),
        "feature_view_name": (
            settings.hopsworks_feature_view_name
        ),
        "feature_view_version": (
            settings.hopsworks_feature_view_version
        ),
        "training_dataset_name": (
            settings.hopsworks_training_dataset_name
        ),
        "training_dataset_version": (
            settings
            .hopsworks_training_dataset_version
        ),
        "feature_pipeline_version": (
            settings.feature_pipeline_version
        ),
        "historical_weather_limitation": (
            "Observed target-hour historical weather "
            "was used as a proxy for forecast weather."
        ),
        "source_model_metadata": (
            model_metadata
        ),
    }

    (
        package_directory
        / "registry_metadata.json"
    ).write_text(
        json.dumps(
            registry_metadata,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    joblib.load(
        package_directory
        / "best_model.joblib"
    )

    return (
        package_directory,
        model_checksum,
    )


def register_initial_production_model(
    *,
    resources: HopsworksResources,
    settings: MLOpsSettings,
    package_directory: Path,
    checksum_sha256: str,
) -> RegisteredModelResult:
    """Register the approved model as initial champion."""

    if resources.model_registry is None:
        raise ModelRegistryError(
            "Hopsworks Model Registry was not resolved."
        )

    if settings.mlops_dry_run:
        return RegisteredModelResult(
            name=settings.hopsworks_model_name,
            version=(
                settings
                .hopsworks_initial_model_version
            ),
            status="PRODUCTION",
            checksum_sha256=checksum_sha256,
            model_directory=str(
                package_directory
            ),
        )

    try:
        model_metadata = load_json_object(
            package_directory
            / "model_metadata.json"
        )

        training_metrics = {}

        for metric_name in (
            "mae",
            "rmse",
            "r2",
        ):
            metric_value = (
                model_metadata.get(metric_name)
            )

            if isinstance(
                metric_value,
                int | float,
            ):
                training_metrics[
                    metric_name
                ] = float(metric_value)

        model = (
            resources.model_registry
            .python.create_model(
                name=(
                    settings.hopsworks_model_name
                ),
                description=(
                    "Approved Phase 3 PM2.5 "
                    "forecasting model registered "
                    "as the initial production champion."
                ),
                metrics=training_metrics,
            )
        )

        model.save(
            str(package_directory)
        )

        registered_version = int(
            model.version
        )

    except Exception as error:
        raise ModelRegistryError(
            "Could not register the approved model "
            "in Hopsworks Model Registry."
        ) from error

    return RegisteredModelResult(
        name=settings.hopsworks_model_name,
        version=registered_version,
        status="PRODUCTION",
        checksum_sha256=checksum_sha256,
        model_directory=str(
            package_directory
        ),
    )

def _replace_registry_cache(
    *,
    source_directory: Path,
    cache_directory: Path,
) -> Path:
    """
    Replace the project registry cache with a validated
    downloaded model bundle.
    """

    source_directory = source_directory.resolve()
    cache_directory = cache_directory.resolve()

    if source_directory == cache_directory:
        return cache_directory

    temporary_cache = (
        cache_directory.parent
        / f"{cache_directory.name}_incoming"
    )

    previous_cache = (
        cache_directory.parent
        / f"{cache_directory.name}_previous"
    )

    if temporary_cache.exists():
        shutil.rmtree(temporary_cache)

    if previous_cache.exists():
        shutil.rmtree(previous_cache)

    shutil.copytree(
        source_directory,
        temporary_cache,
    )

    if cache_directory.exists():
        cache_directory.rename(
            previous_cache
        )

    try:
        temporary_cache.rename(
            cache_directory
        )
    except Exception:
        if (
            previous_cache.exists()
            and not cache_directory.exists()
        ):
            previous_cache.rename(
                cache_directory
            )

        raise

    if previous_cache.exists():
        shutil.rmtree(previous_cache)

    return cache_directory


def resolve_production_model(
    *,
    resources: HopsworksResources,
    settings: MLOpsSettings,
    project_root: Path,
) -> ResolvedProductionModel:
    """Resolve an explicitly configured production version."""

    if resources.model_registry is None:
        raise ModelRegistryError(
            "Hopsworks Model Registry was not resolved."
        )

    production_version = (
        settings.hopsworks_production_model_version
    )

    cache_root = (
        project_root
        / settings.model_cache_directory
    ).resolve()

    try:
        model = resources.model_registry.get_model(
            name=settings.hopsworks_model_name,
            version=production_version,
        )

        if model is None:
            raise ModelRegistryError(
                "Configured production model "
                f"version {production_version} does not exist."
            )

        # Let Hopsworks use its own version-aware cache.
        hopsworks_download_path = Path(
            model.download()
        ).resolve()

    except ModelRegistryError:
        raise

    except Exception as error:
        raise ModelRegistryError(
            "Could not resolve or download the configured "
            f"production model. Cause: "
            f"{type(error).__name__}: {error}"
        ) from error

    model_path = (
        hopsworks_download_path
        / "best_model.joblib"
    )

    feature_columns_path = (
        hopsworks_download_path
        / "model_feature_columns.json"
    )

    model_metadata_path = (
        hopsworks_download_path
        / "model_metadata.json"
    )

    model_selection_report_path = (
        hopsworks_download_path
        / "model_selection_report.json"
    )

    registry_metadata_path = (
        hopsworks_download_path
        / "registry_metadata.json"
    )

    required_files = [
        model_path,
        feature_columns_path,
        model_metadata_path,
        model_selection_report_path,
        registry_metadata_path,
    ]

    missing_files = [
        str(path)
        for path in required_files
        if not path.exists()
    ]

    if missing_files:
        raise ModelRegistryError(
            "Downloaded production model is "
            f"missing files: {missing_files}"
        )

    registry_metadata = load_json_object(
        registry_metadata_path
    )

    expected_checksum = str(
        registry_metadata.get(
            "artifact_checksum_sha256",
            "",
        )
    )

    actual_checksum = calculate_sha256(
        model_path
    )

    if (
        not expected_checksum
        or actual_checksum != expected_checksum
    ):
        raise ModelRegistryError(
            "Downloaded model checksum does not "
            "match registry metadata."
        )

    model_status = str(
        registry_metadata.get(
            "model_status",
            "UNKNOWN",
        )
    )

    if model_status != "PRODUCTION":
        raise ModelRegistryError(
            "Downloaded registry model is not marked "
            "as PRODUCTION."
        )

    try:
        joblib.load(model_path)
    except Exception as error:
        raise ModelRegistryError(
            "Downloaded production model could not "
            "be loaded with joblib."
        ) from error

    # Only replace the project cache after validation succeeds.
    resolved_cache_directory = (
        _replace_registry_cache(
            source_directory=(
                hopsworks_download_path
            ),
            cache_directory=cache_root,
        )
    )

    return ResolvedProductionModel(
        name=settings.hopsworks_model_name,
        version=production_version,
        status=model_status,
        downloaded_directory=(
            resolved_cache_directory
        ),
        model_artifact_path=(
            resolved_cache_directory
            / "best_model.joblib"
        ),
        feature_columns_path=(
            resolved_cache_directory
            / "model_feature_columns.json"
        ),
        metadata_path=(
            resolved_cache_directory
            / "registry_metadata.json"
        ),
        checksum_sha256=actual_checksum,
    )