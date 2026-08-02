"""Validate locally built Phase 10G production container images."""

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
    / "container_image_validation_report.json"
)


class ContainerImageValidationError(RuntimeError):
    """Raised when a required container-image check fails."""


def run_command(
    arguments: list[str],
) -> str:
    """Run one command and return stripped standard output."""

    result = subprocess.run(
        arguments,
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    return result.stdout.strip()


def inspect_image(
    image_name: str,
) -> dict[str, Any]:
    """Inspect one locally available image."""

    raw_payload = run_command(
        [
            "docker",
            "image",
            "inspect",
            image_name,
        ]
    )

    payload = json.loads(raw_payload)

    if not isinstance(payload, list) or len(payload) != 1:
        raise ContainerImageValidationError(
            f"Unexpected Docker inspection result for {image_name}."
        )

    image = payload[0]

    config = image.get("Config") or {}
    labels = config.get("Labels") or {}

    user = str(config.get("User") or "")

    return {
        "image": image_name,
        "image_id": image.get("Id"),
        "created": image.get("Created"),
        "os": image.get("Os"),
        "architecture": image.get("Architecture"),
        "size_bytes": image.get("Size"),
        "configured_user": user,
        "runs_as_root": user in {"", "0", "root"},
        "healthcheck_configured": bool(
            config.get("Healthcheck")
        ),
        "entrypoint": config.get("Entrypoint"),
        "command": config.get("Cmd"),
        "labels": {
            "title": labels.get(
                "org.opencontainers.image.title"
            ),
            "version": labels.get(
                "org.opencontainers.image.version"
            ),
            "revision": labels.get(
                "org.opencontainers.image.revision"
            ),
            "created": labels.get(
                "org.opencontainers.image.created"
            ),
        },
    }


def build_validation_report(
    *,
    image_tag: str,
) -> dict[str, Any]:
    """Validate API, dashboard, and pipeline images."""

    images = {
        "api": inspect_image(
            f"pearls-aqi-api:{image_tag}"
        ),
        "dashboard": inspect_image(
            f"pearls-aqi-dashboard:{image_tag}"
        ),
        "pipeline": inspect_image(
            f"pearls-aqi-pipeline:{image_tag}"
        ),
    }

    checks = {
        "all_images_linux": all(
            image["os"] == "linux"
            for image in images.values()
        ),
        "all_images_amd64": all(
            image["architecture"] == "amd64"
            for image in images.values()
        ),
        "all_images_non_root": all(
            not image["runs_as_root"]
            for image in images.values()
        ),
        "api_healthcheck_configured": images[
            "api"
        ]["healthcheck_configured"],
        "dashboard_healthcheck_configured": images[
            "dashboard"
        ]["healthcheck_configured"],
        "pipeline_has_no_healthcheck": not images[
            "pipeline"
        ]["healthcheck_configured"],
        "all_titles_present": all(
            bool(image["labels"]["title"])
            for image in images.values()
        ),
        "all_revisions_present": all(
            bool(image["labels"]["revision"])
            for image in images.values()
        ),
        "all_commands_present": all(
            bool(image["command"])
            for image in images.values()
        ),
    }

    approved = all(checks.values())

    return {
        "phase": "10G",
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "status": (
            "PRODUCTION_CONTAINER_IMAGES_VALIDATED"
            if approved
            else "PRODUCTION_CONTAINER_IMAGES_INVALID"
        ),
        "approved": approved,
        "image_tag": image_tag,
        "images": images,
        "checks": checks,
        "registry_push_performed": False,
        "azure_resources_modified": False,
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Save the Phase 10G validation report."""

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
    """CLI entry point."""

    parser = argparse.ArgumentParser(
        description=(
            "Validate locally built production "
            "container images."
        )
    )

    parser.add_argument(
        "--image-tag",
        required=True,
        help=(
            "Local image tag used for all three images."
        ),
    )

    arguments = parser.parse_args()

    try:
        report = build_validation_report(
            image_tag=arguments.image_tag
        )

        exit_code = (
            0
            if report["approved"]
            else 1
        )

    except Exception as error:
        report = {
            "phase": "10G",
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": (
                "PRODUCTION_CONTAINER_IMAGE_VALIDATION_FAILED"
            ),
            "approved": False,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "registry_push_performed": False,
            "azure_resources_modified": False,
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