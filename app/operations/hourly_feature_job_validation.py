"""Validate the Phase 10K hourly Azure feature job."""

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
    / "hourly_feature_job_report.json"
)


class HourlyFeatureJobValidationError(
    RuntimeError
):
    """Raised when the hourly job configuration is invalid."""


def run_command(
    arguments: list[str],
) -> str:
    """Run one Azure CLI command."""

    result = subprocess.run(
        arguments,
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    return result.stdout.strip()


def load_job(
    *,
    job_name: str,
    resource_group: str,
) -> dict[str, Any]:
    """Load one Container Apps Job."""

    payload = run_command(
        [
            "az",
            "containerapp",
            "job",
            "show",
            "--name",
            job_name,
            "--resource-group",
            resource_group,
            "--output",
            "json",
        ]
    )

    result = json.loads(payload)

    if not isinstance(result, dict):
        raise HourlyFeatureJobValidationError(
            "Azure job response is not an object."
        )

    return result


def load_latest_execution(
    *,
    job_name: str,
    resource_group: str,
) -> dict[str, Any]:
    """Load the newest job execution."""

    payload = run_command(
        [
            "az",
            "containerapp",
            "job",
            "execution",
            "list",
            "--name",
            job_name,
            "--resource-group",
            resource_group,
            "--output",
            "json",
        ]
    )

    executions = json.loads(payload)

    if (
        not isinstance(executions, list)
        or not executions
    ):
        raise HourlyFeatureJobValidationError(
            "No hourly feature executions exist."
        )

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

    return executions[0]


def env_mapping(
    job: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Return environment variables by name."""

    containers = (
        job.get("properties", {})
        .get("template", {})
        .get("containers", [])
    )

    if not containers:
        raise HourlyFeatureJobValidationError(
            "Hourly job contains no container."
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


def build_report(
    *,
    job_name: str,
    resource_group: str,
    expected_image_tag: str,
) -> dict[str, Any]:
    """Validate the deployed hourly job."""

    job = load_job(
        job_name=job_name,
        resource_group=resource_group,
    )

    execution = load_latest_execution(
        job_name=job_name,
        resource_group=resource_group,
    )

    properties = job["properties"]
    configuration = properties[
        "configuration"
    ]
    template = properties["template"]
    container = template["containers"][0]

    environment = env_mapping(job)

    execution_status = (
        execution.get("properties", {})
        .get("status")
    )

    image = str(container.get("image", ""))

    schedule_configuration = (
        configuration.get(
            "scheduleTriggerConfig",
            {},
        )
    )

    configured_parallelism = (
        schedule_configuration.get(
            "parallelism"
        )
    )

    if configured_parallelism is None:
        configured_parallelism = (
            template.get("parallelism")
        )

    # Azure may omit the field when the effective value is the default of one.
    effective_parallelism = (
        1
        if configured_parallelism is None
        else configured_parallelism
    )

    container_command = (
        container.get("command")
        or []
    )

    container_arguments = (
        container.get("args")
        or []
    )

    uses_python_module_command = (
        container_command == ["python"]
        and container_arguments
        == [
            "-m",
            "app.pipelines.hourly_features",
        ]
    )

    uses_hourly_wrapper = (
        container_command
        == ["/app/bin/run_hourly_features"]
        and not container_arguments
    )

    checks = {
        "trigger_is_schedule": (
            configuration.get("triggerType")
            == "Schedule"
        ),
        "cron_is_hourly": (
            schedule_configuration.get(
                "cronExpression"
            )
            == "15 * * * *"
        ),
        "timeout_is_900_seconds": (
            configuration.get(
                "replicaTimeout"
            )
            == 900
        ),
        "retry_limit_is_one": (
            configuration.get(
                "replicaRetryLimit"
            )
            == 1
        ),
        "parallelism_is_one": (
            effective_parallelism == 1
        ),
        "hourly_entrypoint_is_valid": (
            uses_python_module_command
            or uses_hourly_wrapper
        ),

        "immutable_image_tag": (
            image.endswith(
                f":{expected_image_tag}"
            )
            and expected_image_tag
            != "latest"
        ),
        "feature_store_is_hopsworks": (
            environment.get(
                "FEATURE_STORE_BACKEND",
                {},
            ).get("value")
            == "hopsworks"
        ),
        "dry_run_is_disabled": (
            environment.get(
                "MLOPS_DRY_RUN",
                {},
            ).get("value")
            == "false"
        ),
        "openaq_uses_secret": (
            environment.get(
                "OPENAQ_API_KEY",
                {},
            ).get("secretRef")
            == "openaq-api-key"
        ),
        "hopsworks_uses_secret": (
            environment.get(
                "HOPSWORKS_API_KEY",
                {},
            ).get("secretRef")
            == "hopsworks-api-key"
        ),
        "latest_execution_succeeded": (
            execution_status
            == "Succeeded"
        ),
    }

    approved = all(checks.values())

    return {
        "phase": "10K",
        "subphase": "10K-B",
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "status": (
            "HOURLY_FEATURE_JOB_VALIDATED"
            if approved
            else "HOURLY_FEATURE_JOB_INVALID"
        ),
        "approved": approved,
        "resource_group": resource_group,
        "job_name": job_name,
        "image": image,
        "schedule_utc": (
            configuration.get(
                "scheduleTriggerConfig",
                {},
            ).get(
                "cronExpression"
            )
        ),
        "latest_execution": {
            "name": execution.get("name"),
            "status": execution_status,
            "start_time": (
                execution.get(
                    "properties",
                    {},
                ).get(
                    "startTime"
                )
            ),
            "end_time": (
                execution.get(
                    "properties",
                    {},
                ).get(
                    "endTime"
                )
            ),
        },
        "checks": checks,
        "daily_retraining_job_created": False,
        "automatic_model_promotion_enabled": False,

        "container_execution": {
            "command": container_command,
            "args": container_arguments,
            "uses_python_module_command": (
                uses_python_module_command
            ),
            "uses_hourly_wrapper": (
                uses_hourly_wrapper
            ),
            "effective_parallelism": (
                effective_parallelism
            ),
        },
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Save the hourly-job validation report."""

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
            "Validate the scheduled hourly "
            "feature synchronization job."
        )
    )

    parser.add_argument(
        "--job-name",
        required=True,
    )

    parser.add_argument(
        "--resource-group",
        required=True,
    )

    parser.add_argument(
        "--expected-image-tag",
        required=True,
    )

    arguments = parser.parse_args()

    try:
        report = build_report(
            job_name=arguments.job_name,
            resource_group=(
                arguments.resource_group
            ),
            expected_image_tag=(
                arguments.expected_image_tag
            ),
        )

        exit_code = (
            0
            if report["approved"]
            else 1
        )

    except Exception as error:
        report = {
            "phase": "10K",
            "subphase": "10K-B",
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": (
                "HOURLY_FEATURE_JOB_VALIDATION_FAILED"
            ),
            "approved": False,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "daily_retraining_job_created": False,
            "automatic_model_promotion_enabled": False,
        }

        exit_code = 1

    report_path = save_report(report)

    print(
        json.dumps(
            report,
            indent=2,
            default=str,
        )
    )

    print("Report saved:", report_path)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())