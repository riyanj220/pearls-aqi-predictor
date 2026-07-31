"""Resolve local or Hopsworks production-model artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.mlops.client import (
    HopsworksConnectionError,
    connect_to_hopsworks,
)
from app.mlops.config import (
    MLOpsSettings,
    ModelLoadingMode,
)
from app.mlops.model_registry import (
    ModelRegistryError,
    calculate_sha256,
    resolve_production_model,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ModelSourceError(RuntimeError):
    """Raised when no validated model source is available."""


@dataclass(frozen=True)
class ModelArtifactPaths:
    """Paths and lineage for one validated model source."""

    model_path: Path
    feature_columns_path: Path
    model_metadata_path: Path
    model_selection_report_path: Path
    registry_metadata_path: Path | None
    source: str
    model_name: str
    model_version: int | None
    checksum_sha256: str
    fallback_used: bool
    fallback_reason: str | None

    def safe_summary(self) -> dict[str, Any]:
        """Return model-source metadata without credentials."""

        return {
            "source": self.source,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "checksum_sha256": self.checksum_sha256,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "model_path": str(self.model_path),
            "feature_columns_path": str(
                self.feature_columns_path
            ),
            "model_metadata_path": str(
                self.model_metadata_path
            ),
             "model_selection_report_path": str(
                self.model_selection_report_path
            ),
        }


def _load_json_object(
    path: Path,
) -> dict[str, Any]:
    """Load and validate one JSON object."""

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(payload, dict):
        raise ModelSourceError(
            f"{path} must contain a JSON object."
        )

    return payload


def _require_files(
    paths: list[Path],
) -> None:
    """Require all expected model files."""

    missing = [
        str(path)
        for path in paths
        if not path.exists()
    ]

    if missing:
        raise ModelSourceError(
            f"Required model files are missing: {missing}"
        )


def resolve_local_artifacts(
    *,
    fallback_used: bool = False,
    fallback_reason: str | None = None,
) -> ModelArtifactPaths:
    """Resolve the existing local Phase 3 model."""

    model_path = (
        PROJECT_ROOT
        / "models"
        / "best_model.joblib"
    )

    feature_columns_path = (
        PROJECT_ROOT
        / "models"
        / "model_feature_columns.json"
    )

    metadata_path = (
        PROJECT_ROOT
        / "models"
        / "model_metadata.json"
    )

    model_selection_report_path = (
        PROJECT_ROOT
        / "models"
        / "model_selection_report.json"
    )

    _require_files(
        [
            model_path,
            feature_columns_path,
            metadata_path,
            model_selection_report_path,
        ]
    )

    return ModelArtifactPaths(
        model_path=model_path,
        feature_columns_path=(
            feature_columns_path
        ),
        model_metadata_path=metadata_path,
        model_selection_report_path=model_selection_report_path,
        registry_metadata_path=None,
        source="LOCAL_ARTIFACT",
        model_name="local_phase_3_model",
        model_version=None,
        checksum_sha256=calculate_sha256(
            model_path
        ),
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
    )


def resolve_cached_registry_artifacts(
    *,
    settings: MLOpsSettings,
    fallback_reason: str,
) -> ModelArtifactPaths:
    """Resolve the last validated registry cache."""

    cache_directory = (
        PROJECT_ROOT
        / settings.model_cache_directory
    )

    model_path = (
        cache_directory
        / "best_model.joblib"
    )

    feature_columns_path = (
        cache_directory
        / "model_feature_columns.json"
    )

    model_metadata_path = (
        cache_directory
        / "model_metadata.json"
    )

    registry_metadata_path = (
        cache_directory
        / "registry_metadata.json"
    )

    model_selection_report_path = (
        cache_directory
        / "model_selection_report.json"
    )

    _require_files(
        [
            model_path,
            feature_columns_path,
            model_metadata_path,
            registry_metadata_path,
            model_selection_report_path,
        ]
    )

    registry_metadata = _load_json_object(
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
        raise ModelSourceError(
            "Cached registry model checksum is invalid."
        )

    if (
        registry_metadata.get("model_status")
        != "PRODUCTION"
    ):
        raise ModelSourceError(
            "Cached registry model is not marked "
            "as PRODUCTION."
        )

    return ModelArtifactPaths(
        model_path=model_path,
        feature_columns_path=(
            feature_columns_path
        ),
        model_metadata_path=(
            model_metadata_path
        ),
        registry_metadata_path=(
            registry_metadata_path
        ),
        model_selection_report_path=(
            model_selection_report_path
        ),
        source="HOPSWORKS_REGISTRY_CACHE",
        model_name=settings.hopsworks_model_name,
        model_version=(
            settings.hopsworks_production_model_version
        ),
        checksum_sha256=actual_checksum,
        fallback_used=True,
        fallback_reason=fallback_reason,
    )


def resolve_registry_artifacts(
    *,
    settings: MLOpsSettings,
) -> ModelArtifactPaths:
    """Resolve the explicitly promoted registry model."""

    resources = connect_to_hopsworks(
        settings
    )

    resolved = resolve_production_model(
        resources=resources,
        settings=settings,
        project_root=PROJECT_ROOT,
    )

    model_metadata_path = (
        resolved.downloaded_directory
        / "model_metadata.json"
    )

    model_selection_report_path = (
        resolved.downloaded_directory
        / "model_selection_report.json"
    )

    _require_files(
        [
            resolved.model_artifact_path,
            resolved.feature_columns_path,
            model_metadata_path,
            model_selection_report_path,
            resolved.metadata_path,
        ]
    )

    if resolved.status != "PRODUCTION":
        raise ModelSourceError(
            "Resolved registry model is not marked "
            "as PRODUCTION."
        )

    return ModelArtifactPaths(
        model_path=resolved.model_artifact_path,
        feature_columns_path=(
            resolved.feature_columns_path
        ),
        model_metadata_path=(
            model_metadata_path
        ),
        model_selection_report_path=(
            model_selection_report_path
        ),
        registry_metadata_path=(
            resolved.metadata_path
        ),
        source="HOPSWORKS_REGISTRY",
        model_name=resolved.name,
        model_version=resolved.version,
        checksum_sha256=(
            resolved.checksum_sha256
        ),
        fallback_used=False,
        fallback_reason=None,
    )


def resolve_model_artifact_paths(
    *,
    settings: MLOpsSettings,
) -> ModelArtifactPaths:
    """Resolve the configured model with safe fallbacks."""

    if (
        settings.model_loading_mode
        == ModelLoadingMode.LOCAL_ARTIFACT
    ):
        return resolve_local_artifacts()

    registry_error: Exception | None = None

    try:
        return resolve_registry_artifacts(
            settings=settings
        )

    except (
        HopsworksConnectionError,
        ModelRegistryError,
        ModelSourceError,
    ) as error:
        registry_error = error

    fallback_reason = (
        f"{type(registry_error).__name__}: "
        f"{registry_error}"
    )

    if settings.allow_cached_registry_fallback:
        try:
            return resolve_cached_registry_artifacts(
                settings=settings,
                fallback_reason=fallback_reason,
            )
        except ModelSourceError:
            pass

    if settings.allow_local_model_fallback:
        return resolve_local_artifacts(
            fallback_used=True,
            fallback_reason=fallback_reason,
        )

    raise ModelSourceError(
        "The Hopsworks production model could not be "
        "resolved and all configured fallbacks failed."
    ) from registry_error