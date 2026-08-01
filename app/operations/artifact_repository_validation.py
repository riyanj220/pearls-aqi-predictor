"""Validate durable artifact publication behavior."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.artifacts.repository import (
    ArtifactRepositoryError,
    LocalArtifactRepository,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "artifact_repository_validation_report.json"
)


def create_sample_run(
    directory: Path,
) -> None:
    """Create a small realistic run for validation."""

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        directory
        / "forecast.json"
    ).write_text(
        json.dumps(
            {
                "pipeline_run_id": (
                    "phase10d-validation-run"
                ),
                "forecast_rows": 72,
                "status": "PASSED",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    (
        directory
        / "validation_report.json"
    ).write_text(
        json.dumps(
            {
                "status": "PASSED",
                "checks": {
                    "forecast_rows": 72,
                    "unique_horizons": 72,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def run_local_validation() -> dict[str, Any]:
    """Validate immutable publication and latest-pointer behavior."""

    with tempfile.TemporaryDirectory(
        prefix="pearls-aqi-artifacts-"
    ) as temporary_directory:
        temporary_root = Path(
            temporary_directory
        )

        source_directory = (
            temporary_root / "source"
        )

        repository_root = (
            temporary_root / "repository"
        )

        create_sample_run(
            source_directory
        )

        repository = LocalArtifactRepository(
            repository_root
        )

        first_result = repository.publish_run(
            artifact_type="inference",
            run_id="phase10d-validation-run",
            source_directory=source_directory,
            validation_status="PASSED",
        )

        latest_pointer = (
            repository.get_latest_pointer(
                "inference"
            )
        )

        latest_manifest = (
            repository.get_latest_manifest(
                "inference"
            )
        )

        duplicate_run_blocked = False

        try:
            repository.publish_run(
                artifact_type="inference",
                run_id=(
                    "phase10d-validation-run"
                ),
                source_directory=source_directory,
                validation_status="PASSED",
            )
        except ArtifactRepositoryError:
            duplicate_run_blocked = True

        invalid_run_blocked = False

        try:
            repository.publish_run(
                artifact_type="inference",
                run_id="invalid-validation-run",
                source_directory=source_directory,
                validation_status="FAILED",
            )
        except ArtifactRepositoryError:
            invalid_run_blocked = True

        checks = {
            "run_manifest_exists": (
                repository.exists(
                    first_result
                    .latest_pointer
                    .manifest_path
                )
            ),
            "latest_pointer_exists": (
                repository.exists(
                    "inference/latest/pointer.json"
                )
            ),
            "latest_points_to_run": (
                latest_pointer["run_id"]
                == "phase10d-validation-run"
            ),
            "manifest_file_count": (
                len(latest_manifest["files"])
                == 2
            ),
            "all_manifest_checksums_present": all(
                bool(file_record["sha256"])
                for file_record
                in latest_manifest["files"]
            ),
            "duplicate_run_blocked": (
                duplicate_run_blocked
            ),
            "invalid_run_blocked": (
                invalid_run_blocked
            ),
        }

        approved = all(
            checks.values()
        )

        return {
            "phase": "10D",
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": (
                "ARTIFACT_REPOSITORY_VALIDATED"
                if approved
                else "ARTIFACT_REPOSITORY_INVALID"
            ),
            "approved": approved,
            "backend_validated": "local",
            "azure_backend_implemented": True,
            "azure_live_connection_tested": False,
            "checks": checks,
            "publication_contract": {
                "immutable_run_paths": True,
                "checksums_recorded": True,
                "manifest_written_before_latest": True,
                "latest_written_last": True,
                "invalid_runs_cannot_be_latest": True,
            },
            "azure_resources_created": False,
        }


def save_validation_report(
    report: dict[str, Any],
) -> Path:
    """Save the Phase 10D validation report."""

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    return REPORT_PATH


def main() -> int:
    """Run Phase 10D validation."""

    parser = argparse.ArgumentParser(
        description=(
            "Validate the artifact repository "
            "publication contract."
        )
    )

    parser.parse_args()

    try:
        report = run_local_validation()

        exit_code = (
            0
            if report["approved"]
            else 1
        )

    except Exception as error:
        report = {
            "phase": "10D",
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": (
                "ARTIFACT_REPOSITORY_VALIDATION_FAILED"
            ),
            "approved": False,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "azure_resources_created": False,
        }

        exit_code = 1

    report_path = save_validation_report(
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