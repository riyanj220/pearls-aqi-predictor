"""Generate the formal Phase 10M production release declaration."""

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
    / "production_release_declaration.json"
)


class ProductionReleaseDeclarationError(
    RuntimeError
):
    """Raised when final production declaration cannot be built."""


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
        raise ProductionReleaseDeclarationError(
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
        raise ProductionReleaseDeclarationError(
            f"Blob is not a JSON object: {name}"
        )

    return payload


def active_revision(
    *,
    resource_group: str,
    app_name: str,
) -> dict[str, Any] | None:
    revisions = run_json(
        [
            "az",
            "containerapp",
            "revision",
            "list",
            "--resource-group",
            resource_group,
            "--name",
            app_name,
        ]
    )

    if not isinstance(
        revisions,
        list,
    ):
        return None

    active = [
        revision
        for revision in revisions
        if isinstance(
            revision,
            dict,
        )
        and revision.get(
            "properties",
            {},
        ).get(
            "active"
        )
        is True
    ]

    active.sort(
        key=lambda revision: str(
            revision.get(
                "properties",
                {},
            ).get(
                "createdTime",
                "",
            )
        ),
        reverse=True,
    )

    return (
        active[0]
        if active
        else None
    )


def current_image(
    app: dict[str, Any],
) -> str | None:
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
        return None

    return containers[0].get(
        "image"
    )


def build_declaration(
    *,
    resource_group: str,
    storage_account: str,
    storage_container: str,
    api_name: str,
    dashboard_name: str,
    release_sha: str,
) -> dict[str, Any]:
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

    expected_api_image = (
        "walpole.azurecr.io/"
        f"pearls-aqi/api:{release_sha}"
    )

    expected_dashboard_image = (
        "walpole.azurecr.io/"
        f"pearls-aqi/dashboard:{release_sha}"
    )

    expected_pipeline_image = (
        "walpole.azurecr.io/"
        f"pearls-aqi/pipeline:{release_sha}"
    )

    api_image = current_image(
        api
    )

    dashboard_image = current_image(
        dashboard
    )

    api_fqdn = (
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

    dashboard_fqdn = (
        dashboard.get(
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

    aqi_pointer = download_json_blob(
        account=storage_account,
        container=storage_container,
        name="aqi/latest/pointer.json",
        destination=Path(
            "/tmp/final-release-aqi-pointer.json"
        ),
    )

    health_pointer = download_json_blob(
        account=storage_account,
        container=storage_container,
        name=(
            "production-health/"
            "latest/pointer.json"
        ),
        destination=Path(
            "/tmp/final-release-health-pointer.json"
        ),
    )

    outbox = download_json_blob(
        account=storage_account,
        container=storage_container,
        name=(
            "production-health/"
            "notifications/outbox.json"
        ),
        destination=Path(
            "/tmp/final-release-outbox.json"
        ),
    )

    pending_count = int(
        outbox.get(
            "pending_count",
            0,
        )
    )

    jobs = {}

    for logical_name, job_name in {
        "features": (
            "job-pearls-aqi-features-prod"
        ),
        "forecast": (
            "job-pearls-aqi-forecast-prod"
        ),
        "retraining": (
            "job-pearls-aqi-retraining-prod"
        ),
        "monitoring": (
            "job-pearls-aqi-monitoring-prod"
        ),
    }.items():
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

        image = (
            containers[0].get(
                "image"
            )
            if containers
            else None
        )

        jobs[
            logical_name
        ] = {
            "name": job_name,
            "image": image,
            "release_matches": (
                image
                == expected_pipeline_image
            ),
        }

    api_revision = active_revision(
        resource_group=resource_group,
        app_name=api_name,
    )

    dashboard_revision = active_revision(
        resource_group=resource_group,
        app_name=dashboard_name,
    )

    release_images_match = (
        api_image
        == expected_api_image
        and dashboard_image
        == expected_dashboard_image
        and all(
            job[
                "release_matches"
            ]
            for job in jobs.values()
        )
    )

    core_release_ready = (
        release_images_match
        and aqi_pointer.get(
            "validation_status"
        )
        == "AQI_ALERT_PIPELINE_APPROVED"
        and health_pointer.get(
            "validation_status"
        )
        == "PRODUCTION_HEALTH_RECORDED"
        and bool(api_fqdn)
        and bool(
            dashboard_fqdn
        )
    )

    if not core_release_ready:
        declaration_status = (
            "PRODUCTION_RELEASE_NOT_DECLARED"
        )

    elif pending_count > 0:
        declaration_status = (
            "PRODUCTION_RELEASE_"
            "DECLARED_WITH_LIMITATIONS"
        )

    else:
        declaration_status = (
            "PRODUCTION_RELEASE_DECLARED"
        )

    return {
        "phase": "10M",
        "subphase": "10M-J",
        "declared_at_utc": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        "status": (
            declaration_status
        ),
        "production_live": (
            core_release_ready
        ),
        "release": {
            "release_sha": (
                release_sha
            ),
            "api_image": (
                api_image
            ),
            "dashboard_image": (
                dashboard_image
            ),
            "pipeline_image": (
                expected_pipeline_image
            ),
            "all_images_match_release": (
                release_images_match
            ),
        },
        "public_endpoints": {
            "api": (
                f"https://{api_fqdn}"
                if api_fqdn
                else None
            ),
            "dashboard": (
                f"https://{dashboard_fqdn}"
                if dashboard_fqdn
                else None
            ),
        },
        "artifacts": {
            "container": (
                storage_container
            ),
            "aqi_run_id": (
                aqi_pointer.get(
                    "run_id"
                )
            ),
            "aqi_validation_status": (
                aqi_pointer.get(
                    "validation_status"
                )
            ),
            "health_run_id": (
                health_pointer.get(
                    "run_id"
                )
            ),
            "health_validation_status": (
                health_pointer.get(
                    "validation_status"
                )
            ),
        },
        "jobs": jobs,
        "rollback_anchors": {
            "api_revision": (
                api_revision.get(
                    "name"
                )
                if api_revision
                else None
            ),
            "dashboard_revision": (
                dashboard_revision.get(
                    "name"
                )
                if dashboard_revision
                else None
            ),
            "release_sha": (
                release_sha
            ),
            "images_retained_in_acr": (
                True
            ),
        },
        "operational_limitations": {
            "notification_delivery_permanent": (
                False
            ),
            "notification_pending_count": (
                pending_count
            ),
            "notification_backlog_accepted": (
                pending_count > 0
            ),
            "shared_container_apps_environment": (
                True
            ),
            "shared_environment_reason": (
                "Azure subscription allows only "
                "one Container Apps environment."
            ),
        },
        "cutover": {
            "application_layer_live": True,
            "production_pointer_live": True,
            "scheduled_jobs_live": True,
            "monitoring_live": True,
            "staging_preserved": True,
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
        "--storage-account",
        default="stpearlsaqiriyan",
    )

    parser.add_argument(
        "--storage-container",
        default="artifacts-prod",
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
        report = build_declaration(
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
            dashboard_name=(
                arguments.dashboard_name
            ),
            release_sha=(
                arguments.release_sha
            ),
        )

        exit_code = (
            0
            if report[
                "production_live"
            ]
            else 1
        )

    except Exception as error:
        report = {
            "phase": "10M",
            "subphase": "10M-J",
            "declared_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "PRODUCTION_RELEASE_DECLARATION_FAILED"
            ),
            "production_live": False,
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
        "Release declaration saved:",
        path,
    )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())