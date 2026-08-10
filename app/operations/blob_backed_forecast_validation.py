"""Validate a Hopsworks-independent Blob-backed forecast execution."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT
from app.mlops.config import (
    FeatureStoreBackend,
    ModelLoadingMode,
    ModelRegistryBackend,
    get_mlops_settings,
)
from app.pipelines.publish_forecast import (
    run_forecast_publication,
)


REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "blob_backed_forecast_validation_report.json"
)


class BlobForecastValidationError(
    RuntimeError
):
    """Raised when Blob-backed forecast validation fails."""


def require_environment(
    name: str,
    expected: str,
) -> None:
    """Require one exact runtime setting."""

    actual = (
        os.getenv(
            name,
            ""
        )
        .strip()
    )

    if actual.lower() != expected.lower():
        raise BlobForecastValidationError(
            f"{name} must be {expected!r}; "
            f"received {actual!r}."
        )


def run_validation() -> dict[str, Any]:
    """Run one complete Blob-backed production forecast."""

    started_at = datetime.now(
        timezone.utc
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

    get_mlops_settings.cache_clear()

    settings = get_mlops_settings()

    checks = {
        "feature_backend_is_blob": (
            settings.feature_store_backend
            == FeatureStoreBackend.AZURE_BLOB
        ),
        "model_registry_is_blob": (
            settings.model_registry_backend
            == ModelRegistryBackend.AZURE_BLOB
        ),
        "model_loading_is_blob": (
            settings.model_loading_mode
            == ModelLoadingMode.AZURE_BLOB_REGISTRY
        ),
    }

    if not all(checks.values()):
        raise BlobForecastValidationError(
            "MLOps configuration did not resolve "
            f"to Azure Blob: {checks}"
        )

    publication_report = (
        run_forecast_publication()
    )

    phase_5 = publication_report.get(
        "phase_5",
        {}
    )

    phase_6 = publication_report.get(
        "phase_6",
        {}
    )

    publication = publication_report.get(
        "publication",
        {}
    )

    runtime_checks = {
        "forecast_publication_completed": (
            publication_report.get(
                "status"
            )
            == "FORECAST_PUBLICATION_COMPLETED"
        ),
        "phase_5_completed": (
            phase_5.get(
                "status"
            )
            == "LIVE_INFERENCE_COMPLETED"
        ),
        "phase_5_validation_passed": (
            phase_5.get(
                "validation_status"
            )
            == "PASSED"
        ),
        "forecast_has_72_rows": (
            int(
                phase_5.get(
                    "forecast_rows",
                    0,
                )
            )
            == 72
        ),
        "phase_6_completed": (
            phase_6.get(
                "status"
            )
            == "AQI_ALERT_PIPELINE_COMPLETED"
        ),
        "phase_6_approved": (
            phase_6.get(
                "validation_status"
            )
            == "AQI_ALERT_PIPELINE_APPROVED"
        ),
        "phase_6_has_72_rows": (
            int(
                phase_6.get(
                    "forecast_rows",
                    0,
                )
            )
            == 72
        ),
        "artifact_published": bool(
            publication.get(
                "run_id"
            )
        ),
        "model_source_is_blob": (
            phase_5.get(
                "model_source"
            )
            == "AZURE_BLOB_REGISTRY"
        ),
    }

    valid = (
        all(
            checks.values()
        )
        and all(
            runtime_checks.values()
        )
    )

    if not valid:
        raise BlobForecastValidationError(
            "Blob-backed forecast validation "
            "failed: "
            f"{runtime_checks}"
        )

    completed_at = datetime.now(
        timezone.utc
    )

    return {
        "phase": "10P",
        "subphase": "10P-G",
        "status": (
            "BLOB_BACKED_FORECAST_VALIDATED"
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
        "configuration_checks": (
            checks
        ),
        "runtime_checks": (
            runtime_checks
        ),
        "forecast_publication": (
            publication_report
        ),
        "hopsworks_required_for_execution": (
            False
        ),
        "production_runtime_configuration_changed": (
            False
        ),
        "valid": True,
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Persist validation report atomically."""

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = (
        REPORT_PATH.with_suffix(
            ".json.tmp"
        )
    )

    temporary.write_text(
        json.dumps(
            report,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    temporary.replace(
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
            "subphase": "10P-G",
            "status": (
                "BLOB_BACKED_FORECAST_VALIDATION_FAILED"
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
            "hopsworks_required_for_execution": (
                None
            ),
            "production_runtime_configuration_changed": (
                False
            ),
            "valid": False,
        }

        exit_code = 1

    path = save_report(
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
        path,
    )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
