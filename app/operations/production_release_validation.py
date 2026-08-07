"""Validate one immutable production image release."""

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
    / "production_release_validation_report.json"
)


class ProductionReleaseValidationError(
    RuntimeError
):
    """Raised when the production release is invalid."""


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
        raise ProductionReleaseValidationError(
            "Command failed.\n"
            f"Command: {' '.join(arguments)}\n"
            f"Error: {completed.stderr.strip()}"
        )

    return completed.stdout.strip()


def image_exists(
    *,
    acr_name: str,
    repository: str,
    release_sha: str,
) -> bool:
    completed = subprocess.run(
        [
            "az",
            "acr",
            "repository",
            "show",
            "--name",
            acr_name,
            "--image",
            f"{repository}:{release_sha}",
            "--output",
            "none",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    return completed.returncode == 0


def inspect_local_image(
    image: str,
) -> dict[str, Any]:
    payload = run_command(
        [
            "docker",
            "image",
            "inspect",
            image,
        ]
    )

    parsed = json.loads(payload)

    if not isinstance(parsed, list) or not parsed:
        raise ProductionReleaseValidationError(
            f"Could not inspect image: {image}"
        )

    return parsed[0]


def validate_release(
    *,
    acr_name: str,
    acr_server: str,
    release_sha: str,
) -> dict[str, Any]:
    repositories = {
        "api": "pearls-aqi/api",
        "dashboard": "pearls-aqi/dashboard",
        "pipeline": "pearls-aqi/pipeline",
    }

    images = {
        name: (
            f"{acr_server}/{repository}:"
            f"{release_sha}"
        )
        for name, repository
        in repositories.items()
    }

    checks: dict[str, bool] = {}

    metadata: dict[str, Any] = {}

    for name, repository in repositories.items():
        image = images[name]

        checks[
            f"{name}_exists_in_acr"
        ] = image_exists(
            acr_name=acr_name,
            repository=repository,
            release_sha=release_sha,
        )

        inspected = inspect_local_image(
            image
        )

        config = inspected.get(
            "Config",
            {},
        )

        labels = config.get(
            "Labels",
            {},
        ) or {}

        revision = labels.get(
            "org.opencontainers.image.revision"
        )

        version = labels.get(
            "org.opencontainers.image.version"
        )

        user = config.get(
            "User"
        )

        checks[
            f"{name}_revision_matches"
        ] = (
            revision == release_sha
        )

        checks[
            f"{name}_version_matches"
        ] = (
            version == release_sha
        )

        checks[
            f"{name}_runs_non_root"
        ] = bool(user) and user != "root"

        checks[
            f"{name}_tag_is_immutable"
        ] = (
            image.endswith(
                f":{release_sha}"
            )
            and not image.endswith(
                ":latest"
            )
        )

        metadata[name] = {
            "image": image,
            "revision": revision,
            "version": version,
            "user": user,
            "image_id": (
                inspected.get(
                    "Id"
                )
            ),
        }

    checks[
        "single_release_sha"
    ] = all(
        item.get(
            "revision"
        )
        == release_sha
        for item in metadata.values()
    )

    return {
        "valid": all(
            checks.values()
        ),
        "release_sha": release_sha,
        "checks": checks,
        "images": metadata,
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
    parser = argparse.ArgumentParser(
        description=(
            "Validate immutable production "
            "release images."
        )
    )

    parser.add_argument(
        "--release-sha",
        required=True,
    )

    parser.add_argument(
        "--acr",
        default="walpole",
    )

    parser.add_argument(
        "--acr-server",
        default="walpole.azurecr.io",
    )

    arguments = parser.parse_args()

    try:
        validation = validate_release(
            acr_name=arguments.acr,
            acr_server=(
                arguments.acr_server
            ),
            release_sha=(
                arguments.release_sha
            ),
        )

        report = {
            "phase": "10M",
            "subphase": "10M-D",
            "generated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "PRODUCTION_RELEASE_VALIDATED"
                if validation["valid"]
                else "PRODUCTION_RELEASE_INVALID"
            ),
            "application_services_deployed": False,
            "scheduled_jobs_deployed": False,
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
            "subphase": "10M-D",
            "generated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "PRODUCTION_RELEASE_VALIDATION_FAILED"
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