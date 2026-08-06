"""Run the production-safe daily retraining workflow.

The scheduled workflow:

1. rebuilds the current leakage-safe training dataset from Hopsworks;
2. checks whether enough genuinely new labeled reference hours exist;
3. exits successfully when retraining is not eligible;
4. trains a challenger only when eligible;
5. evaluates the exact challenger against the champion;
6. never registers or promotes a model automatically;
7. durably publishes candidate evidence when a candidate was evaluated.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.artifacts.repository import (
    ArtifactRepository,
)
from app.core.config import PROJECT_ROOT
from app.mlops.config import (
    get_mlops_settings,
)
from app.pipelines.champion_challenger import (
    run_champion_challenger,
)
from app.pipelines.publish_forecast import (
    create_configured_repository,
)
from app.pipelines.refresh_training_dataset import (
    resolve_output_root,
    run_training_dataset_refresh,
)
from app.pipelines.retraining_cycle import (
    run_retraining_cycle,
)


REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "daily_retraining_report.json"
)

ARTIFACT_TYPE = "model-candidates"


class DailyRetrainingError(RuntimeError):
    """Raised when daily retraining orchestration fails."""


def require_status(
    report: dict[str, Any],
    expected_statuses: set[str],
    *,
    pipeline_name: str,
) -> str:
    """Validate and return a nested pipeline status."""

    status = str(
        report.get("status", "")
    )

    if status not in expected_statuses:
        raise DailyRetrainingError(
            f"{pipeline_name} returned an unexpected "
            f"status: {status!r}"
        )

    return status


def resolve_candidate_directory(
    retraining_report: dict[str, Any],
) -> Path:
    """Resolve the candidate package created by retraining."""

    candidate = retraining_report.get(
        "candidate"
    )

    if not isinstance(candidate, dict):
        raise DailyRetrainingError(
            "Retraining report does not contain "
            "candidate metadata."
        )

    candidate_path = candidate.get(
        "directory"
    )

    if not isinstance(
        candidate_path,
        str,
    ) or not candidate_path.strip():
        raise DailyRetrainingError(
            "Retraining report does not contain "
            "a valid candidate directory."
        )

    resolved = Path(
        candidate_path
    ).expanduser()

    if not resolved.is_absolute():
        resolved = (
            PROJECT_ROOT
            / resolved
        )

    resolved = resolved.resolve()

    required_files = [
        resolved / "best_model.joblib",
        resolved / "candidate_metadata.json",
        resolved / "checksum.sha256",
        resolved / "model_feature_columns.json",
    ]

    missing_files = [
        str(path)
        for path in required_files
        if not path.exists()
    ]

    if missing_files:
        raise DailyRetrainingError(
            "Candidate package is incomplete: "
            f"{missing_files}"
        )

    return resolved


def create_publication_bundle(
    *,
    candidate_directory: Path,
    retraining_report: dict[str, Any],
    comparison_report: dict[str, Any],
    training_refresh_report: dict[str, Any],
) -> Path:
    """Create one complete candidate-evaluation publication directory."""

    bundle_directory = (
        candidate_directory
        / "publication_bundle"
    )

    if bundle_directory.exists():
        shutil.rmtree(
            bundle_directory
        )

    bundle_directory.mkdir(
        parents=True,
        exist_ok=False,
    )

    for source_path in (
        candidate_directory
        / "best_model.joblib",
        candidate_directory
        / "candidate_metadata.json",
        candidate_directory
        / "checksum.sha256",
        candidate_directory
        / "model_feature_columns.json",
    ):
        shutil.copy2(
            source_path,
            bundle_directory
            / source_path.name,
        )

    report_payloads = {
        "retraining_report.json": (
            retraining_report
        ),
        "champion_challenger_report.json": (
            comparison_report
        ),
        "training_dataset_refresh_report.json": (
            training_refresh_report
        ),
    }

    for filename, payload in (
        report_payloads.items()
    ):
        (
            bundle_directory
            / filename
        ).write_text(
            json.dumps(
                payload,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    return bundle_directory


def validate_candidate_publication(
    *,
    repository: ArtifactRepository,
    candidate_run_id: str,
) -> dict[str, Any]:
    """Validate the latest evaluated candidate pointer and manifest."""

    pointer = repository.get_latest_pointer(
        ARTIFACT_TYPE
    )

    manifest = repository.get_latest_manifest(
        ARTIFACT_TYPE
    )

    checks = {
        "pointer_run_matches": (
            pointer.get("run_id")
            == candidate_run_id
        ),
        "manifest_run_matches": (
            manifest.get("run_id")
            == candidate_run_id
        ),
        "pointer_status_is_evaluated": (
            pointer.get(
                "validation_status"
            )
            == "CANDIDATE_EVALUATED"
        ),
        "manifest_status_is_evaluated": (
            manifest.get(
                "validation_status"
            )
            == "CANDIDATE_EVALUATED"
        ),
        "manifest_contains_files": bool(
            manifest.get("files")
        ),
    }

    if not all(checks.values()):
        raise DailyRetrainingError(
            "Candidate publication validation failed: "
            f"{checks}"
        )

    return {
        "checks": checks,
        "pointer": pointer,
        "manifest": manifest,
    }


def publish_candidate_evidence(
    *,
    candidate_directory: Path,
    retraining_report: dict[str, Any],
    comparison_report: dict[str, Any],
    training_refresh_report: dict[str, Any],
) -> dict[str, Any]:
    """Publish the candidate package and evaluation reports durably."""

    bundle_directory = (
        create_publication_bundle(
            candidate_directory=(
                candidate_directory
            ),
            retraining_report=(
                retraining_report
            ),
            comparison_report=(
                comparison_report
            ),
            training_refresh_report=(
                training_refresh_report
            ),
        )
    )

    repository = (
        create_configured_repository()
    )

    candidate_run_id = (
        candidate_directory.name
    )

    publication = repository.publish_run(
        artifact_type=ARTIFACT_TYPE,
        run_id=candidate_run_id,
        source_directory=bundle_directory,
        validation_status=(
            "CANDIDATE_EVALUATED"
        ),
        source_run_id=str(
            training_refresh_report[
                "pipeline_run_id"
            ]
        ),
    )

    validation = (
        validate_candidate_publication(
            repository=repository,
            candidate_run_id=(
                candidate_run_id
            ),
        )
    )

    return {
        "artifact_type": ARTIFACT_TYPE,
        "run_id": candidate_run_id,
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
            validation["checks"]
        ),
    }


def run_daily_retraining(
    *,
    output_root: Path,
) -> dict[str, Any]:
    """Run one production-safe daily retraining evaluation."""

    started_at = datetime.now(
        timezone.utc
    )

    started_monotonic = (
        time.monotonic()
    )

    mlops_settings = (
        get_mlops_settings()
    )

    training_refresh_report = (
        run_training_dataset_refresh(
            settings=mlops_settings,
            output_root=output_root,
        )
    )

    require_status(
        training_refresh_report,
        {
            "TRAINING_DATASET_REFRESH_COMPLETED",
        },
        pipeline_name=(
            "training dataset refresh"
        ),
    )

    runtime_directory = Path(
        str(
            training_refresh_report[
                "run_directory"
            ]
        )
    ).resolve()

    retraining_report = (
        run_retraining_cycle(
            force=False,
            dataset_directory=(
                runtime_directory
            ),
        )
    )

    retraining_status = require_status(
        retraining_report,
        {
            "RETRAINING_SKIPPED_NO_NEW_DATA",
            "RETRAINING_COMPLETED",
        },
        pipeline_name=(
            "controlled retraining"
        ),
    )

    completed_at = datetime.now(
        timezone.utc
    )

    if (
        retraining_status
        == "RETRAINING_SKIPPED_NO_NEW_DATA"
    ):
        return {
            "phase": "10K",
            "subphase": "10K-C3",
            "pipeline_name": (
                "daily_retraining"
            ),
            "status": (
                "DAILY_RETRAINING_SKIPPED"
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
            "training_refresh": (
                training_refresh_report
            ),
            "retraining": (
                retraining_report
            ),
            "champion_challenger": None,
            "publication": None,
            "candidate_created": False,
            "candidate_registered": False,
            "automatic_promotion_attempted": False,
            "production_model_changed": False,
        }

    if not bool(
        retraining_report.get(
            "candidate_created"
        )
    ):
        raise DailyRetrainingError(
            "Retraining completed without creating "
            "a candidate package."
        )

    candidate_directory = (
        resolve_candidate_directory(
            retraining_report
        )
    )

    comparison_report = (
        run_champion_challenger(
            register_approved=False,
            candidate_directory=(
                candidate_directory
            ),
        )
    )

    comparison_status = (
        require_status(
            comparison_report,
            {
                "CHALLENGER_APPROVED",
                "CHALLENGER_REJECTED",
            },
            pipeline_name=(
                "champion–challenger evaluation"
            ),
        )
    )

    publication_report = (
        publish_candidate_evidence(
            candidate_directory=(
                candidate_directory
            ),
            retraining_report=(
                retraining_report
            ),
            comparison_report=(
                comparison_report
            ),
            training_refresh_report=(
                training_refresh_report
            ),
        )
    )

    final_status = (
        "DAILY_RETRAINING_CHALLENGER_APPROVED"
        if comparison_status
        == "CHALLENGER_APPROVED"
        else (
            "DAILY_RETRAINING_CHALLENGER_REJECTED"
        )
    )

    completed_at = datetime.now(
        timezone.utc
    )

    return {
        "phase": "10K",
        "subphase": "10K-C3",
        "pipeline_name": (
            "daily_retraining"
        ),
        "status": final_status,
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
        "training_refresh": (
            training_refresh_report
        ),
        "retraining": retraining_report,
        "champion_challenger": (
            comparison_report
        ),
        "publication": (
            publication_report
        ),
        "candidate_created": True,
        "candidate_registered": False,
        "automatic_promotion_attempted": False,
        "production_model_changed": False,
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Atomically save the daily retraining report."""

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
            "Refresh current training data and "
            "run one production-safe retraining "
            "eligibility cycle."
        )
    )

    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help=(
            "Optional root for immutable runtime "
            "training packages."
        ),
    )

    arguments = parser.parse_args()

    try:
        report = run_daily_retraining(
            output_root=resolve_output_root(
                arguments.output_root
            ),
        )

        exit_code = 0

    except Exception as error:
        report = {
            "phase": "10K",
            "subphase": "10K-C3",
            "pipeline_name": (
                "daily_retraining"
            ),
            "status": (
                "DAILY_RETRAINING_FAILED"
            ),
            "failed_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(error),
            "candidate_created": False,
            "candidate_registered": False,
            "automatic_promotion_attempted": False,
            "production_model_changed": False,
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