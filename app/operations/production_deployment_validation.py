"""Validate the complete Phase 10M production deployment."""

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
    / "production_deployment_validation_report.json"
)

EXPECTED_JOBS = {
    "features": "job-pearls-aqi-features-prod",
    "forecast": "job-pearls-aqi-forecast-prod",
    "retraining": "job-pearls-aqi-retraining-prod",
    "monitoring": "job-pearls-aqi-monitoring-prod",
}


class ProductionDeploymentValidationError(
    RuntimeError
):
    """Raised when production deployment validation fails."""


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
        raise ProductionDeploymentValidationError(
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


def request_json(
    url: str,
) -> tuple[int, Any]:
    request = urllib.request.Request(
        url=url,
        headers={
            "Accept": "application/json",
            "User-Agent": (
                "pearls-aqi-production-validator/1.0"
            ),
        },
        method="GET",
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

    try:
        payload = json.loads(
            body.decode(
                "utf-8"
            )
        )
    except json.JSONDecodeError:
        payload = body.decode(
            "utf-8",
            errors="replace",
        )

    return status, payload


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
        item
        for item in executions
        if isinstance(
            item,
            dict,
        )
    ]

    valid.sort(
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
        raise ProductionDeploymentValidationError(
            f"Blob is not a JSON object: {name}"
        )

    return payload


def validate_deployment(
    *,
    resource_group: str,
    environment_resource_group: str,
    environment_name: str,
    identity_name: str,
    storage_account: str,
    production_container: str,
    staging_container: str,
    api_name: str,
    dashboard_name: str,
    release_sha: str,
) -> dict[str, Any]:

    checks: dict[str, bool] = {}

    # ------------------------------------------------------------
    # Infrastructure
    # ------------------------------------------------------------

    group = run_json(
        [
            "az",
            "group",
            "show",
            "--name",
            resource_group,
        ]
    )

    environment = run_json(
        [
            "az",
            "containerapp",
            "env",
            "show",
            "--resource-group",
            environment_resource_group,
            "--name",
            environment_name,
        ]
    )

    identity = run_json(
        [
            "az",
            "identity",
            "show",
            "--resource-group",
            resource_group,
            "--name",
            identity_name,
        ]
    )

    checks[
        "resource_group_exists"
    ] = (
        group.get("name")
        == resource_group
    )

    checks[
        "shared_environment_provisioned"
    ] = (
        environment.get(
            "properties",
            {},
        ).get(
            "provisioningState"
        )
        == "Succeeded"
    )

    checks[
        "production_identity_exists"
    ] = bool(
        identity.get(
            "principalId"
        )
    )

    # ------------------------------------------------------------
    # API
    # ------------------------------------------------------------

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

    api_properties = api.get(
        "properties",
        {},
    )

    api_containers = (
        api_properties.get(
            "template",
            {},
        ).get(
            "containers",
            [],
        )
    )

    if not api_containers:
        raise ProductionDeploymentValidationError(
            "Production API contains no container."
        )

    api_container = api_containers[0]

    api_fqdn = (
        api_properties.get(
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

    if not api_fqdn:
        raise ProductionDeploymentValidationError(
            "Production API has no FQDN."
        )

    api_url = (
        f"https://{api_fqdn}"
    )

    expected_api_image = (
        "walpole.azurecr.io/"
        f"pearls-aqi/api:{release_sha}"
    )

    live_status, live_payload = (
        request_json(
            f"{api_url}/api/v1/health/live"
        )
    )

    ready_status, ready_payload = (
        request_json(
            f"{api_url}/api/v1/health/ready"
        )
    )

    forecast_status, forecast_payload = (
        request_json(
            f"{api_url}/api/v1/forecast"
        )
    )

    checks[
        "api_provisioned"
    ] = (
        api_properties.get(
            "provisioningState"
        )
        == "Succeeded"
    )

    checks[
        "api_image_matches_release"
    ] = (
        api_container.get(
            "image"
        )
        == expected_api_image
    )

    checks[
        "api_live"
    ] = (
        live_status == 200
        and isinstance(
            live_payload,
            dict,
        )
        and live_payload.get(
            "status"
        )
        == "ALIVE"
    )

    checks[
        "api_ready"
    ] = (
        ready_status == 200
    )

    rows = (
        forecast_payload.get(
            "hourly_forecast"
        )
        if isinstance(
            forecast_payload,
            dict,
        )
        else None
    )

    checks[
        "forecast_endpoint_healthy"
    ] = (
        forecast_status == 200
        and isinstance(
            rows,
            list,
        )
        and len(rows) == 72
    )

    checks[
        "forecast_freshness_present"
    ] = (
        isinstance(
            forecast_payload,
            dict,
        )
        and isinstance(
            forecast_payload.get(
                "freshness"
            ),
            dict,
        )
    )

    # ------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------

    dashboard = run_json(
        [
            "az",
            "containerapp",
            "show",
            "--resource-group",
            resource_group,
            "--name",
            dashboard_name,
        ]
    )

    dashboard_properties = (
        dashboard.get(
            "properties",
            {},
        )
    )

    dashboard_containers = (
        dashboard_properties.get(
            "template",
            {},
        ).get(
            "containers",
            [],
        )
    )

    if not dashboard_containers:
        raise ProductionDeploymentValidationError(
            "Production dashboard has no container."
        )

    dashboard_container = (
        dashboard_containers[0]
    )

    dashboard_fqdn = (
        dashboard_properties.get(
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

    if not dashboard_fqdn:
        raise ProductionDeploymentValidationError(
            "Production dashboard has no FQDN."
        )

    dashboard_url = (
        f"https://{dashboard_fqdn}"
    )

    expected_dashboard_image = (
        "walpole.azurecr.io/"
        f"pearls-aqi/dashboard:{release_sha}"
    )

    def request_text(
        url: str,
    ) -> tuple[int, str]:
        request = urllib.request.Request(
            url=url,
            headers={
                "User-Agent": (
                    "pearls-aqi-production-validator/1.0"
                ),
            },
            method="GET",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=30,
            ) as response:
                return (
                    int(response.status),
                    response.read().decode(
                        "utf-8",
                        errors="replace",
                    ),
                )

        except urllib.error.HTTPError as error:
            return (
                int(error.code),
                error.read().decode(
                    "utf-8",
                    errors="replace",
                ),
            )

    dashboard_health_status, dashboard_health_body = (
        request_text(
            f"{dashboard_url}"
            "/_stcore/health"
        )
    )

    checks[
        "dashboard_provisioned"
    ] = (
        dashboard_properties.get(
            "provisioningState"
        )
        == "Succeeded"
    )

    checks[
        "dashboard_image_matches_release"
    ] = (
        dashboard_container.get(
            "image"
        )
        == expected_dashboard_image
    )

    checks[
        "dashboard_healthy"
    ] = (
        dashboard_health_status == 200
        and dashboard_health_body.strip().lower()
        == "ok"
    )


    # ------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------

    jobs: dict[str, Any] = {}

    expected_pipeline_image = (
        "walpole.azurecr.io/"
        f"pearls-aqi/pipeline:{release_sha}"
    )

    for logical_name, job_name in (
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
                job_name,
            ]
        )

        properties = job.get(
            "properties",
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
            raise ProductionDeploymentValidationError(
                f"{job_name} contains no container."
            )

        container = containers[0]

        execution = (
            latest_execution(
                resource_group=(
                    resource_group
                ),
                job_name=job_name,
            )
        )

        execution_status = (
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
            f"{logical_name}_job_provisioned"
        ] = (
            properties.get(
                "provisioningState"
            )
            == "Succeeded"
        )

        checks[
            f"{logical_name}_job_image_matches"
        ] = (
            container.get(
                "image"
            )
            == expected_pipeline_image
        )

        checks[
            f"{logical_name}_latest_execution_succeeded"
        ] = (
            execution_status
            == "Succeeded"
        )

        jobs[
            logical_name
        ] = {
            "name": job_name,
            "latest_execution": (
                execution.get(
                    "name"
                )
                if execution
                else None
            ),
            "status": execution_status,
        }

    # ------------------------------------------------------------
    # Production AQI artifacts
    # ------------------------------------------------------------

    aqi_pointer = (
        download_json_blob(
            account=storage_account,
            container=production_container,
            name=(
                "aqi/latest/"
                "pointer.json"
            ),
            destination=Path(
                "/tmp/final-prod-aqi-pointer.json"
            ),
        )
    )

    checks[
        "production_aqi_pointer_valid"
    ] = (
        aqi_pointer.get(
            "artifact_type"
        )
        == "aqi"
        and aqi_pointer.get(
            "validation_status"
        )
        == "AQI_ALERT_PIPELINE_APPROVED"
    )

    # ------------------------------------------------------------
    # Monitoring artifacts
    # ------------------------------------------------------------

    health_pointer = (
        download_json_blob(
            account=storage_account,
            container=production_container,
            name=(
                "production-health/"
                "latest/pointer.json"
            ),
            destination=Path(
                "/tmp/final-prod-health-pointer.json"
            ),
        )
    )

    checks[
        "production_health_pointer_valid"
    ] = (
        health_pointer.get(
            "artifact_type"
        )
        == "production-health"
        and health_pointer.get(
            "validation_status"
        )
        == "PRODUCTION_HEALTH_RECORDED"
    )

    # ------------------------------------------------------------
    # Notification outbox
    # ------------------------------------------------------------

    outbox = (
        download_json_blob(
            account=storage_account,
            container=production_container,
            name=(
                "production-health/"
                "notifications/outbox.json"
            ),
            destination=Path(
                "/tmp/final-prod-health-outbox.json"
            ),
        )
    )

    checks[
        "notification_outbox_valid"
    ] = (
        isinstance(
            outbox.get(
                "pending"
            ),
            list,
        )
        and isinstance(
            outbox.get(
                "pending_count"
            ),
            int,
        )
    )

    notification_status = {
        "delivery_required_for_phase_10m_i": False,
        "permanent_delivery_configured": False,
        "pending_count": outbox.get(
            "pending_count"
        ),
        "outbox_empty": (
            outbox.get(
                "pending_count"
            )
            == 0
        ),
        "note": (
            "External notification delivery is "
            "temporarily excluded from Phase 10M-I "
            "deployment validity. Permanent webhook "
            "or email delivery will be configured later."
        ),
    }

    # ------------------------------------------------------------
    # Staging / production isolation
    # ------------------------------------------------------------

    staging_pointer = (
        download_json_blob(
            account=storage_account,
            container=staging_container,
            name=(
                "aqi/latest/"
                "pointer.json"
            ),
            destination=Path(
                "/tmp/final-staging-aqi-pointer.json"
            ),
        )
    )

    checks[
        "staging_and_production_containers_differ"
    ] = (
        staging_container
        != production_container
    )

    checks[
        "staging_pointer_exists_independently"
    ] = (
        staging_pointer.get(
            "artifact_type"
        )
        == "aqi"
    )

    # Different run IDs are expected in normal operation.
    checks[
        "staging_and_production_runs_are_independent"
    ] = (
        staging_pointer.get(
            "run_id"
        )
        != aqi_pointer.get(
            "run_id"
        )
    )

    return {
        "valid": all(
            checks.values()
        ),
        "checks": checks,
        "release_sha": release_sha,
        "notifications": notification_status,
        "production": {
            "api_url": api_url,
            "dashboard_url": (
                dashboard_url
            ),
            "aqi_run_id": (
                aqi_pointer.get(
                    "run_id"
                )
            ),
            "health_run_id": (
                health_pointer.get(
                    "run_id"
                )
            ),
            "forecast_rows": (
                len(rows)
                if isinstance(
                    rows,
                    list,
                )
                else None
            ),
            "readiness_status": (
                ready_status
            ),
            "readiness_payload": (
                ready_payload
            ),
        },
        "jobs": jobs,
        "isolation": {
            "staging_container": (
                staging_container
            ),
            "production_container": (
                production_container
            ),
            "staging_run_id": (
                staging_pointer.get(
                    "run_id"
                )
            ),
            "production_run_id": (
                aqi_pointer.get(
                    "run_id"
                )
            ),
        },
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
        default="rg-pearls-aqi-prod",
    )

    parser.add_argument(
        "--environment-resource-group",
        default="rg-pearls-aqi-staging",
    )

    parser.add_argument(
        "--environment-name",
        default="cae-pearls-aqi-staging",
    )

    parser.add_argument(
        "--identity-name",
        default="id-pearls-aqi-prod",
    )

    parser.add_argument(
        "--storage-account",
        default="stpearlsaqiriyan",
    )

    parser.add_argument(
        "--production-container",
        default="artifacts-prod",
    )

    parser.add_argument(
        "--staging-container",
        default="artifacts",
    )

    parser.add_argument(
        "--api-name",
        default="ca-pearls-aqi-api-prod",
    )

    parser.add_argument(
        "--dashboard-name",
        default=(
            "ca-pearls-aqi-dashboard-prod"
        ),
    )

    parser.add_argument(
        "--release-sha",
        required=True,
    )

    arguments = parser.parse_args()

    try:
        validation = (
            validate_deployment(
                resource_group=(
                    arguments.resource_group
                ),
                environment_resource_group=(
                    arguments.environment_resource_group
                ),
                environment_name=(
                    arguments.environment_name
                ),
                identity_name=(
                    arguments.identity_name
                ),
                storage_account=(
                    arguments.storage_account
                ),
                production_container=(
                    arguments.production_container
                ),
                staging_container=(
                    arguments.staging_container
                ),
                api_name=(
                    arguments.api_name
                ),
                dashboard_name=(
                    arguments.dashboard_name
                ),
                release_sha=(
                    arguments.release_sha
                ),
            )
        )

        report = {
            "phase": "10M",
            "subphase": "10M-I",
            "generated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "PRODUCTION_DEPLOYMENT_VALIDATED"
                if validation["valid"]
                else "PRODUCTION_DEPLOYMENT_INVALID"
            ),
            "production_live": (
                validation["valid"]
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
            "subphase": "10M-I",
            "generated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "PRODUCTION_DEPLOYMENT_VALIDATION_FAILED"
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