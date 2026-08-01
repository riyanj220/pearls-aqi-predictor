"""Validate production deployment environment configuration.

This module validates configuration for:

- FastAPI
- Streamlit
- batch pipeline jobs

It does not connect to Azure and never prints secret values.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[2]

REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "deployment_configuration_report.json"
)


class DeploymentConfigurationError(RuntimeError):
    """Raised when deployment configuration is invalid."""


ALLOWED_ENVIRONMENTS = {
    "development",
    "demo",
    "staging",
    "production",
}

ALLOWED_SERVICE_ROLES = {
    "api",
    "dashboard",
    "pipeline",
}

ALLOWED_LOG_LEVELS = {
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
}

ALLOWED_ARTIFACT_BACKENDS = {
    "local",
    "azure_blob",
}

ALLOWED_MODEL_LOADING_MODES = {
    "LOCAL_ARTIFACT",
    "HOPSWORKS_REGISTRY",
}

ALLOWED_FEATURE_STORE_BACKENDS = {
    "local",
    "hopsworks",
}


@dataclass(frozen=True)
class ValidationIssue:
    """One configuration validation issue."""

    code: str
    field: str
    message: str
    severity: str = "ERROR"


@dataclass(frozen=True)
class DeploymentSettings:
    """Non-secret deployment configuration."""

    app_environment: str
    app_version: str
    service_role: str
    log_level: str

    azure_location: str
    azure_resource_group: str
    azure_container_registry: str

    artifact_backend: str
    local_artifact_root: str
    azure_storage_account: str | None
    azure_storage_container: str | None

    azure_key_vault_name: str | None

    fastapi_base_url: str | None
    allowed_cors_origins: list[str]
    forecast_staleness_threshold_hours: int

    model_loading_mode: str
    feature_store_backend: str
    model_registry_backend: str

    automatic_retraining_enabled: bool
    automatic_model_promotion_enabled: bool

    openaq_api_key_configured: bool
    hopsworks_api_key_configured: bool
    hopsworks_project_configured: bool
    hopsworks_host_configured: bool

    def safe_summary(self) -> dict[str, Any]:
        """Return configuration without secret values."""

        return asdict(self)


def read_environment(
    source: Mapping[str, str] | None = None,
) -> Mapping[str, str]:
    """Return the environment mapping used for validation."""

    return source if source is not None else os.environ


def get_string(
    environment: Mapping[str, str],
    name: str,
    default: str = "",
) -> str:
    """Read and normalize one string value."""

    return environment.get(
        name,
        default,
    ).strip()


def get_optional_string(
    environment: Mapping[str, str],
    name: str,
) -> str | None:
    """Read one optional normalized string."""

    value = get_string(
        environment,
        name,
    )

    return value or None


def get_boolean(
    environment: Mapping[str, str],
    name: str,
    default: bool = False,
) -> bool:
    """Read one strict Boolean environment value."""

    raw_value = environment.get(name)

    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()

    if normalized in {
        "true",
        "1",
        "yes",
        "on",
    }:
        return True

    if normalized in {
        "false",
        "0",
        "no",
        "off",
    }:
        return False

    raise DeploymentConfigurationError(
        f"{name} must be a Boolean value."
    )


def get_positive_integer(
    environment: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    """Read one positive integer."""

    raw_value = environment.get(name)

    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError as error:
        raise DeploymentConfigurationError(
            f"{name} must be an integer."
        ) from error

    if value <= 0:
        raise DeploymentConfigurationError(
            f"{name} must be greater than zero."
        )

    return value


def parse_cors_origins(
    raw_value: str,
) -> list[str]:
    """Parse comma-separated CORS origins."""

    return [
        value.strip()
        for value in raw_value.split(",")
        if value.strip()
    ]


def is_valid_http_url(
    value: str,
) -> bool:
    """Return whether a value is a valid HTTP URL."""

    parsed = urlparse(value)

    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
    )


def load_deployment_settings(
    source: Mapping[str, str] | None = None,
) -> DeploymentSettings:
    """Load deployment settings without validating service rules."""

    environment = read_environment(source)

    app_environment = get_string(
        environment,
        "APP_ENV",
        "development",
    ).lower()

    service_role = get_string(
        environment,
        "SERVICE_ROLE",
        "api",
    ).lower()

    log_level = get_string(
        environment,
        "LOG_LEVEL",
        "INFO",
    ).upper()

    artifact_backend = get_string(
        environment,
        "ARTIFACT_BACKEND",
        "local",
    ).lower()

    model_loading_mode = get_string(
        environment,
        "MODEL_LOADING_MODE",
        "LOCAL_ARTIFACT",
    ).upper()

    feature_store_backend = get_string(
        environment,
        "FEATURE_STORE_BACKEND",
        "local",
    ).lower()

    model_registry_backend = get_string(
        environment,
        "MODEL_REGISTRY_BACKEND",
        "local",
    ).lower()

    return DeploymentSettings(
        app_environment=app_environment,
        app_version=get_string(
            environment,
            "APP_VERSION",
            "development",
        ),
        service_role=service_role,
        log_level=log_level,
        azure_location=get_string(
            environment,
            "AZURE_LOCATION",
            "centralindia",
        ).lower(),
        azure_resource_group=get_string(
            environment,
            "AZURE_RESOURCE_GROUP",
            "rg-pearls-aqi-demo",
        ),
        azure_container_registry=get_string(
            environment,
            "AZURE_CONTAINER_REGISTRY",
            "walpole.azurecr.io",
        ),
        artifact_backend=artifact_backend,
        local_artifact_root=get_string(
            environment,
            "LOCAL_ARTIFACT_ROOT",
            ".",
        ),
        azure_storage_account=get_optional_string(
            environment,
            "AZURE_STORAGE_ACCOUNT",
        ),
        azure_storage_container=get_optional_string(
            environment,
            "AZURE_STORAGE_CONTAINER",
        ),
        azure_key_vault_name=get_optional_string(
            environment,
            "AZURE_KEY_VAULT_NAME",
        ),
        fastapi_base_url=get_optional_string(
            environment,
            "FASTAPI_BASE_URL",
        ),
        allowed_cors_origins=parse_cors_origins(
            get_string(
                environment,
                "ALLOWED_CORS_ORIGINS",
                "",
            )
        ),
        forecast_staleness_threshold_hours=(
            get_positive_integer(
                environment,
                "FORECAST_STALENESS_THRESHOLD_HOURS",
                6,
            )
        ),
        model_loading_mode=model_loading_mode,
        feature_store_backend=(
            feature_store_backend
        ),
        model_registry_backend=(
            model_registry_backend
        ),
        automatic_retraining_enabled=(
            get_boolean(
                environment,
                "AUTOMATIC_RETRAINING_ENABLED",
                False,
            )
        ),
        automatic_model_promotion_enabled=(
            get_boolean(
                environment,
                "AUTOMATIC_MODEL_PROMOTION_ENABLED",
                False,
            )
        ),
        openaq_api_key_configured=bool(
            get_string(
                environment,
                "OPENAQ_API_KEY",
            )
        ),
        hopsworks_api_key_configured=bool(
            get_string(
                environment,
                "HOPSWORKS_API_KEY",
            )
        ),
        hopsworks_project_configured=bool(
            get_string(
                environment,
                "HOPSWORKS_PROJECT",
            )
        ),
        hopsworks_host_configured=bool(
            get_string(
                environment,
                "HOPSWORKS_HOST",
            )
        ),
    )


def validate_common_settings(
    settings: DeploymentSettings,
) -> list[ValidationIssue]:
    """Validate settings common to every service."""

    issues: list[ValidationIssue] = []

    if (
        settings.app_environment
        not in ALLOWED_ENVIRONMENTS
    ):
        issues.append(
            ValidationIssue(
                code="INVALID_APP_ENV",
                field="APP_ENV",
                message=(
                    "APP_ENV must be development, demo, "
                    "staging, or production."
                ),
            )
        )

    if (
        settings.service_role
        not in ALLOWED_SERVICE_ROLES
    ):
        issues.append(
            ValidationIssue(
                code="INVALID_SERVICE_ROLE",
                field="SERVICE_ROLE",
                message=(
                    "SERVICE_ROLE must be api, "
                    "dashboard, or pipeline."
                ),
            )
        )

    if settings.log_level not in ALLOWED_LOG_LEVELS:
        issues.append(
            ValidationIssue(
                code="INVALID_LOG_LEVEL",
                field="LOG_LEVEL",
                message=(
                    "LOG_LEVEL contains an unsupported value."
                ),
            )
        )

    if (
        settings.artifact_backend
        not in ALLOWED_ARTIFACT_BACKENDS
    ):
        issues.append(
            ValidationIssue(
                code="INVALID_ARTIFACT_BACKEND",
                field="ARTIFACT_BACKEND",
                message=(
                    "ARTIFACT_BACKEND must be local "
                    "or azure_blob."
                ),
            )
        )

    if (
        settings.model_loading_mode
        not in ALLOWED_MODEL_LOADING_MODES
    ):
        issues.append(
            ValidationIssue(
                code="INVALID_MODEL_LOADING_MODE",
                field="MODEL_LOADING_MODE",
                message=(
                    "MODEL_LOADING_MODE must be "
                    "LOCAL_ARTIFACT or HOPSWORKS_REGISTRY."
                ),
            )
        )

    if (
        settings.feature_store_backend
        not in ALLOWED_FEATURE_STORE_BACKENDS
    ):
        issues.append(
            ValidationIssue(
                code="INVALID_FEATURE_STORE_BACKEND",
                field="FEATURE_STORE_BACKEND",
                message=(
                    "FEATURE_STORE_BACKEND must be "
                    "local or hopsworks."
                ),
            )
        )

    if settings.artifact_backend == "azure_blob":
        if not settings.azure_storage_account:
            issues.append(
                ValidationIssue(
                    code="STORAGE_ACCOUNT_REQUIRED",
                    field="AZURE_STORAGE_ACCOUNT",
                    message=(
                        "Azure Storage account is required "
                        "for the azure_blob backend."
                    ),
                )
            )

        if not settings.azure_storage_container:
            issues.append(
                ValidationIssue(
                    code="STORAGE_CONTAINER_REQUIRED",
                    field="AZURE_STORAGE_CONTAINER",
                    message=(
                        "Azure Storage container is required "
                        "for the azure_blob backend."
                    ),
                )
            )

    if settings.app_environment in {
        "demo",
        "staging",
        "production",
    }:
        if not settings.azure_resource_group:
            issues.append(
                ValidationIssue(
                    code="AZURE_RESOURCE_GROUP_REQUIRED",
                    field="AZURE_RESOURCE_GROUP",
                    message=(
                        "Azure resource group is required "
                        "for cloud environments."
                    ),
                )
            )

        if not settings.azure_container_registry:
            issues.append(
                ValidationIssue(
                    code="CONTAINER_REGISTRY_REQUIRED",
                    field="AZURE_CONTAINER_REGISTRY",
                    message=(
                        "Azure Container Registry login "
                        "server is required."
                    ),
                )
            )

    if settings.automatic_model_promotion_enabled:
        issues.append(
            ValidationIssue(
                code="AUTO_PROMOTION_FORBIDDEN",
                field=(
                    "AUTOMATIC_MODEL_PROMOTION_ENABLED"
                ),
                message=(
                    "Automatic model promotion must remain "
                    "disabled for this deployment."
                ),
            )
        )

    return issues


def validate_api_settings(
    settings: DeploymentSettings,
) -> list[ValidationIssue]:
    """Validate FastAPI-specific settings."""

    issues: list[ValidationIssue] = []

    if settings.service_role != "api":
        return issues

    if (
        settings.app_environment
        in {"demo", "staging", "production"}
        and not settings.allowed_cors_origins
    ):
        issues.append(
            ValidationIssue(
                code="CORS_ORIGINS_REQUIRED",
                field="ALLOWED_CORS_ORIGINS",
                message=(
                    "At least one explicit CORS origin "
                    "is required for cloud deployment."
                ),
            )
        )

    for origin in settings.allowed_cors_origins:
        if origin == "*":
            issues.append(
                ValidationIssue(
                    code="WILDCARD_CORS_FORBIDDEN",
                    field="ALLOWED_CORS_ORIGINS",
                    message=(
                        "Wildcard CORS is not allowed "
                        "for the cloud demo."
                    ),
                )
            )

        elif not is_valid_http_url(origin):
            issues.append(
                ValidationIssue(
                    code="INVALID_CORS_ORIGIN",
                    field="ALLOWED_CORS_ORIGINS",
                    message=(
                        f"Invalid CORS origin: {origin}"
                    ),
                )
            )

    return issues


def validate_dashboard_settings(
    settings: DeploymentSettings,
) -> list[ValidationIssue]:
    """Validate Streamlit-specific settings."""

    issues: list[ValidationIssue] = []

    if settings.service_role != "dashboard":
        return issues

    if not settings.fastapi_base_url:
        issues.append(
            ValidationIssue(
                code="FASTAPI_BASE_URL_REQUIRED",
                field="FASTAPI_BASE_URL",
                message=(
                    "Streamlit requires the FastAPI base URL."
                ),
            )
        )

    elif not is_valid_http_url(
        settings.fastapi_base_url
    ):
        issues.append(
            ValidationIssue(
                code="INVALID_FASTAPI_BASE_URL",
                field="FASTAPI_BASE_URL",
                message=(
                    "FASTAPI_BASE_URL must be a valid "
                    "HTTP or HTTPS URL."
                ),
            )
        )

    return issues


def validate_pipeline_settings(
    settings: DeploymentSettings,
) -> list[ValidationIssue]:
    """Validate batch-pipeline settings."""

    issues: list[ValidationIssue] = []

    if settings.service_role != "pipeline":
        return issues

    if not settings.openaq_api_key_configured:
        issues.append(
            ValidationIssue(
                code="OPENAQ_API_KEY_REQUIRED",
                field="OPENAQ_API_KEY",
                message=(
                    "The live pipeline requires an "
                    "OpenAQ API key."
                ),
            )
        )

    hopsworks_required = any(
        [
            settings.model_loading_mode
            == "HOPSWORKS_REGISTRY",
            settings.feature_store_backend
            == "hopsworks",
            settings.model_registry_backend
            == "hopsworks",
        ]
    )

    if hopsworks_required:
        required_hopsworks_values = {
            "HOPSWORKS_API_KEY": (
                settings.hopsworks_api_key_configured
            ),
            "HOPSWORKS_PROJECT": (
                settings.hopsworks_project_configured
            ),
            "HOPSWORKS_HOST": (
                settings.hopsworks_host_configured
            ),
        }

        for field, configured in (
            required_hopsworks_values.items()
        ):
            if not configured:
                issues.append(
                    ValidationIssue(
                        code=(
                            "HOPSWORKS_CONFIGURATION_REQUIRED"
                        ),
                        field=field,
                        message=(
                            f"{field} is required when "
                            "Hopsworks is enabled."
                        ),
                    )
                )

    return issues


def validate_deployment_settings(
    settings: DeploymentSettings,
) -> list[ValidationIssue]:
    """Run all deployment validation checks."""

    return [
        *validate_common_settings(settings),
        *validate_api_settings(settings),
        *validate_dashboard_settings(settings),
        *validate_pipeline_settings(settings),
    ]


def build_configuration_report(
    source: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the Phase 10C configuration report."""

    settings = load_deployment_settings(source)

    issues = validate_deployment_settings(
        settings
    )

    approved = not any(
        issue.severity == "ERROR"
        for issue in issues
    )

    return {
        "phase": "10C",
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "status": (
            "DEPLOYMENT_CONFIGURATION_VALIDATED"
            if approved
            else "DEPLOYMENT_CONFIGURATION_INVALID"
        ),
        "approved": approved,
        "configuration": settings.safe_summary(),
        "issue_count": len(issues),
        "issues": [
            asdict(issue)
            for issue in issues
        ],
        "secret_values_included": False,
        "azure_resources_created": False,
    }


def save_configuration_report(
    report: dict[str, Any],
) -> Path:
    """Save the Phase 10C report."""

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    return REPORT_PATH


def main() -> int:
    """CLI entry point."""

    parser = argparse.ArgumentParser(
        description=(
            "Validate deployment environment "
            "configuration."
        )
    )

    parser.parse_args()

    try:
        report = build_configuration_report()
        exit_code = (
            0
            if report["approved"]
            else 1
        )

    except Exception as error:
        report = {
            "phase": "10C",
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": (
                "DEPLOYMENT_CONFIGURATION_FAILED"
            ),
            "approved": False,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "secret_values_included": False,
            "azure_resources_created": False,
        }

        exit_code = 1

    report_path = save_configuration_report(
        report
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