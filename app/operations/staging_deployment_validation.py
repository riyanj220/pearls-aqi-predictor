"""Validate the Phase 10I Azure staging deployment."""

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
    / "staging_deployment_report.json"
)


class StagingDeploymentError(RuntimeError):
    """Raised when staging deployment validation fails."""


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


def get_container_app(
    *,
    resource_group: str,
    app_name: str,
) -> dict[str, Any]:
    """Read one Container App configuration."""

    raw_payload = run_command(
        [
            "az",
            "containerapp",
            "show",
            "--name",
            app_name,
            "--resource-group",
            resource_group,
            "--output",
            "json",
        ]
    )

    return json.loads(raw_payload)


def request_json(
    url: str,
    *,
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    """Request one JSON staging endpoint."""

    try:
        with urllib.request.urlopen(
            url,
            timeout=timeout_seconds,
        ) as response:
            payload = json.loads(
                response.read().decode("utf-8")
            )
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
    ) as error:
        raise StagingDeploymentError(
            f"Could not validate endpoint: {url}"
        ) from error

    if not isinstance(payload, dict):
        raise StagingDeploymentError(
            f"Expected JSON object from: {url}"
        )

    return payload


def build_report(
    *,
    resource_group: str,
    api_app: str,
    dashboard_app: str,
    image_tag: str,
) -> dict[str, Any]:
    """Validate staging apps and endpoints."""

    api = get_container_app(
        resource_group=resource_group,
        app_name=api_app,
    )

    dashboard = get_container_app(
        resource_group=resource_group,
        app_name=dashboard_app,
    )

    api_fqdn = (
        api["properties"]
        ["configuration"]
        ["ingress"]
        ["fqdn"]
    )

    dashboard_fqdn = (
        dashboard["properties"]
        ["configuration"]
        ["ingress"]
        ["fqdn"]
    )

    live_payload = request_json(
        f"https://{api_fqdn}/api/v1/health/live"
    )

    ready_payload = request_json(
        f"https://{api_fqdn}/api/v1/health/ready"
    )

    forecast_payload = request_json(
        f"https://{api_fqdn}/api/v1/forecast"
    )

    forecast_rows = len(
        forecast_payload.get(
            "hourly_forecast",
            [],
        )
    )

    api_image = (
        api["properties"]
        ["template"]
        ["containers"][0]
        ["image"]
    )

    dashboard_image = (
        dashboard["properties"]
        ["template"]
        ["containers"][0]
        ["image"]
    )

    checks = {
        "api_live": (
            live_payload.get("status")
            == "ALIVE"
        ),
        "api_ready": (
            ready_payload.get("status")
            in {
                "READY",
                "READY_WITH_LIMITATIONS",
            }
        ),
        "forecast_has_72_rows": (
            forecast_rows == 72
        ),
        "api_uses_expected_tag": (
            api_image.endswith(
                f":{image_tag}"
            )
        ),
        "dashboard_uses_expected_tag": (
            dashboard_image.endswith(
                f":{image_tag}"
            )
        ),
        "api_external_ingress": (
            api["properties"]
            ["configuration"]
            ["ingress"]
            ["external"]
            is True
        ),
        "dashboard_external_ingress": (
            dashboard["properties"]
            ["configuration"]
            ["ingress"]
            ["external"]
            is True
        ),
    }

    approved = all(checks.values())

    return {
        "phase": "10I",
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "status": (
            "STAGING_DEPLOYMENT_VALIDATED"
            if approved
            else "STAGING_DEPLOYMENT_INVALID"
        ),
        "approved": approved,
        "resource_group": resource_group,
        "image_tag": image_tag,
        "api": {
            "name": api_app,
            "fqdn": api_fqdn,
            "image": api_image,
            "readiness_status": (
                ready_payload.get("status")
            ),
            "forecast_rows": forecast_rows,
            "pipeline_run_id": (
                forecast_payload.get(
                    "pipeline_run_id"
                )
            ),
        },
        "dashboard": {
            "name": dashboard_app,
            "fqdn": dashboard_fqdn,
            "image": dashboard_image,
        },
        "checks": checks,
        "scheduled_jobs_created": False,
        "production_deployment_performed": False,
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Save the staging validation report."""

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

    temporary_path.replace(REPORT_PATH)

    return REPORT_PATH


def main() -> int:
    """Run staging deployment validation."""

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--resource-group",
        required=True,
    )

    parser.add_argument(
        "--api-app",
        required=True,
    )

    parser.add_argument(
        "--dashboard-app",
        required=True,
    )

    parser.add_argument(
        "--image-tag",
        required=True,
    )

    arguments = parser.parse_args()

    try:
        report = build_report(
            resource_group=(
                arguments.resource_group
            ),
            api_app=arguments.api_app,
            dashboard_app=(
                arguments.dashboard_app
            ),
            image_tag=arguments.image_tag,
        )

        exit_code = (
            0
            if report["approved"]
            else 1
        )

    except Exception as error:
        report = {
            "phase": "10I",
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": (
                "STAGING_DEPLOYMENT_VALIDATION_FAILED"
            ),
            "approved": False,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "scheduled_jobs_created": False,
            "production_deployment_performed": False,
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