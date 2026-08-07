"""Validate the Phase 10M production deployment configuration."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CONFIG_PATH = (
    PROJECT_ROOT
    / "config"
    / "production.json"
)

REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "production_configuration_validation_report.json"
)


class ProductionConfigurationValidationError(
    RuntimeError
):
    """Raised when production configuration is invalid."""


def load_configuration(
    path: Path,
) -> dict[str, Any]:
    """Load production configuration."""

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except FileNotFoundError as error:
        raise ProductionConfigurationValidationError(
            f"Configuration does not exist: {path}"
        ) from error
    except json.JSONDecodeError as error:
        raise ProductionConfigurationValidationError(
            "Production configuration is invalid JSON."
        ) from error

    if not isinstance(payload, dict):
        raise ProductionConfigurationValidationError(
            "Production configuration must be an object."
        )

    return payload


def validate_configuration(
    configuration: dict[str, Any],
) -> dict[str, Any]:
    """Validate production deployment contracts."""

    azure = configuration.get(
        "azure",
        {},
    )

    api = configuration.get(
        "api",
        {},
    )

    dashboard = configuration.get(
        "dashboard",
        {},
    )

    jobs = configuration.get(
        "jobs",
        {},
    )

    mlops = configuration.get(
        "mlops",
        {},
    )

    secrets = configuration.get(
        "secrets",
        {},
    )

    environment = azure.get(
        "container_apps_environment",
        {},
    )

    storage = azure.get(
        "storage",
        {},
    )

    checks = {
        "schema_version_is_one": (
            configuration.get(
                "schema_version"
            )
            == 1
        ),

        "environment_is_production": (
            configuration.get(
                "environment"
            )
            == "production"
        ),

        "production_resource_group": (
            azure.get(
                "resource_group"
            )
            == "rg-pearls-aqi-prod"
        ),

        "shared_environment_declared": (
            environment.get(
                "name"
            )
            == "cae-pearls-aqi-staging"
            and environment.get(
                "resource_group"
            )
            == "rg-pearls-aqi-staging"
            and environment.get(
                "shared_with_staging"
            )
            is True
        ),

        "production_identity_is_separate": (
            azure.get(
                "managed_identity",
                {},
            ).get(
                "name"
            )
            == "id-pearls-aqi-prod"
        ),

        "production_blob_container_isolated": (
            storage.get(
                "container"
            )
            == "artifacts-prod"
        ),

        "api_uses_blob_backend": (
            api.get(
                "artifact_backend"
            )
            == "azure_blob"
        ),

        "api_serves_aqi": (
            api.get(
                "artifact_type"
            )
            == "aqi"
        ),

        "api_port_is_8000": (
            api.get(
                "port"
            )
            == 8000
        ),

        "api_liveness_contract": (
            api.get(
                "liveness_path"
            )
            == "/api/v1/health/live"
        ),

        "api_readiness_contract": (
            api.get(
                "readiness_path"
            )
            == "/api/v1/health/ready"
        ),

        "api_freshness_thresholds_valid": (
            api.get(
                "forecast_aging_threshold_hours"
            )
            == 7
            and api.get(
                "forecast_staleness_threshold_hours"
            )
            == 13
        ),

        "api_scales_to_zero": (
            api.get(
                "minimum_replicas"
            )
            == 0
        ),

        "dashboard_port_is_8501": (
            dashboard.get(
                "port"
            )
            == 8501
        ),

        "dashboard_scales_to_zero": (
            dashboard.get(
                "minimum_replicas"
            )
            == 0
        ),

        "feature_schedule_valid": (
            jobs.get(
                "hourly_features",
                {},
            ).get(
                "cron"
            )
            == "15 * * * *"
        ),

        "forecast_schedule_valid": (
            jobs.get(
                "forecast",
                {},
            ).get(
                "cron"
            )
            == "0 */6 * * *"
        ),

        "retraining_schedule_valid": (
            jobs.get(
                "daily_retraining",
                {},
            ).get(
                "cron"
            )
            == "30 3 * * *"
        ),

        "monitoring_schedule_valid": (
            jobs.get(
                "monitoring",
                {},
            ).get(
                "cron"
            )
            == "45 * * * *"
        ),

        "feature_store_is_hopsworks": (
            mlops.get(
                "feature_store_backend"
            )
            == "hopsworks"
        ),

        "model_registry_is_hopsworks": (
            mlops.get(
                "model_registry_backend"
            )
            == "hopsworks"
        ),

        "mlops_is_not_dry_run": (
            mlops.get(
                "dry_run"
            )
            is False
        ),

        "hopsworks_key_declared_secret": (
            "HOPSWORKS_API_KEY"
            in secrets.get(
                "required",
                [],
            )
        ),

        "webhook_declared_secret": (
            "PRODUCTION_HEALTH_WEBHOOK_URL"
            in secrets.get(
                "required",
                [],
            )
        ),
    }

    app_names = {
        api.get(
            "name"
        ),
        dashboard.get(
            "name"
        ),
    }

    job_names = {
        value.get(
            "name"
        )
        for value in jobs.values()
        if isinstance(
            value,
            dict,
        )
    }

    checks[
        "all_application_names_are_unique"
    ] = (
        len(app_names)
        == 2
        and None not in app_names
    )

    checks[
        "all_job_names_are_unique"
    ] = (
        len(job_names)
        == 4
        and None not in job_names
    )

    checks[
        "production_names_use_prod_suffix"
    ] = all(
        str(name).endswith(
            "-prod"
        )
        for name in (
            app_names
            | job_names
        )
    )

    return {
        "valid": all(
            checks.values()
        ),
        "checks": checks,
        "configuration_summary": {
            "resource_group": (
                azure.get(
                    "resource_group"
                )
            ),
            "environment": (
                environment
            ),
            "identity": (
                azure.get(
                    "managed_identity"
                )
            ),
            "storage": storage,
            "api": {
                "name": api.get(
                    "name"
                ),
                "port": api.get(
                    "port"
                ),
                "artifact_backend": (
                    api.get(
                        "artifact_backend"
                    )
                ),
                "aging_hours": (
                    api.get(
                        "forecast_aging_threshold_hours"
                    )
                ),
                "stale_hours": (
                    api.get(
                        "forecast_staleness_threshold_hours"
                    )
                ),
            },
            "dashboard": {
                "name": (
                    dashboard.get(
                        "name"
                    )
                ),
                "port": (
                    dashboard.get(
                        "port"
                    )
                ),
            },
            "job_names": sorted(
                str(name)
                for name in job_names
            ),
        },
        "secret_names": {
            "required": (
                secrets.get(
                    "required",
                    []
                )
            ),
            "optional": (
                secrets.get(
                    "optional",
                    []
                )
            ),
        },
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Atomically save validation report."""

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
    """CLI entry point."""

    parser = argparse.ArgumentParser(
        description=(
            "Validate Phase 10M "
            "production configuration."
        )
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
    )

    arguments = parser.parse_args()

    try:
        configuration = (
            load_configuration(
                arguments.config
            )
        )

        validation = (
            validate_configuration(
                configuration
            )
        )

        report = {
            "phase": "10M",
            "subphase": "10M-C",
            "generated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "PRODUCTION_CONFIGURATION_VALIDATED"
                if validation[
                    "valid"
                ]
                else (
                    "PRODUCTION_CONFIGURATION_INVALID"
                )
            ),
            "contains_secret_values": False,
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
            "subphase": "10M-C",
            "generated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "PRODUCTION_CONFIGURATION_VALIDATION_FAILED"
            ),
            "valid": False,
            "contains_secret_values": False,
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