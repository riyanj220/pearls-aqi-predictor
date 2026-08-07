"""Validate initial production FastAPI deployment."""

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
    / "production_api_validation_report.json"
)


class ProductionAPIValidationError(
    RuntimeError
):
    """Raised when production API deployment is invalid."""


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
        raise ProductionAPIValidationError(
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

    return json.loads(output)


def request_json(
    url: str,
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url=url,
        headers={
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:
            status = response.status
            body = response.read()

    except urllib.error.HTTPError as error:
        status = error.code
        body = error.read()

    try:
        payload = json.loads(
            body.decode("utf-8")
        )
    except json.JSONDecodeError as error:
        raise ProductionAPIValidationError(
            f"Endpoint returned invalid JSON: {url}"
        ) from error

    if not isinstance(payload, dict):
        raise ProductionAPIValidationError(
            f"Endpoint response is not an object: {url}"
        )

    return status, payload


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
        raise ProductionAPIValidationError(
            "Production API has no container."
        )

    return {
        str(item.get("name")): item
        for item
        in containers[0].get(
            "env",
            [],
        )
        if item.get("name")
    }


def validate_api(
    *,
    resource_group: str,
    app_name: str,
    expected_image: str,
) -> dict[str, Any]:
    app = run_json_command(
        [
            "az",
            "containerapp",
            "show",
            "--resource-group",
            resource_group,
            "--name",
            app_name,
        ]
    )

    properties = app.get(
        "properties",
        {},
    )

    configuration = properties.get(
        "configuration",
        {},
    )

    ingress = configuration.get(
        "ingress",
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
        raise ProductionAPIValidationError(
            "Production API contains no container."
        )

    container = containers[0]

    environment = environment_mapping(
        app
    )

    fqdn = ingress.get(
        "fqdn"
    )

    if not fqdn:
        raise ProductionAPIValidationError(
            "Production API has no FQDN."
        )

    base_url = f"https://{fqdn}"

    live_status, live_payload = request_json(
        f"{base_url}/api/v1/health/live"
    )

    ready_status, ready_payload = request_json(
        f"{base_url}/api/v1/health/ready"
    )

    _, openapi = request_json(
        f"{base_url}/openapi.json"
    )

    paths = openapi.get(
        "paths",
        {},
    )

    checks = {
        "provisioning_succeeded": (
            properties.get(
                "provisioningState"
            )
            == "Succeeded"
        ),
        "external_ingress_enabled": (
            ingress.get(
                "external"
            )
            is True
        ),
        "target_port_is_8000": (
            ingress.get(
                "targetPort"
            )
            == 8000
        ),
        "immutable_image_matches": (
            container.get(
                "image"
            )
            == expected_image
        ),
        "production_environment": (
            environment.get(
                "PEARLS_API_ENVIRONMENT",
                {},
            ).get(
                "value"
            )
            == "production"
        ),
        "azure_blob_backend": (
            environment.get(
                "PEARLS_API_ARTIFACT_BACKEND",
                {},
            ).get(
                "value"
            )
            == "azure_blob"
        ),
        "production_blob_container": (
            environment.get(
                "PEARLS_API_AZURE_STORAGE_CONTAINER",
                {},
            ).get(
                "value"
            )
            == "artifacts-prod"
        ),
        "aging_threshold_is_7": (
            environment.get(
                "PEARLS_API_FORECAST_AGING_THRESHOLD_HOURS",
                {},
            ).get(
                "value"
            )
            == "7"
        ),
        "staleness_threshold_is_13": (
            environment.get(
                "PEARLS_API_FORECAST_STALENESS_THRESHOLD_HOURS",
                {},
            ).get(
                "value"
            )
            == "13"
        ),
        "liveness_is_healthy": (
            live_status == 200
            and live_payload.get(
                "status"
            )
            == "ALIVE"
        ),

        # Until Phase 10M-H publishes the first AQI artifact,
        # production is deliberately live but not ready.
        "readiness_waiting_for_initial_publication": (
            ready_status == 503
        ),

        "openapi_has_health": (
            "/api/v1/health/live"
            in paths
            and "/api/v1/health/ready"
            in paths
        ),
        "openapi_has_forecast": (
            "/api/v1/forecast"
            in paths
        ),
        "openapi_has_alerts": (
            "/api/v1/alerts"
            in paths
        ),
    }

    return {
        "valid": all(
            checks.values()
        ),
        "checks": checks,
        "application": {
            "name": app_name,
            "fqdn": fqdn,
            "url": base_url,
            "image": container.get(
                "image"
            ),
        },
        "liveness": {
            "http_status": live_status,
            "payload": live_payload,
        },
        "readiness": {
            "http_status": ready_status,
            "payload": ready_payload,
            "expected_before_initial_publication": (
                503
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
        "--app-name",
        default="ca-pearls-aqi-api-prod",
    )

    parser.add_argument(
        "--release-sha",
        required=True,
    )

    arguments = parser.parse_args()

    expected_image = (
        "walpole.azurecr.io/"
        "pearls-aqi/api:"
        f"{arguments.release_sha}"
    )

    try:
        validation = validate_api(
            resource_group=(
                arguments.resource_group
            ),
            app_name=arguments.app_name,
            expected_image=expected_image,
        )

        report = {
            "phase": "10M",
            "subphase": "10M-E",
            "generated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "PRODUCTION_API_DEPLOYMENT_VALIDATED"
                if validation[
                    "valid"
                ]
                else "PRODUCTION_API_DEPLOYMENT_INVALID"
            ),
            "initial_aqi_publication_complete": False,
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
            "subphase": "10M-E",
            "generated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "PRODUCTION_API_DEPLOYMENT_VALIDATION_FAILED"
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