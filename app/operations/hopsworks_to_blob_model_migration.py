"""Seed and validate the approved production model in Azure Blob."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib

from app.core.config import PROJECT_ROOT
from app.mlops.azure_blob_model_repository import (
    AzureBlobModelRepository,
)
from app.mlops.config import (
    MLOpsSettings,
    ModelRegistryBackend,
    get_mlops_settings,
)
from app.mlops.model_registry import (
    calculate_sha256,
    load_json_object,
)
from app.inference.model_source import (
    ModelArtifactPaths
)


REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "hopsworks_to_blob_model_migration_report.json"
)


class ModelMigrationError(
    RuntimeError
):
    """Raised when production model migration fails."""


def build_blob_settings(
    settings: MLOpsSettings,
) -> MLOpsSettings:
    """Create settings explicitly targeting Azure Blob registry."""

    payload = settings.model_dump()

    payload[
        "model_registry_backend"
    ] = (
        ModelRegistryBackend.AZURE_BLOB
    )

    return MLOpsSettings(
        **payload
    )


def prepare_seed_package(
    *,
    settings: MLOpsSettings,
) -> tuple[Path, str]:
    """Create the exact production model package for Blob."""

    source_files = {
        "best_model.joblib": (
            PROJECT_ROOT
            / "models"
            / "best_model.joblib"
        ),
        "model_feature_columns.json": (
            PROJECT_ROOT
            / "models"
            / "model_feature_columns.json"
        ),
        "model_metadata.json": (
            PROJECT_ROOT
            / "models"
            / "model_metadata.json"
        ),
        "model_selection_report.json": (
            PROJECT_ROOT
            / "models"
            / "model_selection_report.json"
        ),
    }

    missing = [
        str(path)
        for path in source_files.values()
        if not path.exists()
    ]

    if missing:
        raise ModelMigrationError(
            "Approved production model artifacts "
            f"are missing: {missing}"
        )

    checksum = calculate_sha256(
        source_files[
            "best_model.joblib"
        ]
    )

    try:
        joblib.load(
            source_files[
                "best_model.joblib"
            ]
        )
    except Exception as error:
        raise ModelMigrationError(
            "Approved production model cannot "
            "be loaded with joblib."
        ) from error

    package_directory = (
        PROJECT_ROOT
        / "models"
        / "blob_registry_seed"
        / (
            f"{settings.hopsworks_model_name}_"
            f"v{settings.hopsworks_production_model_version}"
        )
    )

    if package_directory.exists():
        shutil.rmtree(
            package_directory
        )

    package_directory.mkdir(
        parents=True,
        exist_ok=False,
    )

    for filename, source_path in (
        source_files.items()
    ):
        shutil.copy2(
            source_path,
            package_directory
            / filename,
        )

    source_metadata = load_json_object(
        source_files[
            "model_metadata.json"
        ]
    )

    registry_metadata = {
        "model_name": (
            settings.hopsworks_model_name
        ),
        "model_version": (
            settings
            .hopsworks_production_model_version
        ),
        "model_status": (
            "PRODUCTION"
        ),
        "artifact_checksum_sha256": (
            checksum
        ),
        "source_registry": (
            "Hopsworks Model Registry"
        ),
        "migration_target": (
            "Azure Blob Model Registry"
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
        "source_model_metadata": (
            source_metadata
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

    return (
        package_directory,
        checksum,
    )


def validate_resolved_model(
    *,
    resolved: Any,
    expected_checksum: str,
    expected_version: int,
) -> dict[str, Any]:
    """Validate a production model downloaded from Blob."""

    checks = {
        "version_matches": (
            resolved.version
            == expected_version
        ),
        "status_is_production": (
            resolved.status
            == "PRODUCTION"
        ),
        "checksum_matches": (
            resolved.checksum_sha256
            == expected_checksum
        ),
        "model_exists": (
            resolved
            .model_artifact_path
            .exists()
        ),
        "feature_columns_exist": (
            resolved
            .feature_columns_path
            .exists()
        ),
        "metadata_exists": (
            resolved
            .metadata_path
            .exists()
        ),
    }

    try:
        joblib.load(
            resolved.model_artifact_path
        )
        checks[
            "joblib_load_succeeds"
        ] = True

    except Exception:
        checks[
            "joblib_load_succeeds"
        ] = False

    valid = all(
        checks.values()
    )

    if not valid:
        raise ModelMigrationError(
            "Resolved Blob production model "
            f"failed validation: {checks}"
        )

    return {
        "valid": valid,
        "checks": checks,
    }


def run_migration(
    *,
    settings: MLOpsSettings,
) -> dict[str, Any]:
    """Seed and validate the approved production model."""

    started_at = datetime.now(
        timezone.utc
    )

    blob_settings = (
        build_blob_settings(
            settings
        )
    )

    package_directory, checksum = (
        prepare_seed_package(
            settings=settings
        )
    )

    repository = (
        AzureBlobModelRepository(
            settings=blob_settings
        )
    )

    version = (
        settings
        .hopsworks_production_model_version
    )

    registered = (
        repository.seed_production_model(
            package_directory=(
                package_directory
            ),
            version=version,
            checksum_sha256=checksum,
        )
    )

    pointer = (
        repository.set_production_version(
            version=version
        )
    )

    resolved = (
        repository
        .resolve_production_model(
            project_root=(
                PROJECT_ROOT
            )
        )
    )

    validation = (
        validate_resolved_model(
            resolved=resolved,
            expected_checksum=checksum,
            expected_version=version,
        )
    )

    completed_at = datetime.now(
        timezone.utc
    )

    return {
        "phase": "10P",
        "subphase": "10P-F",
        "status": (
            "AZURE_BLOB_PRODUCTION_MODEL_SEEDED"
        ),
        "started_at_utc": (
            started_at.isoformat()
        ),
        "completed_at_utc": (
            completed_at.isoformat()
        ),
        "duration_seconds": (
            completed_at
            - started_at
        ).total_seconds(),
        "source": {
            "model_name": (
                settings.hopsworks_model_name
            ),
            "version": version,
            "checksum_sha256": (
                checksum
            ),
            "package_directory": (
                str(
                    package_directory
                )
            ),
        },
        "target": {
            "backend": (
                repository.backend_name
            ),
            "azure_storage_account": (
                blob_settings
                .azure_storage_account
            ),
            "azure_storage_container": (
                blob_settings
                .azure_storage_container
            ),
            "registry_prefix": (
                blob_settings
                .azure_model_registry_prefix
            ),
            "registered": (
                registered.to_dict()
            ),
            "production_pointer": (
                pointer
            ),
        },
        "resolved": (
            resolved.to_dict()
        ),
        "validation": (
            validation
        ),
        "production_runtime_configuration_changed": (
            False
        ),
        "hopsworks_model_preserved": (
            True
        ),
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Save migration report atomically."""

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = (
        REPORT_PATH.with_suffix(
            ".json.tmp"
        )
    )

    temporary_path.write_text(
        json.dumps(
            report,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    temporary_path.replace(
        REPORT_PATH
    )

    return REPORT_PATH


def main() -> int:
    """CLI entry point."""

    parser = argparse.ArgumentParser(
        description=(
            "Seed the approved production model "
            "into the Azure Blob model registry."
        )
    )

    parser.parse_args()

    try:
        settings = (
            get_mlops_settings()
        )

        report = run_migration(
            settings=settings
        )

        exit_code = 0

    except Exception as error:
        report = {
            "phase": "10P",
            "subphase": "10P-F",
            "status": (
                "AZURE_BLOB_PRODUCTION_MODEL_SEED_FAILED"
            ),
            "failed_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "error_type": (
                type(error).__name__
            ),
            "error_message": (
                str(error)
            ),
            "production_runtime_configuration_changed": (
                False
            ),
        }

        exit_code = 1

    report_path = save_report(
        report
    )

    print(
        json.dumps(
            report,
            indent=2,
            default=str,
        )
    )

    print(
        "Report saved:",
        report_path,
    )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
