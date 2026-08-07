"""Validate the first complete production execution cycle."""

from __future__ import annotations

import argparse
import json
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]

REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "production_initial_publication_validation_report.json"
)


EXPECTED_JOBS = [
    "job-pearls-aqi-features-prod",
    "job-pearls-aqi-forecast-prod",
    "job-pearls-aqi-retraining-prod",
    "job-pearls-aqi-monitoring-prod",
]


class InitialProductionValidationError(
    RuntimeError
):
    """Raised when initial production publication is invalid."""


def run_command(
    arguments: list[str],
) -> str:

    completed = subprocess.run(
        arguments,
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        raise InitialProductionValidationError(
            "Command failed.\n"
            f"Command: {' '.join(arguments)}\n"
            f"Error: {completed.stderr.strip()}"
        )

    return completed.stdout.strip()


def run_json(
    arguments: list[str],
) -> Any:

    output = run_command(
        [
            *arguments,
            "--output",
            "json",
        ]
    )

    return json.loads(output)


def latest_execution(
    *,
    resource_group: str,
    job_name: str,
) -> dict[str, Any] | None:

    executions = run_json(
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

    if not isinstance(
        executions,
        list,
    ):
        return None

    valid = [
        execution
        for execution in executions
        if isinstance(
            execution,
            dict,
        )
    ]

    valid.sort(
        key=lambda execution: str(
            execution.get(
                "properties",
                {},
            ).get(
                "startTime",
                "",
            )
        ),
        reverse=True,
    )

    return (
        valid[0]
        if valid
        else None
    )


def download_json_blob(
    *,
    account: str,
    container: str,
    name: str,
    destination: Path,
) -> dict[str, Any]:

    run_command(
        [
            "az",
            "storage",
            "blob",
            "download",
            "--account-name",
            account,
            "--container-name",
            container,
            "--name",
            name,
            "--auth-mode",
            "login",
            "--file",
            str(destination),
            "--overwrite",
            "--only-show-errors",
        ]
    )

    payload = json.loads(
        destination.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(
        payload,
        dict,
    ):
        raise InitialProductionValidationError(
            f"Blob is not a JSON object: {name}"
        )

    return payload


def request_json(
    url: str,
) -> tuple[int, dict[str, Any]]:

    request = urllib.request.Request(
        url=url,
        headers={
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:

            status = int(
                response.status
            )

            body = response.read()

    except urllib.error.HTTPError as error:

        status = int(
            error.code
        )

        body = error.read()

    payload = json.loads(
        body.decode(
            "utf-8"
        )
    )

    if not isinstance(
        payload,
        dict,
    ):
        raise InitialProductionValidationError(
            f"Response is not JSON object: {url}"
        )

    return status, payload


def validate_initial_production(
    *,
    resource_group: str,
    storage_account: str,
    storage_container: str,
    api_name: str,
) -> dict[str, Any]:

    checks: dict[
        str,
        bool,
    ] = {}

    job_results: dict[
        str,
        Any,
    ] = {}

    for job_name in EXPECTED_JOBS:

        execution = (
            latest_execution(
                resource_group=(
                    resource_group
                ),
                job_name=job_name,
            )
        )

        status = (
            execution.get(
                "properties",
                {},
            ).get(
                "status"
            )
            if execution
            else None
        )

        checks[
            f"{job_name}_executed"
        ] = (
            execution is not None
        )

        checks[
            f"{job_name}_succeeded"
        ] = (
            status == "Succeeded"
        )

        job_results[
            job_name
        ] = {
            "execution_name": (
                execution.get(
                    "name"
                )
                if execution
                else None
            ),
            "status": status,
        }

    aqi_pointer = (
        download_json_blob(
            account=storage_account,
            container=storage_container,
            name=(
                "aqi/latest/"
                "pointer.json"
            ),
            destination=Path(
                "/tmp/"
                "production-initial-aqi-pointer.json"
            ),
        )
    )

    health_pointer = (
        download_json_blob(
            account=storage_account,
            container=storage_container,
            name=(
                "production-health/"
                "latest/pointer.json"
            ),
            destination=Path(
                "/tmp/"
                "production-initial-health-pointer.json"
            ),
        )
    )

    checks[
        "aqi_pointer_created"
    ] = (
        aqi_pointer.get(
            "artifact_type"
        )
        == "aqi"
    )

    checks[
        "aqi_pointer_approved"
    ] = (
        aqi_pointer.get(
            "validation_status"
        )
        == "AQI_ALERT_PIPELINE_APPROVED"
    )

    checks[
        "health_pointer_created"
    ] = (
        health_pointer.get(
            "artifact_type"
        )
        == "production-health"
    )

    checks[
        "health_pointer_recorded"
    ] = (
        health_pointer.get(
            "validation_status"
        )
        == "PRODUCTION_HEALTH_RECORDED"
    )


    api = run_json(
        [
            "az",
            "containerapp",
            "show",
            "--resource-group",
            resource_group,
            "--name",
            api_name,
        ]
    )

    fqdn = (
        api.get(
            "properties",
            {},
        )
        .get(
            "configuration",
            {},
        )
        .get(
            "ingress",
            {},
        )
        .get(
            "fqdn"
        )
    )

    if not fqdn:
        raise InitialProductionValidationError(
            "Production API has no FQDN."
        )

    base_url = (
        f"https://{fqdn}"
    )

    ready_status, ready_payload = (
        request_json(
            f"{base_url}"
            "/api/v1/health/ready"
        )
    )

    forecast_status, forecast_payload = (
        request_json(
            f"{base_url}"
            "/api/v1/forecast"
        )
    )

    checks[
        "api_is_ready"
    ] = (
        ready_status == 200
    )

    checks[
        "forecast_endpoint_succeeds"
    ] = (
        forecast_status == 200
    )

    checks[
        "readiness_reports_forecast"
    ] = bool(
        ready_payload.get(
            "forecast_available"
        )
    )

    return {
        "valid": all(
            checks.values()
        ),
        "checks": checks,
        "jobs": job_results,
        "aqi_pointer": {
            "run_id": (
                aqi_pointer.get(
                    "run_id"
                )
            ),
            "validation_status": (
                aqi_pointer.get(
                    "validation_status"
                )
            ),
            "published_at_utc": (
                aqi_pointer.get(
                    "published_at_utc"
                )
            ),
        },
        "health_pointer": {
            "run_id": (
                health_pointer.get(
                    "run_id"
                )
            ),
            "validation_status": (
                health_pointer.get(
                    "validation_status"
                )
            ),
            "published_at_utc": (
                health_pointer.get(
                    "published_at_utc"
                )
            ),
        },
        "api": {
            "url": base_url,
            "readiness_status": (
                ready_status
            ),
            "forecast_status": (
                forecast_status
            ),
        },
        "forecast_response_keys": (
            sorted(
                forecast_payload.keys()
            )
        ),
    }


def save_report(
    report: dict[str, Any],
) -> Path:

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

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--resource-group",
        default=(
            "rg-pearls-aqi-prod"
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
        default="artifacts-prod",
    )

    parser.add_argument(
        "--api-name",
        default=(
            "ca-pearls-aqi-api-prod"
        ),
    )

    arguments = parser.parse_args()

    try:

        validation = (
            validate_initial_production(
                resource_group=(
                    arguments.resource_group
                ),
                storage_account=(
                    arguments.storage_account
                ),
                storage_container=(
                    arguments.storage_container
                ),
                api_name=(
                    arguments.api_name
                ),
            )
        )

        report = {
            "phase": "10M",
            "subphase": "10M-H",
            "generated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "INITIAL_PRODUCTION_PUBLICATION_VALIDATED"
                if validation[
                    "valid"
                ]
                else (
                    "INITIAL_PRODUCTION_PUBLICATION_INVALID"
                )
            ),
            "production_live": (
                validation[
                    "valid"
                ]
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
            "phase": "10M",
            "subphase": "10M-H",
            "generated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "INITIAL_PRODUCTION_PUBLICATION_VALIDATION_FAILED"
            ),
            "production_live": False,
            "valid": False,
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(
                error
            ),
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
    raise SystemExit(main())