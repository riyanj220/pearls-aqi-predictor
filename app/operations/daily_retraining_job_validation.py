"""Validate the scheduled Azure daily retraining job."""

from __future__ import annotations

import argparse
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
    / "daily_retraining_job_report.json"
)

EXPECTED_COMMAND = [
    "/app/bin/run_daily_retraining",
]


class RetrainingJobValidationError(
    RuntimeError
):
    """Raised when the Azure retraining job is invalid."""


def run_azure_cli(
    arguments: list[str],
) -> Any:
    """Run one Azure CLI command and parse JSON output."""

    command = [
        "az",
        *arguments,
        "--output",
        "json",
    ]

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        raise RetrainingJobValidationError(
            "Azure CLI command failed.\n"
            f"Command: {' '.join(command)}\n"
            f"Error: {completed.stderr.strip()}"
        )

    try:
        return json.loads(
            completed.stdout
        )
    except json.JSONDecodeError as error:
        raise RetrainingJobValidationError(
            "Azure CLI did not return valid JSON."
        ) from error


def normalize_command(
    value: Any,
) -> list[str]:
    """Normalize a container command or argument list."""

    if value is None:
        return []

    if not isinstance(value, list):
        raise RetrainingJobValidationError(
            "Container command must be a list."
        )

    return [
        str(item)
        for item in value
    ]


def get_job(
    *,
    resource_group: str,
    job_name: str,
) -> dict[str, Any]:
    """Read the deployed Azure Container Apps job."""

    payload = run_azure_cli(
        [
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
        raise RetrainingJobValidationError(
            "Azure job response was not an object."
        )

    return payload


def get_executions(
    *,
    resource_group: str,
    job_name: str,
) -> list[dict[str, Any]]:
    """Read recent job executions."""

    payload = run_azure_cli(
        [
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
        raise RetrainingJobValidationError(
            "Azure execution response was not a list."
        )

    return [
        item
        for item in payload
        if isinstance(item, dict)
    ]


def validate_job(
    *,
    job: dict[str, Any],
    executions: list[dict[str, Any]],
    expected_image: str | None,
) -> dict[str, Any]:
    """Validate configuration and recent execution state."""

    properties = job.get(
        "properties",
        {}
    )

    configuration = properties.get(
        "configuration",
        {}
    )

    template = properties.get(
        "template",
        {}
    )

    containers = template.get(
        "containers",
        []
    )

    if not containers:
        raise RetrainingJobValidationError(
            "Job template contains no containers."
        )

    container = containers[0]

    schedule_configuration = (
        configuration.get(
            "scheduleTriggerConfig",
            {},
        )
    )

    command = normalize_command(
        container.get("command")
    )

    arguments = normalize_command(
        container.get("args")
    )

    parallelism = (
        schedule_configuration.get(
            "parallelism"
        )
    )

    if parallelism is None:
        parallelism = 1

    completion_count = (
        schedule_configuration.get(
            "replicaCompletionCount"
        )
    )

    if completion_count is None:
        completion_count = 1

    resources = container.get(
        "resources",
        {}
    )

    recent_execution = (
        executions[0]
        if executions
        else None
    )

    recent_execution_status = None

    if recent_execution is not None:
        recent_execution_status = (
            recent_execution.get(
                "properties",
                {},
            ).get("status")
        )

    checks = {
        "provisioning_succeeded": (
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
        "cron_is_daily": (
            schedule_configuration.get(
                "cronExpression"
            )
            == "30 3 * * *"
        ),
        "parallelism_is_one": (
            parallelism == 1
        ),
        "completion_count_is_one": (
            completion_count == 1
        ),
        "timeout_is_3600": (
            configuration.get(
                "replicaTimeout"
            )
            == 3600
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
        "cpu_is_one": (
            float(
                resources.get(
                    "cpu",
                    0,
                )
            )
            == 1.0
        ),
        "memory_is_2gi": (
            str(
                resources.get(
                    "memory",
                    ""
                )
            ).lower()
            == "2gi"
        ),
        "image_is_immutable": (
            ":" in str(
                container.get(
                    "image",
                    ""
                )
            )
            and not str(
                container.get(
                    "image",
                    ""
                )
            ).endswith(":latest")
        ),
        "expected_image_matches": (
            expected_image is None
            or container.get(
                "image"
            )
            == expected_image
        ),
        "recent_execution_succeeded": (
            recent_execution_status
            == "Succeeded"
        ),
    }

    return {
        "checks": checks,
        "valid": all(
            checks.values()
        ),
        "configuration": {
            "provisioning_state": (
                properties.get(
                    "provisioningState"
                )
            ),
            "trigger_type": (
                configuration.get(
                    "triggerType"
                )
            ),
            "cron_expression": (
                schedule_configuration.get(
                    "cronExpression"
                )
            ),
            "parallelism": parallelism,
            "completion_count": (
                completion_count
            ),
            "timeout_seconds": (
                configuration.get(
                    "replicaTimeout"
                )
            ),
            "retry_limit": (
                configuration.get(
                    "replicaRetryLimit"
                )
            ),
            "image": container.get(
                "image"
            ),
            "command": command,
            "args": arguments,
            "cpu": resources.get(
                "cpu"
            ),
            "memory": resources.get(
                "memory"
            ),
        },
        "latest_execution": (
            recent_execution
        ),
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
            "Validate the production daily "
            "retraining Azure job."
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
            "job-pearls-aqi-retraining"
        ),
    )

    parser.add_argument(
        "--expected-image",
        default=None,
    )

    arguments = parser.parse_args()

    try:
        job = get_job(
            resource_group=(
                arguments.resource_group
            ),
            job_name=(
                arguments.job_name
            ),
        )

        executions = get_executions(
            resource_group=(
                arguments.resource_group
            ),
            job_name=(
                arguments.job_name
            ),
        )

        validation = validate_job(
            job=job,
            executions=executions,
            expected_image=(
                arguments.expected_image
            ),
        )

        report = {
            "phase": "10K",
            "subphase": "10K-E",
            "generated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "DAILY_RETRAINING_JOB_VALIDATED"
                if validation["valid"]
                else "DAILY_RETRAINING_JOB_INVALID"
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
            "phase": "10K",
            "subphase": "10K-E",
            "generated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "DAILY_RETRAINING_JOB_VALIDATION_FAILED"
            ),
            "resource_group": (
                arguments.resource_group
            ),
            "job_name": (
                arguments.job_name
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