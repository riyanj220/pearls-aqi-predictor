"""Register and validate the existing approved model."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.mlops.client import (
    connect_to_hopsworks,
)
from app.mlops.config import (
    get_mlops_settings,
)
from app.mlops.model_registry import (
    prepare_model_package,
    register_initial_production_model,
    resolve_production_model,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run_initial_model_registration() -> dict[str, Any]:
    """Register and resolve the initial champion."""

    settings = get_mlops_settings()

    if settings.mlops_dry_run:
        raise ValueError(
            "Phase 9F requires MLOPS_DRY_RUN=false."
        )

    resources = connect_to_hopsworks(
        settings
    )

    package_directory, checksum = (
        prepare_model_package(
            project_root=PROJECT_ROOT,
            settings=settings,
        )
    )

    registered = (
        register_initial_production_model(
            resources=resources,
            settings=settings,
            package_directory=(
                package_directory
            ),
            checksum_sha256=checksum,
        )
    )

    if (
        registered.version
        != settings.hopsworks_production_model_version
    ):
        raise RuntimeError(
            "Registered model version does not "
            "match HOPSWORKS_PRODUCTION_MODEL_VERSION. "
            f"Registered={registered.version}, "
            "configured="
            f"{settings.hopsworks_production_model_version}"
        )

    resolved = resolve_production_model(
        resources=resources,
        settings=settings,
        project_root=PROJECT_ROOT,
    )

    return {
        "phase": "9F",
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "status": (
            "INITIAL_PRODUCTION_MODEL_REGISTERED"
        ),
        "registered_model": (
            registered.to_dict()
        ),
        "resolved_model": (
            resolved.to_dict()
        ),
        "explicit_version_resolution": True,
        "latest_version_resolution_used": False,
        "checksum_validated": (
            registered.checksum_sha256
            == resolved.checksum_sha256
        ),
        "model_load_validated": True,
        "local_fallback_preserved": True,
    }


def main() -> int:
    """Run Phase 9F and save its report."""

    report_path = (
        PROJECT_ROOT
        / "reports"
        / "phase_9"
        / "model_registry_report.json"
    )

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        report = (
            run_initial_model_registration()
        )

        exit_code = 0

    except Exception as error:
        report = {
            "phase": "9F",
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": (
                "INITIAL_MODEL_REGISTRATION_FAILED"
            ),
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(error),
        }

        exit_code = 1

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

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