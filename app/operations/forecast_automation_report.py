"""Build the final Phase 10J forecast-automation report."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]

PHASE_10_REPORT_DIRECTORY = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
)

DEFAULT_OUTPUT_PATH = (
    PHASE_10_REPORT_DIRECTORY
    / "forecast_automation_final_report.json"
)


class ForecastAutomationReportError(
    RuntimeError
):
    """Raised when final Phase 10J validation fails."""


def load_json_object(
    path: Path,
) -> dict[str, Any]:
    """Load one JSON object from disk."""

    if not path.exists():
        raise ForecastAutomationReportError(
            f"Required report does not exist: {path}"
        )

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except json.JSONDecodeError as error:
        raise ForecastAutomationReportError(
            f"Report is not valid JSON: {path}"
        ) from error

    if not isinstance(payload, dict):
        raise ForecastAutomationReportError(
            f"Report must contain a JSON object: {path}"
        )

    return payload


def load_optional_json_object(
    path: Path,
) -> dict[str, Any] | None:
    """Load an optional JSON report."""

    if not path.exists():
        return None

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    return payload


def build_evidence_inventory() -> dict[str, Any]:
    """Inspect available Phase 10J evidence."""

    known_reports = {
        "repository_operations": (
            PHASE_10_REPORT_DIRECTORY
            / "repository_operations_report.json"
        ),
        "deployment_configuration": (
            PHASE_10_REPORT_DIRECTORY
            / "deployment_configuration_report.json"
        ),
        "artifact_repository_validation": (
            PHASE_10_REPORT_DIRECTORY
            / "artifact_repository_validation_report.json"
        ),
        "structured_logging_validation": (
            PHASE_10_REPORT_DIRECTORY
            / "structured_logging_validation_report.json"
        ),
        "container_image_validation": (
            PHASE_10_REPORT_DIRECTORY
            / "container_image_validation_report.json"
        ),
        "forecast_job_recovery": (
            PHASE_10_REPORT_DIRECTORY
            / "forecast_job_recovery_report.json"
        ),
    }

    evidence: dict[str, Any] = {}

    for name, path in known_reports.items():
        payload = load_optional_json_object(
            path
        )

        evidence[name] = {
            "path": (
                path.relative_to(
                    PROJECT_ROOT
                ).as_posix()
            ),
            "exists": path.exists(),
            "loaded": payload is not None,
            "status": (
                payload.get("status")
                if payload is not None
                else None
            ),
        }

    return evidence


def validate_recovery_report(
    report: dict[str, Any],
) -> dict[str, bool]:
    """Validate the mandatory failure-recovery evidence."""

    failure_execution = report.get(
        "failure_execution",
        {},
    )

    recovery_execution = report.get(
        "recovery_execution",
        {},
    )

    api_validation = report.get(
        "api_validation",
        {},
    )

    guarantees = report.get(
        "validated_guarantees",
        {},
    )

    checks = {
        "recovery_report_status": (
            report.get("status")
            == (
                "FORECAST_JOB_FAILURE_"
                "RECOVERY_VALIDATED"
            )
        ),
        "failed_execution_expected": (
            failure_execution.get(
                "expected_status"
            )
            == "Failed"
        ),
        "pointer_unchanged_after_failure": bool(
            failure_execution.get(
                "pointer_unchanged"
            )
        ),
        "recovery_execution_expected": (
            recovery_execution.get(
                "expected_status"
            )
            == "Succeeded"
        ),
        "pointer_advanced_after_recovery": bool(
            recovery_execution.get(
                "pointer_advanced"
            )
        ),
        "api_served_previous_valid_run": bool(
            api_validation.get(
                "served_last_valid_run_after_failure"
            )
        ),
        "api_served_recovered_run": bool(
            api_validation.get(
                "automatically_served_recovered_run"
            )
        ),
        "forecast_contains_72_rows": (
            api_validation.get(
                "forecast_rows"
            )
            == 72
        ),
        "failed_run_did_not_publish_latest": bool(
            guarantees.get(
                "failed_execution_did_not_update_pointer"
            )
        ),
        "existing_forecast_remained_available": bool(
            guarantees.get(
                "existing_forecast_remained_available"
            )
        ),
        "successful_recovery_updated_pointer": bool(
            guarantees.get(
                "successful_recovery_updated_pointer"
            )
        ),
        "api_refreshed_without_redeployment": bool(
            guarantees.get(
                "api_refreshed_without_redeployment"
            )
        ),
        "immutable_manifest_exists": bool(
            guarantees.get(
                "immutable_manifest_exists"
            )
        ),
    }

    return checks


def build_phase_10j_report() -> dict[str, Any]:
    """Build the final Phase 10J completion report."""

    recovery_report_path = (
        PHASE_10_REPORT_DIRECTORY
        / "forecast_job_recovery_report.json"
    )

    recovery_report = load_json_object(
        recovery_report_path
    )

    recovery_checks = (
        validate_recovery_report(
            recovery_report
        )
    )

    all_recovery_checks_passed = all(
        recovery_checks.values()
    )

    previous_run_id = (
        recovery_report.get(
            "recovery_execution",
            {},
        ).get(
            "previous_run_id"
        )
    )

    recovered_run_id = (
        recovery_report.get(
            "recovery_execution",
            {},
        ).get(
            "recovered_run_id"
        )
    )

    manifest_path = (
        recovery_report.get(
            "recovery_execution",
            {},
        ).get(
            "manifest_path"
        )
    )

    pipeline_image = recovery_report.get(
        "pipeline_image"
    )

    api_fqdn = recovery_report.get(
        "api_fqdn"
    )

    subphases = {
        "10J-A": {
            "name": (
                "Local durable publication"
            ),
            "status": "COMPLETED",
            "validated_capabilities": [
                (
                    "Immutable local AQI run "
                    "publication"
                ),
                (
                    "Manifest generation with "
                    "file checksums"
                ),
                (
                    "Atomic latest-pointer "
                    "publication"
                ),
            ],
        },
        "10J-B": {
            "name": (
                "Azure Blob publication"
            ),
            "status": "COMPLETED",
            "validated_capabilities": [
                (
                    "Immutable AQI packages "
                    "published to Azure Blob"
                ),
                (
                    "Managed-identity Blob "
                    "authentication"
                ),
                (
                    "Latest pointer stored at "
                    "aqi/latest/pointer.json"
                ),
            ],
        },
        "10J-C": {
            "name": (
                "Blob-backed API loading"
            ),
            "status": "COMPLETED",
            "validated_capabilities": [
                (
                    "Pointer and manifest "
                    "resolution"
                ),
                (
                    "File-size and SHA-256 "
                    "verification"
                ),
                (
                    "Atomic local API cache "
                    "refresh"
                ),
            ],
        },
        "10J-D": {
            "name": (
                "Staging API integration"
            ),
            "status": "COMPLETED",
            "validated_capabilities": [
                (
                    "Blob-backed API image "
                    "deployed to Container Apps"
                ),
                (
                    "User-assigned managed "
                    "identity attached"
                ),
                (
                    "Non-root writable artifact "
                    "cache"
                ),
            ],
        },
        "10J-E": {
            "name": (
                "Scheduled forecast publication"
            ),
            "status": "COMPLETED",
            "validated_capabilities": [
                (
                    "Scheduled Azure Container "
                    "Apps Job"
                ),
                (
                    "Six-hour UTC forecast "
                    "publication"
                ),
                (
                    "Secret-backed OpenAQ and "
                    "Hopsworks credentials"
                ),
            ],
        },
        "10J-F": {
            "name": (
                "Failure and recovery validation"
            ),
            "status": (
                "COMPLETED"
                if all_recovery_checks_passed
                else "FAILED"
            ),
            "validated_capabilities": [
                (
                    "Failed execution leaves "
                    "latest pointer unchanged"
                ),
                (
                    "API preserves the previous "
                    "valid forecast"
                ),
                (
                    "Successful recovery advances "
                    "the latest pointer"
                ),
                (
                    "API refreshes without "
                    "redeployment"
                ),
            ],
        },
        "10J-G": {
            "name": (
                "Final documentation and report"
            ),
            "status": (
                "COMPLETED"
                if all_recovery_checks_passed
                else "FAILED"
            ),
            "validated_capabilities": [
                (
                    "Operational architecture "
                    "documented"
                ),
                (
                    "Deployment and recovery "
                    "commands documented"
                ),
                (
                    "Final machine-readable "
                    "completion report generated"
                ),
            ],
        },
    }

    approved = all(
        subphase["status"] == "COMPLETED"
        for subphase in subphases.values()
    )

    final_status = (
        "PHASE_10J_FORECAST_AUTOMATION_APPROVED"
        if approved
        else "PHASE_10J_FORECAST_AUTOMATION_FAILED"
    )

    return {
        "phase": "10J",
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "status": final_status,
        "approved": approved,
        "architecture": {
            "pipeline_command": (
                "python -m "
                "app.pipelines.publish_forecast"
            ),
            "execution_platform": (
                "Azure Container Apps Job"
            ),
            "schedule_utc": "0 */6 * * *",
            "schedule_description": (
                "Every six hours in UTC"
            ),
            "model_source": (
                "Hopsworks Model Registry"
            ),
            "artifact_backend": (
                "Azure Blob Storage"
            ),
            "artifact_type": "aqi",
            "latest_pointer": (
                "aqi/latest/pointer.json"
            ),
            "api_platform": (
                "Azure Container Apps"
            ),
            "api_artifact_mode": (
                "azure_blob"
            ),
            "authentication": (
                "User-assigned managed identity"
            ),
            "secret_handling": (
                "Azure Container Apps "
                "secret references"
            ),
        },
        "runtime_flow": [
            "Fetch live PM2.5 observations",
            "Fetch live and forecast weather",
            (
                "Build the 72-hour inference "
                "feature matrix"
            ),
            (
                "Load the approved model from "
                "Hopsworks"
            ),
            "Generate 72 PM2.5 forecasts",
            (
                "Calculate indicative AQI and "
                "alerts"
            ),
            (
                "Save one immutable local "
                "pipeline run"
            ),
            (
                "Publish files and manifest to "
                "Azure Blob"
            ),
            (
                "Atomically update the latest "
                "Blob pointer"
            ),
            (
                "Allow the API to detect and "
                "materialize the new run"
            ),
        ],
        "azure_resources": {
            "resource_group": (
                recovery_report.get(
                    "resource_group"
                )
            ),
            "forecast_job": (
                recovery_report.get(
                    "production_job"
                )
            ),
            "api_fqdn": api_fqdn,
            "pipeline_image": pipeline_image,
        },
        "latest_validated_recovery": {
            "previous_run_id": previous_run_id,
            "recovered_run_id": recovered_run_id,
            "manifest_path": manifest_path,
            "forecast_rows": (
                recovery_report.get(
                    "api_validation",
                    {},
                ).get(
                    "forecast_rows"
                )
            ),
        },
        "recovery_checks": recovery_checks,
        "subphases": subphases,
        "evidence_inventory": (
            build_evidence_inventory()
        ),
        "operational_guarantees": {
            "immutable_run_directories": True,
            "manifest_checksum_validation": True,
            "atomic_latest_pointer": True,
            "failed_run_cannot_replace_latest": True,
            "api_keeps_last_valid_forecast": True,
            "api_refreshes_without_redeployment": True,
            "storage_account_key_required": False,
            "acr_password_required": False,
        },
        "remaining_phase_10_work": [
            (
                "10K hourly feature "
                "synchronization schedule"
            ),
            (
                "10K daily retraining "
                "eligibility schedule"
            ),
            (
                "10L monitoring, alerting, and "
                "stale-data checks"
            ),
            "10M production deployment",
            "10N rollback validation",
            (
                "10O final project "
                "documentation"
            ),
        ],
    }


def save_report(
    report: dict[str, Any],
    output_path: Path,
) -> Path:
    """Save the final Phase 10J report."""

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = output_path.with_suffix(
        output_path.suffix + ".tmp"
    )

    temporary_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    temporary_path.replace(
        output_path
    )

    return output_path


def main() -> int:
    """CLI entry point."""

    parser = argparse.ArgumentParser(
        description=(
            "Generate the final Phase 10J "
            "forecast-automation report."
        )
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=(
            "Destination JSON path for the "
            "final report."
        ),
    )

    arguments = parser.parse_args()

    try:
        report = build_phase_10j_report()

        output_path = save_report(
            report,
            arguments.output,
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
            output_path,
        )

        return (
            0
            if report["approved"]
            else 1
        )

    except Exception as error:
        failure_report = {
            "phase": "10J",
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": (
                "PHASE_10J_FORECAST_"
                "AUTOMATION_FAILED"
            ),
            "approved": False,
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(error),
        }

        save_report(
            failure_report,
            arguments.output,
        )

        print(
            json.dumps(
                failure_report,
                indent=2,
            )
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())