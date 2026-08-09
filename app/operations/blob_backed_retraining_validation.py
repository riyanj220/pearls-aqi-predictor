"""Validate Hopsworks-independent model retraining from Azure Blob."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT
from app.mlops.config import (
    FeatureStoreBackend,
    ModelRegistryBackend,
    get_mlops_settings,
)
from app.pipelines.champion_challenger import (
    run_champion_challenger,
)
from app.pipelines.daily_retraining import (
    publish_candidate_evidence,
    resolve_candidate_directory,
)
from app.pipelines.refresh_training_dataset import (
    run_training_dataset_refresh,
)
from app.pipelines.retraining_cycle import (
    run_retraining_cycle,
)


REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "blob_backed_retraining_validation_report.json"
)

RUNTIME_ROOT = (
    PROJECT_ROOT
    / ".cache"
    / "phase_10p"
    / "retraining_validation"
)


class BlobRetrainingValidationError(
    RuntimeError
):
    """Raised when Blob-backed retraining validation fails."""


def require_environment(
    name: str,
    expected: str,
) -> None:
    """Require one exact environment value."""

    actual = (
        os.getenv(
            name,
            "",
        )
        .strip()
    )

    if actual.lower() != expected.lower():
        raise BlobRetrainingValidationError(
            f"{name} must be {expected!r}; "
            f"received {actual!r}."
        )


def require_hopsworks_absent() -> dict[str, bool]:
    """Verify that Hopsworks credentials are unavailable."""

    checks = {
        "api_key_absent": (
            not os.getenv(
                "HOPSWORKS_API_KEY"
            )
        ),
        "project_absent": (
            not os.getenv(
                "HOPSWORKS_PROJECT"
            )
        ),
        "host_absent": (
            not os.getenv(
                "HOPSWORKS_HOST"
            )
        ),
    }

    if not all(checks.values()):
        raise BlobRetrainingValidationError(
            "Hopsworks configuration is still "
            f"present: {checks}"
        )

    return checks


def require_status(
    report: dict[str, Any],
    expected: set[str],
    *,
    name: str,
) -> str:
    """Require an expected pipeline status."""

    status = str(
        report.get(
            "status",
            "",
        )
    )

    if status not in expected:
        raise BlobRetrainingValidationError(
            f"{name} returned unexpected "
            f"status {status!r}."
        )

    return status


def run_validation() -> dict[str, Any]:
    """Run a complete Blob-backed retraining evaluation."""

    started_at = datetime.now(
        timezone.utc
    )

    started_monotonic = (
        time.monotonic()
    )

    require_environment(
        "FEATURE_STORE_BACKEND",
        "azure_blob",
    )

    require_environment(
        "MODEL_REGISTRY_BACKEND",
        "azure_blob",
    )

    require_environment(
        "MODEL_LOADING_MODE",
        "AZURE_BLOB_REGISTRY",
    )

    require_environment(
        "ARTIFACT_BACKEND",
        "azure_blob",
    )

    hopsworks_checks = (
        require_hopsworks_absent()
    )

    get_mlops_settings.cache_clear()

    settings = (
        get_mlops_settings()
    )

    configuration_checks = {
        "feature_backend_is_blob": (
            settings.feature_store_backend
            == FeatureStoreBackend.AZURE_BLOB
        ),
        "model_registry_is_blob": (
            settings.model_registry_backend
            == ModelRegistryBackend.AZURE_BLOB
        ),
    }

    if not all(
        configuration_checks.values()
    ):
        raise BlobRetrainingValidationError(
            "MLOps settings did not resolve "
            f"to Blob: {configuration_checks}"
        )

    RUNTIME_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    #
    # 1. Rebuild training data entirely
    #    from Blob feature datasets.
    #
    training_refresh_report = (
        run_training_dataset_refresh(
            settings=settings,
            output_root=(
                RUNTIME_ROOT
                / "training"
            ),
        )
    )

    require_status(
        training_refresh_report,
        {
            "TRAINING_DATASET_REFRESH_COMPLETED",
        },
        name="training dataset refresh",
    )

    runtime_directory = Path(
        str(
            training_refresh_report[
                "run_directory"
            ]
        )
    ).resolve()

    #
    # 2. Force one challenger training
    #    cycle for validation purposes.
    #
    retraining_report = (
        run_retraining_cycle(
            force=True,
            dataset_directory=(
                runtime_directory
            ),
        )
    )

    require_status(
        retraining_report,
        {
            "RETRAINING_COMPLETED",
        },
        name="forced retraining",
    )

    if not bool(
        retraining_report.get(
            "candidate_created"
        )
    ):
        raise BlobRetrainingValidationError(
            "Forced retraining did not "
            "create a candidate."
        )

    candidate_directory = (
        resolve_candidate_directory(
            retraining_report
        )
    )

    #
    # 3. Compare candidate against current
    #    champion, but DO NOT register it.
    #
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
            name=(
                "champion challenger"
            ),
        )
    )

    #
    # 4. Publish evidence to Blob.
    #
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

    runtime_checks = {
        "training_refresh_completed": (
            training_refresh_report.get(
                "status"
            )
            == "TRAINING_DATASET_REFRESH_COMPLETED"
        ),
        "training_source_is_blob": (
            training_refresh_report.get(
                "feature_repository_backend"
            )
            == "azure_blob"
            or training_refresh_report.get(
                "source"
            )
            == "Azure Blob Feature Repository"
        ),
        "training_rows_exist": (
            int(
                training_refresh_report.get(
                    "final_rows",
                    0,
                )
            )
            > 0
        ),
        "forced_retraining_completed": (
            retraining_report.get(
                "status"
            )
            == "RETRAINING_COMPLETED"
        ),
        "candidate_created": bool(
            retraining_report.get(
                "candidate_created"
            )
        ),
        "candidate_directory_exists": (
            candidate_directory.exists()
        ),
        "candidate_model_exists": (
            (
                candidate_directory
                / "best_model.joblib"
            ).exists()
        ),
        "candidate_checksum_exists": (
            (
                candidate_directory
                / "checksum.sha256"
            ).exists()
        ),
        "comparison_completed": (
            comparison_status
            in {
                "CHALLENGER_APPROVED",
                "CHALLENGER_REJECTED",
            }
        ),
        "candidate_not_registered": (
            not bool(
                comparison_report.get(
                    "challenger",
                    {},
                ).get(
                    "registered",
                    False,
                )
            )
        ),
        "production_not_changed": (
            comparison_report.get(
                "production_changed"
            )
            is False
        ),
        "candidate_evidence_published": (
            bool(
                publication_report.get(
                    "run_id"
                )
            )
        ),
    }

    valid = (
        all(
            configuration_checks.values()
        )
        and all(
            hopsworks_checks.values()
        )
        and all(
            runtime_checks.values()
        )
    )

    if not valid:
        raise BlobRetrainingValidationError(
            "Blob-backed retraining "
            f"validation failed: {runtime_checks}"
        )

    completed_at = datetime.now(
        timezone.utc
    )

    return {
        "phase": "10P",
        "subphase": "10P-H",
        "status": (
            "BLOB_BACKED_RETRAINING_VALIDATED"
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
        "configuration_checks": (
            configuration_checks
        ),
        "hopsworks_checks": (
            hopsworks_checks
        ),
        "runtime_checks": (
            runtime_checks
        ),
        "training_refresh": (
            training_refresh_report
        ),
        "retraining": (
            retraining_report
        ),
        "champion_challenger": (
            comparison_report
        ),
        "publication": (
            publication_report
        ),
        "challenger_decision": (
            comparison_status
        ),
        "candidate_registered": False,
        "automatic_promotion_attempted": False,
        "production_model_changed": False,
        "hopsworks_required_for_execution": False,
        "production_runtime_configuration_changed": False,
        "valid": True,
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Save Phase 10P-H validation evidence."""

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

    try:
        report = run_validation()
        exit_code = 0

    except Exception as error:
        report = {
            "phase": "10P",
            "subphase": "10P-H",
            "status": (
                "BLOB_BACKED_RETRAINING_VALIDATION_FAILED"
            ),
            "failed_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(
                error
            ),
            "candidate_registered": False,
            "automatic_promotion_attempted": False,
            "production_model_changed": False,
            "production_runtime_configuration_changed": False,
            "valid": False,
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
