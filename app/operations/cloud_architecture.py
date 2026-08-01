"""Generate the cost-aware Azure cloud architecture inventory.

This module documents the minimum Azure architecture planned for the
Pearls AQI Predictor.

It does not authenticate with Azure and does not create cloud resources.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]

REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "cloud_resource_inventory.json"
)


class CloudArchitectureError(RuntimeError):
    """Raised when the cloud architecture configuration is invalid."""


def normalize_resource_suffix(
    value: str,
) -> str:
    """Normalize a suffix for Azure resource names."""

    normalized = "".join(
        character
        for character in value.lower()
        if character.isalnum()
    )

    if not normalized:
        raise CloudArchitectureError(
            "AZURE_RESOURCE_SUFFIX must contain at least "
            "one letter or number."
        )

    return normalized


def get_resource_suffix() -> str:
    """Return the suffix used for globally unique Azure names."""

    configured_suffix = os.getenv(
        "AZURE_RESOURCE_SUFFIX",
        "riyan",
    )

    return normalize_resource_suffix(
        configured_suffix
    )


def get_azure_location() -> str:
    """Return the provisional Azure region."""

    location = os.getenv(
        "AZURE_LOCATION",
        "centralindia",
    )

    normalized = (
        location.strip()
        .lower()
        .replace(" ", "")
    )

    if not normalized:
        raise CloudArchitectureError(
            "AZURE_LOCATION cannot be empty."
        )

    return normalized


def build_resource_inventory(
    *,
    suffix: str,
) -> list[dict[str, Any]]:
    """Build the minimum Azure resource inventory."""

    resource_group = "rg-pearls-aqi-demo"

    return [
        {
            "logical_name": "resource_group",
            "resource_name": resource_group,
            "azure_resource_type": (
                "Microsoft.Resources/resourceGroups"
            ),
            "service": "Azure Resource Group",
            "sku": None,
            "purpose": (
                "Contain all internship deployment resources."
            ),
            "public_access": False,
            "estimated_usage": (
                "One shared cost-aware demo environment."
            ),
        },
        {
            "logical_name": "container_registry",
            "resource_name": (
                f"acrpearlsaqi{suffix}"
            ),
            "azure_resource_type": (
                "Microsoft.ContainerRegistry/registries"
            ),
            "service": "Azure Container Registry",
            "sku": "Basic",
            "purpose": (
                "Store immutable FastAPI, Streamlit, "
                "and pipeline container images."
            ),
            "public_access": False,
            "estimated_usage": (
                "Three small application images tagged "
                "with immutable Git commit SHAs."
            ),
        },
        {
            "logical_name": (
                "container_apps_environment"
            ),
            "resource_name": (
                "cae-pearls-aqi-demo"
            ),
            "azure_resource_type": (
                "Microsoft.App/managedEnvironments"
            ),
            "service": (
                "Azure Container Apps Environment"
            ),
            "sku": "Consumption",
            "purpose": (
                "Host FastAPI, Streamlit, and the "
                "shared batch pipeline job."
            ),
            "public_access": False,
            "estimated_usage": (
                "Consumption-based environment with "
                "scale-to-zero where practical."
            ),
        },
        {
            "logical_name": "fastapi",
            "resource_name": (
                "ca-pearls-aqi-api"
            ),
            "azure_resource_type": (
                "Microsoft.App/containerApps"
            ),
            "service": "Azure Container App",
            "sku": "Consumption",
            "purpose": (
                "Serve forecast, AQI, alerts, metadata, "
                "liveness, and readiness endpoints."
            ),
            "public_access": True,
            "estimated_usage": (
                "Low-traffic public internship API."
            ),
        },
        {
            "logical_name": "streamlit",
            "resource_name": (
                "ca-pearls-aqi-dashboard"
            ),
            "azure_resource_type": (
                "Microsoft.App/containerApps"
            ),
            "service": "Azure Container App",
            "sku": "Consumption",
            "purpose": (
                "Serve the public Streamlit forecasting dashboard."
            ),
            "public_access": True,
            "estimated_usage": (
                "Low-traffic demonstration dashboard."
            ),
        },
        {
            "logical_name": "pipeline_job",
            "resource_name": (
                "caj-pearls-aqi-pipeline"
            ),
            "azure_resource_type": (
                "Microsoft.App/jobs"
            ),
            "service": (
                "Azure Container Apps Job"
            ),
            "sku": "Consumption",
            "purpose": (
                "Run live inference, AQI processing, "
                "incremental features, retraining checks, "
                "and approved manual operations."
            ),
            "public_access": False,
            "estimated_usage": (
                "Manual initially, with selected schedules "
                "enabled later."
            ),
        },
        {
            "logical_name": "storage",
            "resource_name": (
                f"stpearlsaqi{suffix}"
            ),
            "azure_resource_type": (
                "Microsoft.Storage/storageAccounts"
            ),
            "service": "Azure Blob Storage",
            "sku": "Standard_LRS",
            "purpose": (
                "Store immutable inference, AQI, report, "
                "and deployment artifacts."
            ),
            "public_access": False,
            "estimated_usage": (
                "Small Parquet, CSV, JSON, and report artifacts."
            ),
        },
        {
            "logical_name": "key_vault",
            "resource_name": (
                f"kv-pearls-aqi-{suffix}"
            ),
            "azure_resource_type": (
                "Microsoft.KeyVault/vaults"
            ),
            "service": "Azure Key Vault",
            "sku": "Standard",
            "purpose": (
                "Store OpenAQ, Hopsworks, and future "
                "notification credentials."
            ),
            "public_access": False,
            "estimated_usage": (
                "A small number of application secrets."
            ),
        },
        {
            "logical_name": "logging",
            "resource_name": (
                "log-pearls-aqi-demo"
            ),
            "azure_resource_type": (
                "Microsoft.OperationalInsights/workspaces"
            ),
            "service": (
                "Azure Log Analytics Workspace"
            ),
            "sku": "PerGB2018",
            "purpose": (
                "Collect FastAPI, Streamlit, and "
                "pipeline execution logs."
            ),
            "public_access": False,
            "estimated_usage": (
                "Low-volume logs with short retention."
            ),
        },
    ]


def build_pipeline_commands() -> list[dict[str, Any]]:
    """Document commands supported by the shared pipeline image."""

    return [
        {
            "operation": "live_inference",
            "command": (
                "python -m "
                "app.pipelines.live_inference"
            ),
            "execution_mode": (
                "scheduled_or_manual"
            ),
            "enabled_initially": True,
        },
        {
            "operation": "aqi_alert_processing",
            "command": (
                "python -m "
                "app.pipelines.aqi_alert_pipeline"
            ),
            "execution_mode": (
                "scheduled_or_manual"
            ),
            "enabled_initially": True,
        },
        {
            "operation": "incremental_features",
            "command": (
                "python -m "
                "app.pipelines.incremental_features"
            ),
            "execution_mode": (
                "manual_initially"
            ),
            "enabled_initially": False,
        },
        {
            "operation": "retraining_eligibility",
            "command": (
                "python -m "
                "app.pipelines.retraining_cycle"
            ),
            "execution_mode": (
                "manual_initially"
            ),
            "enabled_initially": False,
        },
        {
            "operation": "champion_challenger",
            "command": (
                "python -m "
                "app.pipelines.champion_challenger"
            ),
            "execution_mode": (
                "manual_protected"
            ),
            "enabled_initially": False,
        },
        {
            "operation": "historical_backfill",
            "command": (
                "python -m "
                "app.pipelines.historical_backfill"
            ),
            "execution_mode": (
                "manual_protected"
            ),
            "enabled_initially": False,
        },
    ]


def build_storage_structure() -> dict[str, Any]:
    """Document the planned Blob Storage structure."""

    return {
        "container_name": "artifacts",
        "paths": {
            "inference_runs": (
                "inference/runs/<pipeline_run_id>/"
            ),
            "aqi_runs": (
                "aqi/runs/<phase_6_run_id>/"
            ),
            "latest_pointer": (
                "latest/pointer.json"
            ),
            "pipeline_reports": (
                "reports/pipelines/"
            ),
            "deployment_reports": (
                "reports/deployments/"
            ),
        },
        "publication_policy": {
            "immutable_run_directories": True,
            "latest_updated_after_validation": True,
            "previous_successful_run_preserved": True,
            "partial_artifacts_exposed": False,
        },
    }


def build_cost_controls() -> dict[str, Any]:
    """Document cost-control decisions."""

    return {
        "single_demo_environment": True,
        "separate_staging_environment": False,
        "separate_production_environment": False,
        "container_apps_consumption_plan": True,
        "scale_to_zero_where_practical": True,
        "container_registry_sku": "Basic",
        "storage_redundancy": "Standard_LRS",
        "manual_retraining_initially": True,
        "manual_backfill_initially": True,
        "automatic_model_promotion": False,
        "kubernetes_used": False,
        "relational_database_used": False,
        "private_networking_used": False,
        "premium_registry_used": False,
        "limited_log_retention": True,
        "blob_lifecycle_policy_planned": True,
    }


def build_cloud_resource_inventory() -> dict[str, Any]:
    """Build the complete Phase 10B inventory report."""

    suffix = get_resource_suffix()
    azure_location = get_azure_location()

    resources = build_resource_inventory(
        suffix=suffix
    )

    return {
        "phase": "10B",
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "status": (
            "CLOUD_ARCHITECTURE_SELECTED"
        ),
        "project_name": (
            "Pearls AQI Predictor"
        ),
        "cloud_provider": (
            "Microsoft Azure"
        ),
        "subscription_type": (
            "Azure for Students"
        ),
        "environment": "demo",
        "azure_location": azure_location,
        "location_validation_status": (
            "REQUIRES_SUBSCRIPTION_VERIFICATION"
        ),
        "cost_optimized": True,
        "architecture_summary": {
            "serving_platform": (
                "Azure Container Apps"
            ),
            "batch_platform": (
                "Azure Container Apps Jobs"
            ),
            "container_registry": (
                "Azure Container Registry Basic"
            ),
            "artifact_storage": (
                "Azure Blob Storage"
            ),
            "secret_management": (
                "Azure Key Vault"
            ),
            "logging": (
                "Azure Log Analytics"
            ),
        },
        "resource_suffix": suffix,
        "resource_count": len(resources),
        "resources": resources,
        "pipeline_commands": (
            build_pipeline_commands()
        ),
        "storage": (
            build_storage_structure()
        ),
        "cost_controls": (
            build_cost_controls()
        ),
        "environment_strategy": {
            "development": (
                "Local Docker Compose"
            ),
            "cloud_demo": (
                "Single cost-aware Azure environment"
            ),
            "future_staging": (
                "Not created"
            ),
            "future_production": (
                "Not created"
            ),
        },
        "security_decisions": {
            "secrets_in_images": False,
            "secrets_committed_to_git": False,
            "key_vault_planned": True,
            "managed_identity_planned": True,
            "github_oidc_planned": True,
        },
        "operational_decisions": {
            "fastapi_public": True,
            "streamlit_public": True,
            "batch_job_public_ingress": False,
            "streamlit_reads_fastapi_only": True,
            "batch_jobs_run_outside_api_requests": True,
            "automatic_retraining_enabled": False,
            "automatic_model_promotion_enabled": False,
        },
        "resources_created": False,
        "ready_for_phase_10c": True,
    }


def save_cloud_resource_inventory(
    report: dict[str, Any],
) -> Path:
    """Save the Phase 10B inventory report."""

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
    """Generate the cloud architecture inventory."""

    parser = argparse.ArgumentParser(
        description=(
            "Generate the cost-aware Azure "
            "resource inventory for Phase 10B."
        )
    )

    parser.parse_args()

    try:
        report = (
            build_cloud_resource_inventory()
        )

        report_path = (
            save_cloud_resource_inventory(
                report
            )
        )

        exit_code = 0

    except Exception as error:
        report = {
            "phase": "10B",
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": (
                "CLOUD_ARCHITECTURE_INVENTORY_FAILED"
            ),
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(error),
            "resources_created": False,
        }

        report_path = (
            save_cloud_resource_inventory(
                report
            )
        )

        exit_code = 1

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