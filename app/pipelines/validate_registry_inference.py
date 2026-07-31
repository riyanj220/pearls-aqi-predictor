"""Validate registry-backed model loading."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.inference.model_source import (
    resolve_local_artifacts,
    resolve_registry_artifacts,
)

from app.mlops.config import (
    get_mlops_settings,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_feature_columns(
    path: Path,
) -> list[str]:
    """Load ordered feature columns."""

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if isinstance(payload, list):
        return [
            str(value)
            for value in payload
        ]

    values = payload.get(
        "feature_columns"
    )

    if not isinstance(values, list):
        raise ValueError(
            f"No feature_columns list in {path}."
        )

    return [
        str(value)
        for value in values
    ]


def main() -> int:
    """Validate registry and local model parity."""

    report_path = (
        PROJECT_ROOT
        / "reports"
        / "phase_9"
        / "production_model_resolution_report.json"
    )

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        settings = get_mlops_settings()

        local = resolve_local_artifacts()

        registry = resolve_registry_artifacts(
            settings=settings
        )

        local_columns = load_feature_columns(
            local.feature_columns_path
        )

        registry_columns = load_feature_columns(
            registry.feature_columns_path
        )

        checksum_matches = (
            local.checksum_sha256
            == registry.checksum_sha256
        )

        feature_contract_matches = (
            local_columns
            == registry_columns
        )

        if not checksum_matches:
            raise RuntimeError(
                "Local and registry model checksums differ."
            )

        if not feature_contract_matches:
            raise RuntimeError(
                "Local and registry feature contracts differ."
            )

        report = {
            "phase": "9G",
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": (
                "REGISTRY_MODEL_LOADING_VALIDATED"
            ),
            "configured_mode": (
                settings.model_loading_mode.value
            ),
            "registry_model_name": (
                registry.model_name
            ),
            "registry_model_version": (
                registry.model_version
            ),
            "explicit_version_resolution": True,
            "latest_version_used": False,
            "local_checksum": (
                local.checksum_sha256
            ),
            "registry_checksum": (
                registry.checksum_sha256
            ),
            "checksum_matches": (
                checksum_matches
            ),
            "feature_count": len(
                registry_columns
            ),
            "feature_contract_matches": (
                feature_contract_matches
            ),
            "registry_fallback_used": (
                registry.fallback_used
            ),
            "local_fallback_available": True,
        }

        exit_code = 0

    except Exception as error:
        report = {
            "phase": "9G",
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": (
                "REGISTRY_MODEL_LOADING_FAILED"
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
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            report,
            indent=2,
        )
    )

    print("Report saved:", report_path)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())