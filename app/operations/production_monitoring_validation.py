"""Validate the complete deployed production-monitoring workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]

REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "production_monitoring_validation_report.json"
)

HEALTH_POINTER_PATH = (
    "production-health/latest/pointer.json"
)

NOTIFICATION_OUTBOX_PATH = (
    "production-health/notifications/outbox.json"
)

RECEIPT_PREFIX = (
    "production-health/notifications/receipts/"
)

EXPECTED_COMMAND = [
    "/app/bin/run_production_health",
]


class ProductionMonitoringValidationError(
    RuntimeError
):
    """Raised when deployed monitoring validation fails."""


def run_command(
    arguments: list[str],
) -> str:
    """Run one command and return standard output."""

    completed = subprocess.run(
        arguments,
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        raise ProductionMonitoringValidationError(
            "Command failed.\n"
            f"Command: {' '.join(arguments)}\n"
            f"Error: {completed.stderr.strip()}"
        )

    return completed.stdout.strip()


def run_json_command(
    arguments: list[str],
) -> Any:
    """Run one command and parse its JSON response."""

    output = run_command(
        [
            *arguments,
            "--output",
            "json",
        ]
    )

    try:
        return json.loads(output)
    except json.JSONDecodeError as error:
        raise ProductionMonitoringValidationError(
            "Command did not return valid JSON."
        ) from error


def load_job(
    *,
    resource_group: str,
    job_name: str,
) -> dict[str, Any]:
    """Load the deployed monitoring job."""

    payload = run_json_command(
        [
            "az",
            "containerapp",
            "job",
            "show",
            "--resource-group",
            resource_group,
            "--name",
            job_name,
        ]
    )

    if not isinstance(payload, dict):
        raise ProductionMonitoringValidationError(
            "Monitoring job response is not an object."
        )

    return payload


def load_executions(
    *,
    resource_group: str,
    job_name: str,
) -> list[dict[str, Any]]:
    """Load recent monitoring executions."""

    payload = run_json_command(
        [
            "az",
            "containerapp",
            "job",
            "execution",
            "list",
            "--resource-group",
            resource_group,
            "--name",
            job_name,
        ]
    )

    if not isinstance(payload, list):
        raise ProductionMonitoringValidationError(
            "Monitoring executions response is not a list."
        )

    executions = [
        item
        for item in payload
        if isinstance(item, dict)
    ]

    executions.sort(
        key=lambda item: str(
            item.get(
                "properties",
                {},
            ).get(
                "startTime",
                "",
            )
        ),
        reverse=True,
    )

    return executions


def download_blob(
    *,
    storage_account: str,
    storage_container: str,
    blob_name: str,
    destination: Path,
) -> bytes:
    """Download one Blob artifact."""

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    run_command(
        [
            "az",
            "storage",
            "blob",
            "download",
            "--account-name",
            storage_account,
            "--container-name",
            storage_container,
            "--name",
            blob_name,
            "--auth-mode",
            "login",
            "--file",
            str(destination),
            "--overwrite",
            "--only-show-errors",
        ]
    )

    return destination.read_bytes()


def blob_exists(
    *,
    storage_account: str,
    storage_container: str,
    blob_name: str,
) -> bool:
    """Return whether one Blob artifact exists."""

    output = run_command(
        [
            "az",
            "storage",
            "blob",
            "exists",
            "--account-name",
            storage_account,
            "--container-name",
            storage_container,
            "--name",
            blob_name,
            "--auth-mode",
            "login",
            "--query",
            "exists",
            "--output",
            "tsv",
        ]
    )

    return output.lower() == "true"


def list_receipts(
    *,
    storage_account: str,
    storage_container: str,
) -> list[dict[str, Any]]:
    """List immutable webhook delivery receipts."""

    payload = run_json_command(
        [
            "az",
            "storage",
            "blob",
            "list",
            "--account-name",
            storage_account,
            "--container-name",
            storage_container,
            "--prefix",
            RECEIPT_PREFIX,
            "--auth-mode",
            "login",
        ]
    )

    if not isinstance(payload, list):
        raise ProductionMonitoringValidationError(
            "Webhook receipt response is not a list."
        )

    return [
        item
        for item in payload
        if isinstance(item, dict)
    ]


def environment_mapping(
    job: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Return container environment variables by name."""

    containers = (
        job.get(
            "properties",
            {},
        )
        .get(
            "template",
            {},
        )
        .get(
            "containers",
            [],
        )
    )

    if not containers:
        raise ProductionMonitoringValidationError(
            "Monitoring job contains no container."
        )

    environment = containers[0].get(
        "env",
        [],
    )

    return {
        str(item.get("name")): item
        for item in environment
        if item.get("name")
    }


def validate_monitoring(
    *,
    job: dict[str, Any],
    executions: list[dict[str, Any]],
    expected_image: str | None,
    storage_account: str,
    storage_container: str,
) -> dict[str, Any]:
    """Validate job, snapshot, incident, and webhook state."""

    properties = job.get(
        "properties",
        {},
    )

    configuration = properties.get(
        "configuration",
        {},
    )

    template = properties.get(
        "template",
        {},
    )

    containers = template.get(
        "containers",
        [],
    )

    if not containers:
        raise ProductionMonitoringValidationError(
            "Monitoring job contains no containers."
        )

    container = containers[0]

    schedule = configuration.get(
        "scheduleTriggerConfig",
        {},
    )

    environment = environment_mapping(
        job
    )

    command = container.get(
        "command"
    ) or []

    arguments = container.get(
        "args"
    ) or []

    latest_execution = (
        executions[0]
        if executions
        else None
    )

    latest_execution_status = None

    if latest_execution is not None:
        latest_execution_status = (
            latest_execution.get(
                "properties",
                {},
            ).get(
                "status"
            )
        )

    pointer_bytes = download_blob(
        storage_account=storage_account,
        storage_container=storage_container,
        blob_name=HEALTH_POINTER_PATH,
        destination=Path(
            "/tmp/production-health-pointer.json"
        ),
    )

    pointer = json.loads(
        pointer_bytes.decode("utf-8")
    )

    manifest_path = str(
        pointer.get(
            "manifest_path",
            "",
        )
    )

    artifact_prefix = str(
        pointer.get(
            "artifact_prefix",
            "",
        )
    )

    if not manifest_path:
        raise ProductionMonitoringValidationError(
            "Health pointer has no manifest path."
        )

    manifest_bytes = download_blob(
        storage_account=storage_account,
        storage_container=storage_container,
        blob_name=manifest_path,
        destination=Path(
            "/tmp/production-health-manifest.json"
        ),
    )

    manifest = json.loads(
        manifest_bytes.decode("utf-8")
    )

    report_blob_path = (
        f"{artifact_prefix}/"
        "production_health_report.json"
    )

    report_bytes = download_blob(
        storage_account=storage_account,
        storage_container=storage_container,
        blob_name=report_blob_path,
        destination=Path(
            "/tmp/production-health-report.json"
        ),
    )

    health_report = json.loads(
        report_bytes.decode("utf-8")
    )

    manifest_files = manifest.get(
        "files",
        [],
    )

    report_record = next(
        (
            record
            for record in manifest_files
            if record.get(
                "relative_path"
            )
            == "production_health_report.json"
        ),
        None,
    )

    checksum_matches = False

    if isinstance(
        report_record,
        dict,
    ):
        checksum_matches = (
            report_record.get(
                "sha256"
            )
            == hashlib.sha256(
                report_bytes
            ).hexdigest()
        )

    outbox_exists = blob_exists(
        storage_account=storage_account,
        storage_container=storage_container,
        blob_name=NOTIFICATION_OUTBOX_PATH,
    )

    outbox = None
    pending_count = 0

    if outbox_exists:
        outbox_bytes = download_blob(
            storage_account=storage_account,
            storage_container=storage_container,
            blob_name=NOTIFICATION_OUTBOX_PATH,
            destination=Path(
                "/tmp/production-health-outbox.json"
            ),
        )

        outbox = json.loads(
            outbox_bytes.decode("utf-8")
        )

        pending = outbox.get(
            "pending",
            [],
        )

        if isinstance(pending, list):
            pending_count = len(pending)

    receipts = list_receipts(
        storage_account=storage_account,
        storage_container=storage_container,
    )

    image = str(
        container.get(
            "image",
            "",
        )
    )

    effective_parallelism = (
        schedule.get(
            "parallelism"
        )
    )

    if effective_parallelism is None:
        effective_parallelism = 1

    completion_count = (
        schedule.get(
            "replicaCompletionCount"
        )
    )

    if completion_count is None:
        completion_count = 1

    checks = {
        "job_provisioning_succeeded": (
            properties.get(
                "provisioningState"
            )
            == "Succeeded"
        ),
        "trigger_is_schedule": (
            configuration.get(
                "triggerType"
            )
            == "Schedule"
        ),
        "cron_is_hourly": (
            schedule.get(
                "cronExpression"
            )
            == "45 * * * *"
        ),
        "parallelism_is_one": (
            effective_parallelism == 1
        ),
        "completion_count_is_one": (
            completion_count == 1
        ),
        "timeout_is_600": (
            configuration.get(
                "replicaTimeout"
            )
            == 600
        ),
        "retry_limit_is_one": (
            configuration.get(
                "replicaRetryLimit"
            )
            == 1
        ),
        "entrypoint_is_valid": (
            command == EXPECTED_COMMAND
            and not arguments
        ),
        "image_is_immutable": (
            ":" in image
            and not image.endswith(
                ":latest"
            )
        ),
        "expected_image_matches": (
            expected_image is None
            or image == expected_image
        ),
        "latest_execution_succeeded": (
            latest_execution_status
            == "Succeeded"
        ),
        "artifact_backend_is_azure_blob": (
            environment.get(
                "ARTIFACT_BACKEND",
                {},
            ).get(
                "value"
            )
            == "azure_blob"
        ),
        "job_query_backend_is_arm": (
            environment.get(
                "AZURE_JOB_QUERY_BACKEND",
                {},
            ).get(
                "value"
            )
            == "arm"
        ),
        "webhook_is_enabled": (
            environment.get(
                "PRODUCTION_HEALTH_WEBHOOK_ENABLED",
                {},
            ).get(
                "value"
            )
            == "true"
        ),
        "webhook_uses_secret": (
            environment.get(
                "PRODUCTION_HEALTH_WEBHOOK_URL",
                {},
            ).get(
                "secretRef"
            )
            == "production-health-webhook-url"
        ),
        "health_pointer_is_valid": (
            pointer.get(
                "artifact_type"
            )
            == "production-health"
            and pointer.get(
                "validation_status"
            )
            == "PRODUCTION_HEALTH_RECORDED"
        ),
        "manifest_matches_pointer": (
            manifest.get(
                "run_id"
            )
            == pointer.get(
                "run_id"
            )
        ),
        "health_report_checksum_matches": (
            checksum_matches
        ),
        "health_report_is_read_only": (
            health_report.get(
                "read_only"
            )
            is True
        ),
        "outbox_exists": (
            outbox_exists
        ),
        "outbox_has_valid_pending_count": (
            isinstance(
                pending_count,
                int,
            )
            and pending_count >= 0
        ),
    }

    return {
        "valid": all(
            checks.values()
        ),
        "checks": checks,
        "job": {
            "image": image,
            "command": command,
            "args": arguments,
            "cron_expression": (
                schedule.get(
                    "cronExpression"
                )
            ),
            "latest_execution": (
                latest_execution
            ),
        },
        "health_snapshot": {
            "run_id": pointer.get(
                "run_id"
            ),
            "published_at_utc": (
                pointer.get(
                    "published_at_utc"
                )
            ),
            "health_status": (
                health_report.get(
                    "status"
                )
            ),
            "overall_component_status": (
                health_report.get(
                    "overall_component_status"
                )
            ),
            "checksum_matches": (
                checksum_matches
            ),
        },
        "notifications": {
            "outbox_exists": (
                outbox_exists
            ),
            "pending_count": (
                pending_count
            ),
            "receipt_count": len(
                receipts
            ),
            "receipt_names": [
                item.get(
                    "name"
                )
                for item in receipts
            ],
        },
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Atomically save the validation report."""

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
            "Validate deployed production health "
            "monitoring and webhook delivery."
        )
    )

    parser.add_argument(
        "--resource-group",
        default=(
            "rg-pearls-aqi-staging"
        ),
    )

    parser.add_argument(
        "--job-name",
        default=(
            "job-pearls-aqi-monitoring"
        ),
    )

    parser.add_argument(
        "--storage-account",
        default=(
            "stpearlsaqiriyan"
        ),
    )

    parser.add_argument(
        "--storage-container",
        default="artifacts",
    )

    parser.add_argument(
        "--expected-image",
        default=None,
    )

    arguments = parser.parse_args()

    try:
        job = load_job(
            resource_group=(
                arguments.resource_group
            ),
            job_name=(
                arguments.job_name
            ),
        )

        executions = load_executions(
            resource_group=(
                arguments.resource_group
            ),
            job_name=(
                arguments.job_name
            ),
        )

        validation = validate_monitoring(
            job=job,
            executions=executions,
            expected_image=(
                arguments.expected_image
            ),
            storage_account=(
                arguments.storage_account
            ),
            storage_container=(
                arguments.storage_container
            ),
        )

        report = {
            "phase": "10L",
            "subphase": "10L-E",
            "generated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "PRODUCTION_MONITORING_VALIDATED"
                if validation["valid"]
                else "PRODUCTION_MONITORING_INVALID"
            ),
            "resource_group": (
                arguments.resource_group
            ),
            "job_name": (
                arguments.job_name
            ),
            **validation,
        }

        exit_code = (
            0
            if validation["valid"]
            else 1
        )

    except Exception as error:
        report = {
            "phase": "10L",
            "subphase": "10L-E",
            "generated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "PRODUCTION_MONITORING_VALIDATION_FAILED"
            ),
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(error),
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
    raise SystemExit(main())