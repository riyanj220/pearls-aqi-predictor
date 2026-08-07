"""Build a read-only inventory for production deployment planning.

The inventory combines:

- repository deployment contracts;
- current staging Azure resources;
- immutable image references;
- API and dashboard runtime configuration;
- production naming and isolation decisions.

No Azure resources are created, updated, or deleted.
"""

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
    / "production_deployment_inventory.json"
)

DEFAULT_STAGING_RESOURCE_GROUP = (
    "rg-pearls-aqi-staging"
)

DEFAULT_STAGING_ENVIRONMENT = (
    "cae-pearls-aqi-staging"
)

DEFAULT_STAGING_IDENTITY = (
    "id-pearls-aqi-staging"
)

DEFAULT_STAGING_API = (
    "ca-pearls-aqi-api-staging"
)

DEFAULT_STAGING_DASHBOARD = (
    "ca-pearls-aqi-dashboard-staging"
)

DEFAULT_ACR_NAME = "walpole"

DEFAULT_STORAGE_ACCOUNT = (
    "stpearlsaqiriyan"
)

DEFAULT_STAGING_CONTAINER = (
    "artifacts"
)

PRODUCTION_PLAN = {
    "resource_group": (
        "rg-pearls-aqi-prod"
    ),
    "location": "centralindia",
    "container_apps_environment": (
        "cae-pearls-aqi-staging"
    ),
    "managed_identity": (
        "id-pearls-aqi-prod"
    ),
    "api_app": (
        "ca-pearls-aqi-api-prod"
    ),
    "dashboard_app": (
        "ca-pearls-aqi-dashboard-prod"
    ),
    "feature_job": (
        "job-pearls-aqi-features-prod"
    ),
    "forecast_job": (
        "job-pearls-aqi-forecast-prod"
    ),
    "retraining_job": (
        "job-pearls-aqi-retraining-prod"
    ),
    "monitoring_job": (
        "job-pearls-aqi-monitoring-prod"
    ),
    "storage_account": (
        DEFAULT_STORAGE_ACCOUNT
    ),
    "artifact_container": (
        "artifacts-prod"
    ),
    "acr_name": DEFAULT_ACR_NAME,
    "acr_server": (
        "walpole.azurecr.io"
    ),
}


class ProductionDeploymentInventoryError(
    RuntimeError
):
    """Raised when deployment inventory inspection fails."""


def utc_now() -> datetime:
    """Return current timezone-aware UTC time."""

    return datetime.now(
        timezone.utc
    )


def run_command(
    arguments: list[str],
) -> str:
    """Run one local command."""

    completed = subprocess.run(
        arguments,
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        raise ProductionDeploymentInventoryError(
            "Command failed.\n"
            f"Command: {' '.join(arguments)}\n"
            f"Error: {completed.stderr.strip()}"
        )

    return completed.stdout.strip()


def run_json_command(
    arguments: list[str],
) -> Any:
    """Run one command and parse JSON output."""

    output = run_command(
        [
            *arguments,
            "--output",
            "json",
        ]
    )

    try:
        return json.loads(
            output
        )
    except json.JSONDecodeError as error:
        raise ProductionDeploymentInventoryError(
            "Command did not return valid JSON."
        ) from error


def safe_json_command(
    arguments: list[str],
) -> Any | None:
    """Run one inspection command without aborting inventory."""

    try:
        return run_json_command(
            arguments
        )
    except Exception:
        return None


def git_inventory() -> dict[str, Any]:
    """Inspect source revision and working-tree state."""

    commit = run_command(
        [
            "git",
            "rev-parse",
            "HEAD",
        ]
    )

    short_commit = run_command(
        [
            "git",
            "rev-parse",
            "--short",
            "HEAD",
        ]
    )

    branch = run_command(
        [
            "git",
            "branch",
            "--show-current",
        ]
    )

    status = run_command(
        [
            "git",
            "status",
            "--porcelain",
        ]
    )

    return {
        "commit": commit,
        "short_commit": (
            short_commit
        ),
        "branch": branch,
        "working_tree_clean": (
            status == ""
        ),
        "working_tree_changes": (
            []
            if not status
            else status.splitlines()
        ),
    }


def repository_contracts() -> dict[str, Any]:
    """Return runtime contracts derived from the repository."""

    return {
        "api": {
            "dockerfile": (
                "Dockerfile.api"
            ),
            "image_repository": (
                "pearls-aqi/api"
            ),
            "runtime": "FastAPI/Uvicorn",
            "entrypoint": [
                "uvicorn",
                "app.api.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
                "--workers",
                "1",
                "--no-access-log",
            ],
            "port": 8000,
            "non_root": True,
            "container_user": (
                "pearls"
            ),
            "healthcheck": (
                "/api/v1/health/live"
            ),
            "liveness_endpoint": (
                "/api/v1/health/live"
            ),
            "readiness_endpoint": (
                "/api/v1/health/ready"
            ),
            "docs_endpoint": "/docs",
            "openapi_endpoint": (
                "/openapi.json"
            ),
            "artifact_backend": {
                "supported": [
                    "local",
                    "azure_blob",
                ],
                "production": (
                    "azure_blob"
                ),
                "artifact_type": "aqi",
            },
            "required_environment": [
                "PEARLS_API_ENVIRONMENT",
                "PEARLS_API_APPLICATION_VERSION",
                "PEARLS_API_ARTIFACT_BACKEND",
                "PEARLS_API_ARTIFACT_TYPE",
                "PEARLS_API_AZURE_STORAGE_ACCOUNT",
                "PEARLS_API_AZURE_STORAGE_CONTAINER",
                "PEARLS_API_PHASE_6_BLOB_CACHE_DIRECTORY",
                "PEARLS_API_ARTIFACT_CACHE_SECONDS",
                "PEARLS_API_FORECAST_AGING_THRESHOLD_HOURS",
                "PEARLS_API_FORECAST_STALENESS_THRESHOLD_HOURS",
                "PEARLS_API_ALLOWED_CORS_ORIGINS",
                "PEARLS_API_LOG_LEVEL",
                "AZURE_CLIENT_ID",
            ],
            "required_secrets": [],
            "azure_authentication": (
                "user-assigned managed identity "
                "through DefaultAzureCredential"
            ),
            "production_dependencies": [
                "Azure Blob Storage",
                "production AQI latest pointer",
            ],
            "serving_contract": {
                "forecast_rows": 72,
                "forecast_horizons": (
                    "1 through 72"
                ),
                "target_frequency": (
                    "1 hour"
                ),
                "required_validation_statuses": [
                    "AQI_ALERT_PIPELINE_APPROVED",
                    (
                        "AQI_ALERT_PIPELINE_"
                        "APPROVED_WITH_LIMITATIONS"
                    ),
                ],
            },
            "local_fallback_artifacts_in_image": (
                True
            ),
        },
        "dashboard": {
            "dockerfile": (
                "Dockerfile.dashboard"
            ),
            "image_repository": (
                "pearls-aqi/dashboard"
            ),
            "runtime": "Streamlit",
            "entrypoint": [
                "streamlit",
                "run",
                "dashboard/app.py",
                (
                    "--server.address="
                    "0.0.0.0"
                ),
                "--server.port=8501",
                "--server.headless=true",
                (
                    "--browser."
                    "gatherUsageStats=false"
                ),
            ],
            "port": 8501,
            "non_root": True,
            "container_user": (
                "dashboard"
            ),
            "healthcheck": (
                "/_stcore/health"
            ),
            "required_environment": [
                "FASTAPI_BASE_URL",
                "DASHBOARD_ENVIRONMENT",
            ],
            "optional_environment": [
                (
                    "DASHBOARD_REQUEST_"
                    "TIMEOUT_SECONDS"
                ),
                (
                    "DASHBOARD_CACHE_"
                    "TTL_SECONDS"
                ),
                "DASHBOARD_TITLE",
                (
                    "DASHBOARD_DEFAULT_"
                    "TIMEZONE"
                ),
            ],
            "required_secrets": [],
            "direct_blob_dependency": (
                False
            ),
            "direct_hopsworks_dependency": (
                False
            ),
            "direct_model_registry_dependency": (
                False
            ),
            "api_dependency": True,
            "api_protocol": "HTTPS",
            "api_routes_used": [
                "/health/live",
                "/health/ready",
                "/forecast",
                "/forecast/hourly",
                "/forecast/summary",
                "/alerts",
                "/alerts/active",
                "/metadata",
                "/pipeline/status",
            ],
            "http_retry_policy": {
                "total_retries": 2,
                "connect_retries": 2,
                "read_retries": 1,
                "retry_status_codes": [
                    502,
                    503,
                    504,
                ],
            },
        },
        "pipeline": {
            "dockerfile": (
                "Dockerfile.pipeline"
            ),
            "image_repository": (
                "pearls-aqi/pipeline"
            ),
            "non_root": True,
            "container_user": (
                "pipeline"
            ),
            "default_entrypoint": [
                "python",
                "-m",
                (
                    "app.pipelines."
                    "publish_forecast"
                ),
            ],
            "workloads": [
                "hourly feature synchronization",
                "six-hour forecast publication",
                "daily retraining",
                "production health monitoring",
            ],
        },
    }


def planned_production_configuration() -> dict[str, Any]:
    """Return configuration decisions for later 10M phases."""

    return {
        **PRODUCTION_PLAN,
        "api": {
            "ingress": "external",
            "target_port": 8000,
            "min_replicas": 0,
            "max_replicas": 1,
            "cpu": 0.25,
            "memory": "0.5Gi",
            "artifact_backend": (
                "azure_blob"
            ),
            "artifact_type": "aqi",
        },
        "dashboard": {
            "ingress": "external",
            "target_port": 8501,
            "min_replicas": 0,
            "max_replicas": 1,
            "cpu": 0.25,
            "memory": "0.5Gi",
            "api_connection": (
                "production FastAPI HTTPS "
                "FQDN + /api/v1"
            ),
        },
        "isolation": {
            "separate_resource_group": True,
            "separate_container_apps_environment": False,
            "shared_container_apps_environment": True,
            "separate_managed_identity": True,
            "separate_blob_container": True,
            "shared_storage_account": True,
            "shared_acr": True,
            "shared_hopsworks_project": True,
        },

        "container_apps_environment_constraint": {
            "shared_environment_name": (
                "cae-pearls-aqi-staging"
            ),
            "reason": (
                "Azure subscription currently permits "
                "only one Container Apps environment."
            ),
            "production_isolation_preserved_by": [
                "separate app names",
                "separate job names",
                "separate managed identity",
                "separate Blob container",
                "separate environment variables",
                "separate secret references",
            ],
        },
        "artifact_boundary": {
            "staging_container": (
                DEFAULT_STAGING_CONTAINER
            ),
            "production_container": (
                "artifacts-prod"
            ),
            "reason": (
                "Prevent staging writers from "
                "advancing production latest pointers."
            ),
        },
    }


def inspect_container_app(
    *,
    resource_group: str,
    app_name: str,
) -> dict[str, Any]:
    """Inspect one existing Container App."""

    payload = safe_json_command(
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

    if not isinstance(
        payload,
        dict,
    ):
        return {
            "exists": False,
            "name": app_name,
        }

    properties = payload.get(
        "properties",
        {},
    )

    configuration = (
        properties.get(
            "configuration",
            {},
        )
    )

    template = properties.get(
        "template",
        {},
    )

    containers = template.get(
        "containers",
        [],
    )

    container = (
        containers[0]
        if containers
        else {}
    )

    ingress = configuration.get(
        "ingress",
        {},
    )

    environment_variables = (
        container.get(
            "env",
            [],
        )
    )

    safe_environment = {}

    for item in environment_variables:
        name = item.get(
            "name"
        )

        if not name:
            continue

        safe_environment[
            str(name)
        ] = {
            "uses_secret": bool(
                item.get(
                    "secretRef"
                )
            ),
            "secret_ref": (
                item.get(
                    "secretRef"
                )
            ),
            "value": (
                None
                if item.get(
                    "secretRef"
                )
                else item.get(
                    "value"
                )
            ),
        }

    return {
        "exists": True,
        "name": app_name,
        "provisioning_state": (
            properties.get(
                "provisioningState"
            )
        ),
        "environment_id": (
            properties.get(
                "managedEnvironmentId"
            )
        ),
        "image": container.get(
            "image"
        ),
        "command": container.get(
            "command"
        ),
        "args": container.get(
            "args"
        ),
        "cpu": (
            container.get(
                "resources",
                {},
            ).get(
                "cpu"
            )
        ),
        "memory": (
            container.get(
                "resources",
                {},
            ).get(
                "memory"
            )
        ),
        "fqdn": ingress.get(
            "fqdn"
        ),
        "target_port": (
            ingress.get(
                "targetPort"
            )
        ),
        "external": (
            ingress.get(
                "external"
            )
        ),
        "transport": (
            ingress.get(
                "transport"
            )
        ),
        "environment": (
            safe_environment
        ),
    }


def inspect_job(
    *,
    resource_group: str,
    job_name: str,
) -> dict[str, Any]:
    """Inspect one Container Apps Job."""

    payload = safe_json_command(
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

    if not isinstance(
        payload,
        dict,
    ):
        return {
            "exists": False,
            "name": job_name,
        }

    properties = payload.get(
        "properties",
        {},
    )

    configuration = properties.get(
        "configuration",
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

    container = (
        containers[0]
        if containers
        else {}
    )

    schedule = configuration.get(
        "scheduleTriggerConfig",
        {},
    )

    return {
        "exists": True,
        "name": job_name,
        "provisioning_state": (
            properties.get(
                "provisioningState"
            )
        ),
        "image": container.get(
            "image"
        ),
        "command": container.get(
            "command"
        ),
        "args": container.get(
            "args"
        ),
        "trigger_type": (
            configuration.get(
                "triggerType"
            )
        ),
        "cron_expression": (
            schedule.get(
                "cronExpression"
            )
        ),
        "replica_timeout": (
            configuration.get(
                "replicaTimeout"
            )
        ),
        "replica_retry_limit": (
            configuration.get(
                "replicaRetryLimit"
            )
        ),
    }


def staging_inventory(
    *,
    resource_group: str,
    environment_name: str,
    identity_name: str,
    api_name: str,
    dashboard_name: str,
    storage_account: str,
    acr_name: str,
) -> dict[str, Any]:
    """Inspect current staging Azure resources."""

    resource_group_payload = (
        safe_json_command(
            [
                "az",
                "group",
                "show",
                "--name",
                resource_group,
            ]
        )
    )

    environment_payload = (
        safe_json_command(
            [
                "az",
                "containerapp",
                "env",
                "show",
                "--resource-group",
                resource_group,
                "--name",
                environment_name,
            ]
        )
    )

    identity_payload = (
        safe_json_command(
            [
                "az",
                "identity",
                "show",
                "--resource-group",
                resource_group,
                "--name",
                identity_name,
            ]
        )
    )

    storage_payload = (
        safe_json_command(
            [
                "az",
                "storage",
                "account",
                "show",
                "--resource-group",
                resource_group,
                "--name",
                storage_account,
            ]
        )
    )

    acr_payload = (
        safe_json_command(
            [
                "az",
                "acr",
                "show",
                "--name",
                acr_name,
            ]
        )
    )

    jobs = {
        "hourly_features": (
            inspect_job(
                resource_group=resource_group,
                job_name=(
                    "job-pearls-aqi-features"
                ),
            )
        ),
        "forecast": (
            inspect_job(
                resource_group=resource_group,
                job_name=(
                    "job-pearls-aqi-forecast"
                ),
            )
        ),
        "daily_retraining": (
            inspect_job(
                resource_group=resource_group,
                job_name=(
                    "job-pearls-aqi-retraining"
                ),
            )
        ),
        "monitoring": (
            inspect_job(
                resource_group=resource_group,
                job_name=(
                    "job-pearls-aqi-monitoring"
                ),
            )
        ),
    }

    return {
        "resource_group": {
            "exists": isinstance(
                resource_group_payload,
                dict,
            ),
            "name": resource_group,
            "location": (
                resource_group_payload.get(
                    "location"
                )
                if isinstance(
                    resource_group_payload,
                    dict,
                )
                else None
            ),
        },
        "container_apps_environment": {
            "exists": isinstance(
                environment_payload,
                dict,
            ),
            "name": environment_name,
            "provisioning_state": (
                environment_payload.get(
                    "properties",
                    {},
                ).get(
                    "provisioningState"
                )
                if isinstance(
                    environment_payload,
                    dict,
                )
                else None
            ),
        },
        "managed_identity": {
            "exists": isinstance(
                identity_payload,
                dict,
            ),
            "name": identity_name,
            "client_id_present": bool(
                identity_payload.get(
                    "clientId"
                )
                if isinstance(
                    identity_payload,
                    dict,
                )
                else None
            ),
            "principal_id_present": bool(
                identity_payload.get(
                    "principalId"
                )
                if isinstance(
                    identity_payload,
                    dict,
                )
                else None
            ),
        },
        "storage": {
            "exists": isinstance(
                storage_payload,
                dict,
            ),
            "account_name": (
                storage_account
            ),
            "container": (
                DEFAULT_STAGING_CONTAINER
            ),
            "public_blob_access": (
                storage_payload.get(
                    "allowBlobPublicAccess"
                )
                if isinstance(
                    storage_payload,
                    dict,
                )
                else None
            ),
        },
        "acr": {
            "exists": isinstance(
                acr_payload,
                dict,
            ),
            "name": acr_name,
            "login_server": (
                acr_payload.get(
                    "loginServer"
                )
                if isinstance(
                    acr_payload,
                    dict,
                )
                else None
            ),
        },
        "api": inspect_container_app(
            resource_group=resource_group,
            app_name=api_name,
        ),
        "dashboard": (
            inspect_container_app(
                resource_group=resource_group,
                app_name=dashboard_name,
            )
        ),
        "jobs": jobs,
    }


def build_findings(
    *,
    staging: dict[str, Any],
    git: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build important production-readiness observations."""

    findings: list[
        dict[str, Any]
    ] = []

    api_environment = (
        staging.get(
            "api",
            {},
        ).get(
            "environment",
            {},
        )
    )

    staging_aging = (
        api_environment.get(
            (
                "PEARLS_API_FORECAST_"
                "AGING_THRESHOLD_HOURS"
            ),
            {},
        ).get(
            "value"
        )
    )

    staging_stale = (
        api_environment.get(
            (
                "PEARLS_API_FORECAST_"
                "STALENESS_THRESHOLD_HOURS"
            ),
            {},
        ).get(
            "value"
        )
    )

    findings.append(
        {
            "severity": "INFO",
            "code": (
                "PRODUCTION_ARTIFACT_"
                "ISOLATION_REQUIRED"
            ),
            "message": (
                "Production should use "
                "'artifacts-prod' while staging "
                "continues using 'artifacts'."
            ),
        }
    )

    findings.append(
        {
            "severity": "INFO",
            "code": (
                "DASHBOARD_API_ONLY_"
                "DEPENDENCY"
            ),
            "message": (
                "The dashboard consumes FastAPI "
                "only and requires no direct Blob, "
                "Hopsworks, or model-registry access."
            ),
        }
    )

    findings.append(
        {
            "severity": (
                "WARNING"
                if not git[
                    "working_tree_clean"
                ]
                else "INFO"
            ),
            "code": (
                "SOURCE_TREE_STATE"
            ),
            "message": (
                "Production images must be built "
                "from a clean committed revision."
            ),
        }
    )

    findings.append(
        {
            "severity": "DECISION_REQUIRED",
            "code": (
                "API_FRESHNESS_THRESHOLDS"
            ),
            "message": (
                "API defaults/local configuration "
                "use 6h aging / 12h stale, while "
                "the current staging deployment "
                f"reports aging={staging_aging!r} "
                f"and stale={staging_stale!r}. "
                "Production thresholds must be "
                "selected explicitly in Phase 10M-C."
            ),
        }
    )

    findings.append(
        {
            "severity": "INFO",
            "code": (
                "API_LOCAL_FALLBACK_PRESENT"
            ),
            "message": (
                "Dockerfile.api contains a local "
                "AQI fallback bundle, but production "
                "will explicitly configure "
                "artifact_backend=azure_blob."
            ),
        }
    )

    findings.append(
        {
            "severity": "INFO",
            "code": (
                "SHARED_CONTAINER_APPS_ENVIRONMENT"
            ),
            "message": (
                "Production reuses the existing "
                "Container Apps environment because "
                "the Azure subscription environment "
                "quota prevents creation of a second one."
            ),
        }
    )

    return findings


def build_inventory(
    *,
    resource_group: str,
    environment_name: str,
    identity_name: str,
    api_name: str,
    dashboard_name: str,
    storage_account: str,
    acr_name: str,
) -> dict[str, Any]:
    """Build the complete deployment inventory."""

    generated_at = utc_now()

    git = git_inventory()

    staging = staging_inventory(
        resource_group=resource_group,
        environment_name=(
            environment_name
        ),
        identity_name=identity_name,
        api_name=api_name,
        dashboard_name=(
            dashboard_name
        ),
        storage_account=(
            storage_account
        ),
        acr_name=acr_name,
    )

    contracts = (
        repository_contracts()
    )

    production = (
        planned_production_configuration()
    )

    findings = build_findings(
        staging=staging,
        git=git,
    )

    missing_staging_resources = []

    if not staging[
        "resource_group"
    ][
        "exists"
    ]:
        missing_staging_resources.append(
            "resource_group"
        )

    if not staging[
        "container_apps_environment"
    ][
        "exists"
    ]:
        missing_staging_resources.append(
            "container_apps_environment"
        )

    if not staging[
        "api"
    ][
        "exists"
    ]:
        missing_staging_resources.append(
            "api"
        )

    if not staging[
        "dashboard"
    ][
        "exists"
    ]:
        missing_staging_resources.append(
            "dashboard"
        )

    status = (
        "PRODUCTION_DEPLOYMENT_INVENTORY_READY"
        if not missing_staging_resources
        else (
            "PRODUCTION_DEPLOYMENT_"
            "INVENTORY_INCOMPLETE"
        )
    )

    return {
        "phase": "10M",
        "subphase": "10M-A",
        "generated_at_utc": (
            generated_at.isoformat()
        ),
        "status": status,
        "read_only": True,
        "source_revision": git,
        "repository_contracts": (
            contracts
        ),
        "staging": staging,
        "production_plan": (
            production
        ),
        "findings": findings,
        "missing_staging_resources": (
            missing_staging_resources
        ),
        "production_resources_changed": (
            False
        ),
        "staging_resources_changed": (
            False
        ),
        "artifact_pointers_changed": (
            False
        ),
        "model_registry_changed": (
            False
        ),
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Atomically save inventory report."""

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
            "Inspect repository and staging Azure "
            "resources before production deployment."
        )
    )

    parser.add_argument(
        "--resource-group",
        default=(
            DEFAULT_STAGING_RESOURCE_GROUP
        ),
    )

    parser.add_argument(
        "--environment",
        default=(
            DEFAULT_STAGING_ENVIRONMENT
        ),
    )

    parser.add_argument(
        "--identity",
        default=(
            DEFAULT_STAGING_IDENTITY
        ),
    )

    parser.add_argument(
        "--api",
        default=(
            DEFAULT_STAGING_API
        ),
    )

    parser.add_argument(
        "--dashboard",
        default=(
            DEFAULT_STAGING_DASHBOARD
        ),
    )

    parser.add_argument(
        "--storage-account",
        default=(
            DEFAULT_STORAGE_ACCOUNT
        ),
    )

    parser.add_argument(
        "--acr",
        default=DEFAULT_ACR_NAME,
    )

    arguments = parser.parse_args()

    try:
        report = build_inventory(
            resource_group=(
                arguments.resource_group
            ),
            environment_name=(
                arguments.environment
            ),
            identity_name=(
                arguments.identity
            ),
            api_name=arguments.api,
            dashboard_name=(
                arguments.dashboard
            ),
            storage_account=(
                arguments.storage_account
            ),
            acr_name=arguments.acr,
        )

        exit_code = (
            0
            if report["status"]
            == (
                "PRODUCTION_DEPLOYMENT_"
                "INVENTORY_READY"
            )
            else 1
        )

    except Exception as error:
        report = {
            "phase": "10M",
            "subphase": "10M-A",
            "generated_at_utc": (
                utc_now().isoformat()
            ),
            "status": (
                "PRODUCTION_DEPLOYMENT_"
                "INVENTORY_FAILED"
            ),
            "read_only": True,
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(
                error
            ),
            "production_resources_changed": (
                False
            ),
            "staging_resources_changed": (
                False
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