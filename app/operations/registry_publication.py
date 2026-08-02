"""Validate images published to Azure Container Registry."""

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
    / "registry_publication_report.json"
)


class RegistryPublicationError(RuntimeError):
    """Raised when registry publication validation fails."""


def run_command(
    arguments: list[str],
) -> str:
    """Run one command and return standard output."""

    result = subprocess.run(
        arguments,
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    return result.stdout.strip()


def inspect_registry_image(
    *,
    registry_name: str,
    repository: str,
    tag: str,
) -> dict[str, Any]:
    """Read metadata for one published ACR image."""

    raw_payload = run_command(
        [
            "az",
            "acr",
            "repository",
            "show",
            "--name",
            registry_name,
            "--image",
            f"{repository}:{tag}",
            "--output",
            "json",
        ]
    )

    payload = json.loads(raw_payload)

    digest = payload.get("digest")

    if not isinstance(digest, str):
        raise RegistryPublicationError(
            f"Digest missing for {repository}:{tag}."
        )

    if not digest.startswith("sha256:"):
        raise RegistryPublicationError(
            f"Invalid digest for {repository}:{tag}."
        )

    return {
        "repository": repository,
        "tag": tag,
        "digest": digest,
        "created_time": payload.get(
            "createdTime"
        ),
        "last_update_time": payload.get(
            "lastUpdateTime"
        ),
        "image_size_bytes": payload.get(
            "imageSize"
        ),
        "changeable_attributes": payload.get(
            "changeableAttributes"
        ),
    }


def build_registry_publication_report(
    *,
    registry_name: str,
    registry_login_server: str,
    image_tag: str,
    git_commit_sha: str,
) -> dict[str, Any]:
    """Validate all three published production images."""

    repositories = {
        "api": "pearls-aqi/api",
        "dashboard": "pearls-aqi/dashboard",
        "pipeline": "pearls-aqi/pipeline",
    }

    images = {
        name: inspect_registry_image(
            registry_name=registry_name,
            repository=repository,
            tag=image_tag,
        )
        for name, repository
        in repositories.items()
    }

    checks = {
        "all_images_found": (
            len(images) == 3
        ),
        "all_digests_present": all(
            bool(image["digest"])
            for image in images.values()
        ),
        "all_digests_sha256": all(
            image["digest"].startswith(
                "sha256:"
            )
            for image in images.values()
        ),
        "tag_matches_git_commit": (
            image_tag == git_commit_sha
        ),
        "tag_is_not_latest": (
            image_tag != "latest"
        ),
        "registry_login_server_valid": (
            registry_login_server.endswith(
                ".azurecr.io"
            )
        ),
    }

    approved = all(checks.values())

    return {
        "phase": "10H",
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "status": (
            "REGISTRY_PUBLICATION_VALIDATED"
            if approved
            else "REGISTRY_PUBLICATION_INVALID"
        ),
        "approved": approved,
        "registry": {
            "name": registry_name,
            "login_server": (
                registry_login_server
            ),
        },
        "image_tag": image_tag,
        "git_commit_sha": git_commit_sha,
        "images": images,
        "checks": checks,
        "floating_latest_tag_pushed": False,
        "deployment_performed": False,
        "azure_resources_created": False,
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Save the registry publication report atomically."""

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
            "Validate images published to Azure "
            "Container Registry."
        )
    )

    parser.add_argument(
        "--registry-name",
        required=True,
    )

    parser.add_argument(
        "--registry-login-server",
        required=True,
    )

    parser.add_argument(
        "--image-tag",
        required=True,
    )

    parser.add_argument(
        "--git-commit-sha",
        required=True,
    )

    arguments = parser.parse_args()

    try:
        report = (
            build_registry_publication_report(
                registry_name=(
                    arguments.registry_name
                ),
                registry_login_server=(
                    arguments
                    .registry_login_server
                ),
                image_tag=(
                    arguments.image_tag
                ),
                git_commit_sha=(
                    arguments.git_commit_sha
                ),
            )
        )

        exit_code = (
            0
            if report["approved"]
            else 1
        )

    except Exception as error:
        report = {
            "phase": "10H",
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": (
                "REGISTRY_PUBLICATION_VALIDATION_FAILED"
            ),
            "approved": False,
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(error),
            "floating_latest_tag_pushed": False,
            "deployment_performed": False,
            "azure_resources_created": False,
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