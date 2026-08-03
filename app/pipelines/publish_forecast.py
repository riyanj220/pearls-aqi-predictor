"""Run inference, AQI processing, and durable artifact publication.

This is the production orchestration entry point for the scheduled
forecast workflow.

Execution order:

1. Run one exact Phase 5 live-inference execution.
2. Run Phase 6 using that exact Phase 5 run ID.
3. Publish the validated Phase 6 run through the configured artifact
   repository.
4. Verify that the latest pointer resolves to the newly published run.

The latest repository pointer is updated only after every artifact,
checksum, and manifest has been published successfully.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.artifacts.repository import (
    ArtifactRepository,
    ArtifactRepositoryError,
    PublicationResult,
    create_artifact_repository,
)
from app.core.config import PROJECT_ROOT
from app.pipelines.aqi_alert_pipeline import (
    run_aqi_alert_pipeline,
)
from app.pipelines.live_inference import (
    generate_pipeline_run_id,
    run_live_inference,
)


REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "forecast_publication_report.json"
)

DEFAULT_LOCAL_ARTIFACT_ROOT = (
    PROJECT_ROOT
    / "artifacts"
    / "repository"
)

ARTIFACT_TYPE = "aqi"

def resolve_subphase(
    artifact_backend: str,
) -> str:
    """Resolve the Phase 10J subphase from the backend."""

    if artifact_backend == "azure_blob":
        return "10J-B"

    return "10J-A"

class ForecastPublicationError(RuntimeError):
    """Raised when the combined publication workflow fails."""


def read_environment_value(
    name: str,
    *,
    default: str | None = None,
) -> str | None:
    """Read and normalize one environment variable."""

    value = os.getenv(
        name,
        default,
    )

    if value is None:
        return None

    cleaned_value = value.strip()

    return cleaned_value or None


def resolve_local_artifact_root() -> Path:
    """Resolve the configured local artifact repository root."""

    configured_value = read_environment_value(
        "LOCAL_ARTIFACT_ROOT",
        default=str(
            DEFAULT_LOCAL_ARTIFACT_ROOT
        ),
    )

    if configured_value is None:
        return DEFAULT_LOCAL_ARTIFACT_ROOT.resolve()

    path = Path(
        configured_value
    ).expanduser()

    if not path.is_absolute():
        path = PROJECT_ROOT / path

    resolved_path = path.resolve()

    # Prevent accidentally publishing into the project root where the
    # Phase 6 source directory already exists.
    if resolved_path == PROJECT_ROOT.resolve():
        raise ForecastPublicationError(
            "LOCAL_ARTIFACT_ROOT cannot be the project root. "
            "Use a dedicated path such as "
            "'artifacts/repository'."
        )

    return resolved_path


def create_configured_repository() -> ArtifactRepository:
    """Create the configured local or Azure Blob repository."""

    backend = (
        read_environment_value(
            "ARTIFACT_BACKEND",
            default="local",
        )
        or "local"
    ).lower()

    if backend == "local":
        return create_artifact_repository(
            backend="local",
            local_root=(
                resolve_local_artifact_root()
            ),
        )

    if backend == "azure_blob":
        storage_account = (
            read_environment_value(
                "AZURE_STORAGE_ACCOUNT"
            )
        )

        storage_container = (
            read_environment_value(
                "AZURE_STORAGE_CONTAINER",
                default="artifacts",
            )
        )

        return create_artifact_repository(
            backend="azure_blob",
            azure_storage_account=(
                storage_account
            ),
            azure_storage_container=(
                storage_container
            ),
        )

    raise ForecastPublicationError(
        "ARTIFACT_BACKEND must be either "
        "'local' or 'azure_blob'."
    )


def require_report_value(
    report: dict[str, Any],
    key: str,
) -> Any:
    """Read one required pipeline-report value."""

    value = report.get(key)

    if value is None:
        raise ForecastPublicationError(
            f"Pipeline report is missing required field: {key}"
        )

    return value


def validate_phase_5_report(
    report: dict[str, Any],
    *,
    expected_run_id: str,
) -> None:
    """Validate the returned Phase 5 operational report."""

    if (
        report.get("status")
        != "LIVE_INFERENCE_COMPLETED"
    ):
        raise ForecastPublicationError(
            "Phase 5 did not complete successfully. "
            f"Status={report.get('status')!r}"
        )

    if (
        report.get("validation_status")
        != "PASSED"
    ):
        raise ForecastPublicationError(
            "Phase 5 validation did not pass. "
            f"Status={report.get('validation_status')!r}"
        )

    actual_run_id = str(
        require_report_value(
            report,
            "pipeline_run_id",
        )
    )

    if actual_run_id != expected_run_id:
        raise ForecastPublicationError(
            "Phase 5 returned a different pipeline run ID. "
            f"Expected={expected_run_id}, "
            f"actual={actual_run_id}"
        )

    if int(
        require_report_value(
            report,
            "forecast_rows",
        )
    ) != 72:
        raise ForecastPublicationError(
            "Phase 5 did not produce exactly 72 rows."
        )

    run_directory = Path(
        str(
            require_report_value(
                report,
                "run_directory",
            )
        )
    )

    if not run_directory.exists():
        raise ForecastPublicationError(
            "Phase 5 run directory does not exist: "
            f"{run_directory}"
        )


def validate_phase_6_report(
    report: dict[str, Any],
    *,
    expected_source_run_id: str,
) -> Path:
    """Validate Phase 6 and return its immutable run directory."""

    if (
        report.get("status")
        != "AQI_ALERT_PIPELINE_COMPLETED"
    ):
        raise ForecastPublicationError(
            "Phase 6 did not complete successfully. "
            f"Status={report.get('status')!r}"
        )

    validation_status = str(
        require_report_value(
            report,
            "validation_status",
        )
    )

    if (
        validation_status
        != "AQI_ALERT_PIPELINE_APPROVED"
    ):
        raise ForecastPublicationError(
            "Phase 6 did not receive approval. "
            f"Status={validation_status}"
        )

    source_run_id = str(
        require_report_value(
            report,
            "source_phase_5_run_id",
        )
    )

    if source_run_id != expected_source_run_id:
        raise ForecastPublicationError(
            "Phase 6 consumed an unexpected Phase 5 run. "
            f"Expected={expected_source_run_id}, "
            f"actual={source_run_id}"
        )

    if int(
        require_report_value(
            report,
            "forecast_rows",
        )
    ) != 72:
        raise ForecastPublicationError(
            "Phase 6 did not produce exactly 72 rows."
        )

    run_directory = Path(
        str(
            require_report_value(
                report,
                "run_directory",
            )
        )
    ).resolve()

    if not run_directory.exists():
        raise ForecastPublicationError(
            "Phase 6 run directory does not exist: "
            f"{run_directory}"
        )

    if not run_directory.is_dir():
        raise ForecastPublicationError(
            "Phase 6 run path is not a directory: "
            f"{run_directory}"
        )

    return run_directory


def validate_publication(
    *,
    repository: ArtifactRepository,
    publication: PublicationResult,
    expected_phase_6_run_id: str,
    expected_source_run_id: str,
) -> dict[str, Any]:
    """Verify the manifest and latest pointer after publication."""

    pointer = repository.get_latest_pointer(
        ARTIFACT_TYPE
    )

    manifest = repository.get_latest_manifest(
        ARTIFACT_TYPE
    )

    checks = {
        "pointer_run_id_matches": (
            pointer.get("run_id")
            == expected_phase_6_run_id
        ),
        "manifest_run_id_matches": (
            manifest.get("run_id")
            == expected_phase_6_run_id
        ),
        "pointer_source_run_id_matches": (
            pointer.get("source_run_id")
            == expected_source_run_id
        ),
        "manifest_source_run_id_matches": (
            manifest.get("source_run_id")
            == expected_source_run_id
        ),
        "pointer_validation_passed": (
            pointer.get("validation_status")
            == "AQI_ALERT_PIPELINE_APPROVED"
        ),
        "manifest_validation_passed": (
            manifest.get("validation_status")
            == "AQI_ALERT_PIPELINE_APPROVED"
        ),
        "manifest_has_files": bool(
            manifest.get("files")
        ),
        "publication_pointer_matches": (
            publication.latest_pointer.run_id
            == expected_phase_6_run_id
        ),
    }

    if not all(checks.values()):
        raise ForecastPublicationError(
            "Published artifact verification failed: "
            f"{checks}"
        )

    return {
        "checks": checks,
        "pointer": pointer,
        "manifest": manifest,
    }


def run_forecast_publication() -> dict[str, Any]:
    """Run Phase 5, Phase 6, and durable publication."""

    artifact_backend = (
        read_environment_value(
            "ARTIFACT_BACKEND",
            default="local",
        )
        or "local"
    ).lower()

    subphase = resolve_subphase(
        artifact_backend
    )

    started_at = datetime.now(
        timezone.utc
    )

    started_monotonic = time.monotonic()

    phase_5_run_id = (
        generate_pipeline_run_id()
    )

    phase_5_report = run_live_inference(
        pipeline_run_id=phase_5_run_id,
    )

    validate_phase_5_report(
        phase_5_report,
        expected_run_id=phase_5_run_id,
    )

    phase_6_report = (
        run_aqi_alert_pipeline(
            source_run_id=phase_5_run_id
        )
    )

    phase_6_run_directory = (
        validate_phase_6_report(
            phase_6_report,
            expected_source_run_id=(
                phase_5_run_id
            ),
        )
    )

    phase_6_run_id = str(
        require_report_value(
            phase_6_report,
            "phase_6_run_id",
        )
    )

    repository = (
        create_configured_repository()
    )

    publication = repository.publish_run(
        artifact_type=ARTIFACT_TYPE,
        run_id=phase_6_run_id,
        source_directory=(
            phase_6_run_directory
        ),
        validation_status=(
            "AQI_ALERT_PIPELINE_APPROVED"
        ),
        source_run_id=phase_5_run_id,
    )

    publication_validation = (
        validate_publication(
            repository=repository,
            publication=publication,
            expected_phase_6_run_id=(
                phase_6_run_id
            ),
            expected_source_run_id=(
                phase_5_run_id
            ),
        )
    )

    completed_at = datetime.now(
        timezone.utc
    )

    return {
        "phase": "10J",
        "subphase": subphase,
        "pipeline_name": (
            "forecast_publication"
        ),
        "status": (
            "FORECAST_PUBLICATION_COMPLETED"
        ),
        "started_at_utc": (
            started_at.isoformat()
        ),
        "completed_at_utc": (
            completed_at.isoformat()
        ),
        "duration_seconds": round(
            time.monotonic()
            - started_monotonic,
            3,
        ),
        "artifact_backend": artifact_backend,

        "phase_5": {
            "pipeline_run_id": (
                phase_5_run_id
            ),
            "status": (
                phase_5_report["status"]
            ),
            "validation_status": (
                phase_5_report[
                    "validation_status"
                ]
            ),
            "forecast_rows": (
                phase_5_report[
                    "forecast_rows"
                ]
            ),
            "model_source": (
                phase_5_report.get(
                    "model_source"
                )
            ),
            "model_registry_version": (
                phase_5_report.get(
                    "model_registry_version"
                )
            ),
        },
        "phase_6": {
            "phase_6_run_id": (
                phase_6_run_id
            ),
            "source_phase_5_run_id": (
                phase_5_run_id
            ),
            "status": (
                phase_6_report["status"]
            ),
            "validation_status": (
                phase_6_report[
                    "validation_status"
                ]
            ),
            "forecast_rows": (
                phase_6_report[
                    "forecast_rows"
                ]
            ),
            "active_alert_rows": (
                phase_6_report.get(
                    "active_alert_rows"
                )
            ),
            "alert_episode_count": (
                phase_6_report.get(
                    "alert_episode_count"
                )
            ),
        },
        "publication": {
            "artifact_type": (
                ARTIFACT_TYPE
            ),
            "run_id": (
                publication
                .latest_pointer
                .run_id
            ),
            "artifact_prefix": (
                publication
                .latest_pointer
                .artifact_prefix
            ),
            "manifest_path": (
                publication
                .latest_pointer
                .manifest_path
            ),
            "published_at_utc": (
                publication
                .latest_pointer
                .published_at_utc
            ),
            "file_count": len(
                publication.manifest.files
            ),
            "validation": (
                publication_validation[
                    "checks"
                ]
            ),
        },
        "api_updated": False,
        "azure_job_created": False,
        "schedule_enabled": False,
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Save the latest orchestration report atomically."""

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = REPORT_PATH.with_suffix(
        ".json.tmp"
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
            "Run live inference, AQI processing, "
            "and durable artifact publication."
        )
    )

    parser.parse_args()

    artifact_backend = (
        read_environment_value(
            "ARTIFACT_BACKEND",
            default="local",
        )
        or "local"
    ).lower()

    subphase = resolve_subphase(
        artifact_backend
    )

    try:
        report = (
            run_forecast_publication()
        )

        exit_code = 0

    except Exception as error:
        report = {
            "phase": "10J",
            "subphase": subphase,
            "artifact_backend": artifact_backend,
            "pipeline_name": (
                "forecast_publication"
            ),
            "status": (
                "FORECAST_PUBLICATION_FAILED"
            ),
            "failed_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(error),
            "api_updated": False,
            "azure_job_created": False,
            "schedule_enabled": False,
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
    raise SystemExit(main())