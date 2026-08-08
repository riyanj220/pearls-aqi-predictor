"""Validate deployed production Container Apps Jobs."""

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
    / "production_jobs_validation_report.json"
)

EXPECTED_JOBS = {
    "features": {
        "name": "job-pearls-aqi-features-prod",
        "schedule": "15 * * * *",
        "timeout": 1800,
    },
    "forecast": {
        "name": "job-pearls-aqi-forecast-prod",
        "schedule": "0 */6 * * *",
        "timeout": 1800,
    },
    "retraining": {
        "name": "job-pearls-aqi-retraining-prod",
        "schedule": "30 3 * * *",
        "timeout": 3600,
    },
    "monitoring": {
        "name": "job-pearls-aqi-monitoring-prod",
        "schedule": "45 * * * *",
        "timeout": 600,
    },
}


class ProductionJobsValidationError(RuntimeError):
    """Raised when production job validation fails."""


def run_json(
    arguments: list[str],
) -> Any:
    completed = subprocess.run(
        [
            *arguments,
            "--output",
            "json",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        raise ProductionJobsValidationError(
            completed.stderr.strip()
        )

    return json.loads(
        completed.stdout
    )


def environment_mapping(
    job: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    containers = (
        job.get("properties", {})
        .get("template", {})
        .get("containers", [])
    )

    if not containers:
        raise ProductionJobsValidationError(
            "Job contains no container."
        )

    return {
        str(item.get("name")): item
        for item in containers[0].get(
            "env",
            [],
        )
        if item.get("name")
    }


def validate_jobs(
    *,
    resource_group: str,
    release_sha: str,
) -> dict[str, Any]:

    expected_image = (
        "walpole.azurecr.io/"
        f"pearls-aqi/pipeline:{release_sha}"
    )

    job_results: dict[str, Any] = {}
    all_checks: dict[str, bool] = {}

    for logical_name, expected in (
        EXPECTED_JOBS.items()
    ):
        job = run_json(
            [
                "az",
                "containerapp",
                "job",
                "show",
                "--resource-group",
                resource_group,
                "--name",
                expected["name"],
            ]
        )

        properties = job.get(
            "properties",
            {},
        )

        configuration = properties.get(
            "configuration",
            {},
        )

        schedule = configuration.get(
            "scheduleTriggerConfig",
            {},
        )

        containers = (
            properties.get(
                "template",
                {},
            ).get(
                "containers",
                [],
            )
        )

        if not containers:
            raise ProductionJobsValidationError(
                f"{expected['name']} has no container."
            )

        container = containers[0]

        environment = environment_mapping(
            job
        )

        checks = {
            "provisioned": (
                properties.get(
                    "provisioningState"
                )
                == "Succeeded"
            ),
            "schedule_trigger": (
                configuration.get(
                    "triggerType"
                )
                == "Schedule"
            ),
            "schedule_matches": (
                schedule.get(
                    "cronExpression"
                )
                == expected["schedule"]
            ),
            "timeout_matches": (
                configuration.get(
                    "replicaTimeout"
                )
                == expected["timeout"]
            ),
            "retry_limit_is_one": (
                configuration.get(
                    "replicaRetryLimit"
                )
                == 1
            ),
            "parallelism_is_one": (
                (
                    schedule.get(
                        "parallelism"
                    )
                    or 1
                )
                == 1
            ),
            "completion_count_is_one": (
                (
                    schedule.get(
                        "replicaCompletionCount"
                    )
                    or 1
                )
                == 1
            ),
            "immutable_image_matches": (
                container.get(
                    "image"
                )
                == expected_image
            ),
            "production_environment": (
                environment.get(
                    "APP_ENV",
                    {},
                ).get(
                    "value"
                )
                == "production"
            ),
        }

        if logical_name in {
            "forecast",
            "retraining",
            "monitoring",
        }:
            checks[
                "production_blob_container"
            ] = (
                environment.get(
                    "AZURE_STORAGE_CONTAINER",
                    {},
                ).get(
                    "value"
                )
                == "artifacts-prod"
            )

        if logical_name == "monitoring":
            checks[
                "monitor_targets_prod_rg"
            ] = (
                environment.get(
                    "PRODUCTION_RESOURCE_GROUP",
                    {},
                ).get(
                    "value"
                )
                == "rg-pearls-aqi-prod"
            )

            checks[
                "monitor_targets_prod_jobs"
            ] = (
                environment.get(
                    "FEATURE_JOB_NAME",
                    {},
                ).get(
                    "value"
                )
                == "job-pearls-aqi-features-prod"
                and environment.get(
                    "FORECAST_JOB_NAME",
                    {},
                ).get(
                    "value"
                )
                == "job-pearls-aqi-forecast-prod"
                and environment.get(
                    "RETRAINING_JOB_NAME",
                    {},
                ).get(
                    "value"
                )
                == "job-pearls-aqi-retraining-prod"
            )

        for check_name, value in checks.items():
            all_checks[
                f"{logical_name}_{check_name}"
            ] = value

        job_results[
            logical_name
        ] = {
            "name": expected["name"],
            "image": container.get(
                "image"
            ),
            "schedule": schedule.get(
                "cronExpression"
            ),
            "checks": checks,
        }

    return {
        "valid": all(
            all_checks.values()
        ),
        "checks": all_checks,
        "jobs": job_results,
        "release_sha": release_sha,
    }


def save_report(
    report: dict[str, Any],
) -> Path:

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = REPORT_PATH.with_suffix(
        ".json.tmp"
    )

    temporary.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    temporary.replace(
        REPORT_PATH
    )

    return REPORT_PATH


def main() -> int:

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--resource-group",
        default="rg-pearls-aqi-prod",
    )

    parser.add_argument(
        "--release-sha",
        required=True,
    )

    arguments = parser.parse_args()

    try:
        validation = validate_jobs(
            resource_group=(
                arguments.resource_group
            ),
            release_sha=(
                arguments.release_sha
            ),
        )

        report = {
            "phase": "10M",
            "subphase": "10M-G",
            "generated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "PRODUCTION_JOBS_VALIDATED"
                if validation["valid"]
                else "PRODUCTION_JOBS_INVALID"
            ),
            "manual_execution_complete": False,
            **validation,
        }

        exit_code = (
            0
            if validation["valid"]
            else 1
        )

    except Exception as error:
        report = {
            "phase": "10M",
            "subphase": "10M-G",
            "generated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "PRODUCTION_JOBS_VALIDATION_FAILED"
            ),
            "valid": False,
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(error),
        }

        exit_code = 1

    path = save_report(
        report
    )

    print(
        json.dumps(
            report,
            indent=2,
        )
    )

    print(
        "Report saved:",
        path,
    )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())