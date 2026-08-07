"""Validate the initial production Streamlit deployment."""

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
    / "production_dashboard_validation_report.json"
)


class ProductionDashboardValidationError(
    RuntimeError
):
    """Raised when production dashboard validation fails."""


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
        raise ProductionDashboardValidationError(
            "Command failed.\n"
            f"Command: {' '.join(arguments)}\n"
            f"Error: {completed.stderr.strip()}"
        )

    return completed.stdout.strip()


def run_json_command(
    arguments: list[str],
) -> Any:
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
        raise ProductionDashboardValidationError(
            "Command did not return valid JSON."
        ) from error


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


def environment_mapping(
    app: dict[str, Any],
) -> dict[str, dict[str, Any]]:

    containers = (
        app.get(
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
        raise ProductionDashboardValidationError(
            "Container App contains no container."
        )

    return {
        str(item.get("name")): item
        for item in containers[0].get(
            "env",
            [],
        )
        if item.get("name")
    }


def validate_dashboard(
    *,
    resource_group: str,
    dashboard_name: str,
    api_name: str,
    expected_image: str,
) -> dict[str, Any]:

    dashboard = run_json_command(
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

    api = run_json_command(
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

    dashboard_properties = dashboard.get(
        "properties",
        {},
    )

    dashboard_configuration = (
        dashboard_properties.get(
            "configuration",
            {},
        )
    )

    dashboard_ingress = (
        dashboard_configuration.get(
            "ingress",
            {},
        )
    )

    containers = (
        dashboard_properties.get(
            "template",
            {},
        ).get(
            "containers",
            [],
        )
    )

    if not containers:
        raise ProductionDashboardValidationError(
            "Dashboard contains no container."
        )

    container = containers[0]

    dashboard_environment = (
        environment_mapping(
            dashboard
        )
    )

    api_environment = (
        environment_mapping(
            api
        )
    )

    dashboard_fqdn = (
        dashboard_ingress.get(
            "fqdn"
        )
    )

    if not dashboard_fqdn:
        raise ProductionDashboardValidationError(
            "Dashboard has no FQDN."
        )

    dashboard_url = (
        f"https://{dashboard_fqdn}"
    )

    expected_api_fqdn = (
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

    if not expected_api_fqdn:
        raise ProductionDashboardValidationError(
            "Production API has no FQDN."
        )

    expected_api_base_url = (
        f"https://{expected_api_fqdn}"
        "/api/v1"
    )

    expected_dashboard_origin = (
        f"https://{dashboard_fqdn}"
    )

    health_status, health_body = (
        request_text(
            f"{dashboard_url}"
            "/_stcore/health"
        )
    )

    page_status, page_body = (
        request_text(
            dashboard_url
        )
    )

    cors_value = (
        api_environment.get(
            "PEARLS_API_ALLOWED_CORS_ORIGINS",
            {},
        ).get(
            "value"
        )
    )

    expected_cors_value = json.dumps(
        [
            expected_dashboard_origin
        ],
        separators=(",", ":"),
    )

    checks = {
        "provisioning_succeeded": (
            dashboard_properties.get(
                "provisioningState"
            )
            == "Succeeded"
        ),

        "external_ingress_enabled": (
            dashboard_ingress.get(
                "external"
            )
            is True
        ),

        "target_port_is_8501": (
            dashboard_ingress.get(
                "targetPort"
            )
            == 8501
        ),

        "immutable_image_matches": (
            container.get(
                "image"
            )
            == expected_image
        ),

        "dashboard_environment_is_production": (
            dashboard_environment.get(
                "DASHBOARD_ENVIRONMENT",
                {},
            ).get(
                "value"
            )
            == "production"
        ),

        "api_base_url_matches": (
            dashboard_environment.get(
                "FASTAPI_BASE_URL",
                {},
            ).get(
                "value"
            )
            == expected_api_base_url
        ),

        "request_timeout_is_10": (
            dashboard_environment.get(
                "DASHBOARD_REQUEST_TIMEOUT_SECONDS",
                {},
            ).get(
                "value"
            )
            == "10"
        ),

        "cache_ttl_is_60": (
            dashboard_environment.get(
                "DASHBOARD_CACHE_TTL_SECONDS",
                {},
            ).get(
                "value"
            )
            == "60"
        ),

        "timezone_is_karachi": (
            dashboard_environment.get(
                "DASHBOARD_DEFAULT_TIMEZONE",
                {},
            ).get(
                "value"
            )
            == "Asia/Karachi"
        ),

        "streamlit_health_is_healthy": (
            health_status == 200
        ),

        "dashboard_page_is_reachable": (
            page_status == 200
            and bool(
                page_body.strip()
            )
        ),

        "api_cors_contains_dashboard_origin": (
            cors_value
            == expected_cors_value
        ),
    }

    return {
        "valid": all(
            checks.values()
        ),
        "checks": checks,

        "dashboard": {
            "name": dashboard_name,
            "fqdn": dashboard_fqdn,
            "url": dashboard_url,
            "image": container.get(
                "image"
            ),
            "health_status": (
                health_status
            ),
        },

        "api_dependency": {
            "name": api_name,
            "base_url": (
                expected_api_base_url
            ),
            "cors_origin": (
                expected_dashboard_origin
            ),
        },

        "initial_production_forecast_expected": (
            False
        ),
    }


def save_report(
    report: dict[str, Any],
) -> Path:

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

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--resource-group",
        default="rg-pearls-aqi-prod",
    )

    parser.add_argument(
        "--dashboard-name",
        default=(
            "ca-pearls-aqi-dashboard-prod"
        ),
    )

    parser.add_argument(
        "--api-name",
        default=(
            "ca-pearls-aqi-api-prod"
        ),
    )

    parser.add_argument(
        "--release-sha",
        required=True,
    )

    arguments = parser.parse_args()

    expected_image = (
        "walpole.azurecr.io/"
        "pearls-aqi/dashboard:"
        f"{arguments.release_sha}"
    )

    try:
        validation = (
            validate_dashboard(
                resource_group=(
                    arguments.resource_group
                ),
                dashboard_name=(
                    arguments.dashboard_name
                ),
                api_name=(
                    arguments.api_name
                ),
                expected_image=(
                    expected_image
                ),
            )
        )

        report = {
            "phase": "10M",
            "subphase": "10M-F",
            "generated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "PRODUCTION_DASHBOARD_DEPLOYMENT_VALIDATED"
                if validation["valid"]
                else (
                    "PRODUCTION_DASHBOARD_DEPLOYMENT_INVALID"
                )
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
            "subphase": "10M-F",
            "generated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "PRODUCTION_DASHBOARD_DEPLOYMENT_VALIDATION_FAILED"
            ),
            "valid": False,
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(
                error
            ),
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