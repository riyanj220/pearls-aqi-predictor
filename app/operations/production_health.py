"""Build a read-only production health snapshot.

The monitor inspects:

- recent Azure Container Apps Job executions;
- latest timestamps in the three Hopsworks feature groups;
- freshness of the latest published AQI artifact.

It does not modify Azure resources, Hopsworks data, model registry
state, Blob artifacts, or production models.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import PROJECT_ROOT
from app.mlops.client import (
    connect_to_hopsworks,
)
from app.mlops.config import (
    FeatureStoreBackend,
    MLOpsSettings,
    get_mlops_settings,
)
from app.mlops.contracts import (
    FeatureGroupContract,
    build_feature_group_contracts,
)
from app.pipelines.historical_backfill import (
    load_feature_columns,
)
from app.pipelines.publish_forecast import (
    create_configured_repository,
)

import os
import urllib.error
import urllib.parse
import urllib.request

from azure.identity import (
    DefaultAzureCredential,
)

REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "production_health_report.json"
)

DEFAULT_RESOURCE_GROUP = (
    "rg-pearls-aqi-staging"
)

DEFAULT_FEATURE_JOB = (
    "job-pearls-aqi-features"
)

DEFAULT_FORECAST_JOB = (
    "job-pearls-aqi-forecast"
)

DEFAULT_RETRAINING_JOB = (
    "job-pearls-aqi-retraining"
)

AZURE_MANAGEMENT_SCOPE = (
    "https://management.azure.com/.default"
)

AZURE_MANAGEMENT_ENDPOINT = (
    "https://management.azure.com"
)

AZURE_CONTAINER_APPS_API_VERSION = (
    "2026-01-01"
)

AQI_ARTIFACT_TYPE = "aqi"

HEALTHY = "HEALTHY"
WARNING = "WARNING"
CRITICAL = "CRITICAL"
UNKNOWN = "UNKNOWN"


class ProductionHealthError(RuntimeError):
    """Raised when production health cannot be inspected."""


@dataclass(frozen=True)
class FreshnessThreshold:
    """Warning and critical age thresholds."""

    warning_after_hours: float
    critical_after_hours: float

    def __post_init__(self) -> None:
        if self.warning_after_hours < 0:
            raise ValueError(
                "warning_after_hours cannot be negative."
            )

        if (
            self.critical_after_hours
            <= self.warning_after_hours
        ):
            raise ValueError(
                "critical_after_hours must be greater "
                "than warning_after_hours."
            )


FEATURE_DATA_THRESHOLD = FreshnessThreshold(
    warning_after_hours=3,
    critical_after_hours=6,
)

AQI_ARTIFACT_THRESHOLD = FreshnessThreshold(
    warning_after_hours=7,
    critical_after_hours=13,
)

FEATURE_JOB_THRESHOLD = FreshnessThreshold(
    warning_after_hours=2,
    critical_after_hours=3,
)

FORECAST_JOB_THRESHOLD = FreshnessThreshold(
    warning_after_hours=7,
    critical_after_hours=13,
)

RETRAINING_JOB_THRESHOLD = FreshnessThreshold(
    warning_after_hours=30,
    critical_after_hours=48,
)


def utc_now() -> datetime:
    """Return the current timezone-aware UTC time."""

    return datetime.now(
        timezone.utc
    )


def parse_utc_timestamp(
    value: Any,
) -> datetime | None:
    """Parse one value as a timezone-aware UTC datetime."""

    if value is None:
        return None

    try:
        timestamp = pd.Timestamp(value)
    except (
        TypeError,
        ValueError,
    ):
        return None

    if pd.isna(timestamp):
        return None

    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(
            "UTC"
        )
    else:
        timestamp = timestamp.tz_convert(
            "UTC"
        )

    return timestamp.to_pydatetime()


def calculate_age_hours(
    *,
    timestamp: datetime,
    now: datetime,
) -> float:
    """Return non-negative age in hours."""

    age_seconds = (
        now - timestamp
    ).total_seconds()

    return round(
        max(
            age_seconds,
            0.0,
        )
        / 3600,
        3,
    )


def classify_age(
    *,
    age_hours: float | None,
    threshold: FreshnessThreshold,
) -> str:
    """Classify timestamp freshness."""

    if age_hours is None:
        return UNKNOWN

    if (
        age_hours
        > threshold.critical_after_hours
    ):
        return CRITICAL

    if (
        age_hours
        > threshold.warning_after_hours
    ):
        return WARNING

    return HEALTHY


def build_freshness_result(
    *,
    latest_timestamp: datetime | None,
    threshold: FreshnessThreshold,
    now: datetime,
) -> dict[str, Any]:
    """Build one timestamp-freshness result."""

    age_hours = (
        calculate_age_hours(
            timestamp=latest_timestamp,
            now=now,
        )
        if latest_timestamp is not None
        else None
    )

    status = classify_age(
        age_hours=age_hours,
        threshold=threshold,
    )

    return {
        "status": status,
        "latest_timestamp_utc": (
            latest_timestamp.isoformat()
            if latest_timestamp is not None
            else None
        ),
        "age_hours": age_hours,
        "thresholds": {
            "warning_after_hours": (
                threshold
                .warning_after_hours
            ),
            "critical_after_hours": (
                threshold
                .critical_after_hours
            ),
        },
    }

def read_environment_value(
    name: str,
    *,
    default: str | None = None,
) -> str | None:
    """Read and normalize one environment value."""

    value = os.getenv(
        name,
        default,
    )

    if value is None:
        return None

    normalized = value.strip()

    return normalized or None


def should_use_azure_resource_manager() -> bool:
    """Return whether ARM should replace local Azure CLI access."""

    backend = (
        read_environment_value(
            "AZURE_JOB_QUERY_BACKEND",
            default="auto",
        )
        or "auto"
    ).lower()

    if backend not in {
        "auto",
        "cli",
        "arm",
    }:
        raise ProductionHealthError(
            "AZURE_JOB_QUERY_BACKEND must be "
            "'auto', 'cli', or 'arm'."
        )

    if backend == "arm":
        return True

    if backend == "cli":
        return False

    return bool(
        read_environment_value(
            "AZURE_SUBSCRIPTION_ID"
        )
    )

def run_azure_arm_get(
    *,
    resource_path: str,
) -> Any:
    """Perform one authenticated Azure Resource Manager GET request."""

    subscription_id = (
        read_environment_value(
            "AZURE_SUBSCRIPTION_ID"
        )
    )

    if subscription_id is None:
        raise ProductionHealthError(
            "AZURE_SUBSCRIPTION_ID is required "
            "for ARM-based job inspection."
        )

    managed_identity_client_id = (
        read_environment_value(
            "AZURE_CLIENT_ID"
        )
    )

    credential = DefaultAzureCredential(
        managed_identity_client_id=(
            managed_identity_client_id
        ),
        exclude_interactive_browser_credential=True,
    )

    token = credential.get_token(
        AZURE_MANAGEMENT_SCOPE
    )

    separator = (
        "&"
        if "?" in resource_path
        else "?"
    )

    url = (
        f"{AZURE_MANAGEMENT_ENDPOINT}"
        f"/subscriptions/"
        f"{urllib.parse.quote(subscription_id, safe='')}"
        f"{resource_path}"
        f"{separator}api-version="
        f"{AZURE_CONTAINER_APPS_API_VERSION}"
    )

    request = urllib.request.Request(
        url=url,
        method="GET",
        headers={
            "Authorization": (
                f"Bearer {token.token}"
            ),
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:
            payload = response.read().decode(
                "utf-8"
            )

    except urllib.error.HTTPError as error:
        response_body = error.read().decode(
            "utf-8",
            errors="replace",
        )

        raise ProductionHealthError(
            "Azure Resource Manager request failed. "
            f"Status={error.code}, "
            f"resource={resource_path}, "
            f"response={response_body[:500]}"
        ) from error

    except urllib.error.URLError as error:
        raise ProductionHealthError(
            "Azure Resource Manager could not be reached."
        ) from error

    try:
        return json.loads(payload)

    except json.JSONDecodeError as error:
        raise ProductionHealthError(
            "Azure Resource Manager returned invalid JSON."
        ) from error

def run_azure_cli(
    arguments: list[str],
) -> Any:
    """Run Azure CLI and parse JSON output."""

    command = [
        "az",
        *arguments,
        "--output",
        "json",
    ]

    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        raise ProductionHealthError(
            "Azure CLI command failed.\n"
            f"Command: {' '.join(command)}\n"
            f"Error: {completed.stderr.strip()}"
        )

    try:
        return json.loads(
            completed.stdout
        )
    except json.JSONDecodeError as error:
        raise ProductionHealthError(
            "Azure CLI did not return valid JSON."
        ) from error


def load_job_executions(
    *,
    resource_group: str,
    job_name: str,
) -> list[dict[str, Any]]:
    """Load recent executions through ARM or the local Azure CLI."""

    if should_use_azure_resource_manager():
        encoded_resource_group = (
            urllib.parse.quote(
                resource_group,
                safe="",
            )
        )

        encoded_job_name = (
            urllib.parse.quote(
                job_name,
                safe="",
            )
        )

        payload = run_azure_arm_get(
            resource_path=(
                f"/resourceGroups/"
                f"{encoded_resource_group}"
                f"/providers/Microsoft.App/jobs/"
                f"{encoded_job_name}"
                f"/executions"
            )
        )

        if not isinstance(payload, dict):
            raise ProductionHealthError(
                "Azure execution response is not an object."
            )

        raw_executions = payload.get(
            "value",
            []
        )

    else:
        raw_executions = run_azure_cli(
            [
                "containerapp",
                "job",
                "execution",
                "list",
                "--resource-group",
                resource_group,
                "--name",
                job_name,
            ]
        )

    if not isinstance(
        raw_executions,
        list,
    ):
        raise ProductionHealthError(
            f"Execution response is not a list: {job_name}"
        )

    executions = [
        item
        for item in raw_executions
        if isinstance(item, dict)
    ]

    executions.sort(
        key=lambda item: str(
            item.get(
                "properties",
                {},
            ).get(
                "startTime",
                "",
            )
        ),
        reverse=True,
    )

    return executions

def inspect_azure_job(
    *,
    resource_group: str,
    job_name: str,
    threshold: FreshnessThreshold,
    now: datetime,
) -> dict[str, Any]:
    """Inspect the latest execution of one Azure job."""

    try:
        executions = load_job_executions(
            resource_group=resource_group,
            job_name=job_name,
        )

        if not executions:
            return {
                "status": UNKNOWN,
                "job_name": job_name,
                "latest_execution": None,
                "reason": (
                    "No job executions were found."
                ),
                "thresholds": {
                    "warning_after_hours": (
                        threshold
                        .warning_after_hours
                    ),
                    "critical_after_hours": (
                        threshold
                        .critical_after_hours
                    ),
                },
            }

        execution = executions[0]

        properties = execution.get(
            "properties",
            {},
        )

        execution_status = str(
            properties.get(
                "status",
                "",
            )
        )

        start_time = parse_utc_timestamp(
            properties.get(
                "startTime"
            )
        )

        end_time = parse_utc_timestamp(
            properties.get(
                "endTime"
            )
        )

        freshness_time = (
            end_time
            or start_time
        )

        freshness = build_freshness_result(
            latest_timestamp=freshness_time,
            threshold=threshold,
            now=now,
        )

        if execution_status != "Succeeded":
            component_status = CRITICAL
            reason = (
                "Latest execution did not succeed."
            )
        else:
            component_status = freshness[
                "status"
            ]
            reason = (
                "Latest execution succeeded."
            )

        return {
            "status": component_status,
            "job_name": job_name,
            "reason": reason,
            "latest_execution": {
                "name": execution.get(
                    "name"
                ),
                "status": execution_status,
                "start_time_utc": (
                    start_time.isoformat()
                    if start_time is not None
                    else None
                ),
                "end_time_utc": (
                    end_time.isoformat()
                    if end_time is not None
                    else None
                ),
                "age_hours": (
                    freshness[
                        "age_hours"
                    ]
                ),
            },
            "thresholds": (
                freshness["thresholds"]
            ),
            "execution_count_returned": len(
                executions
            ),
        }

    except Exception as error:
        return {
            "status": UNKNOWN,
            "job_name": job_name,
            "latest_execution": None,
            "reason": (
                "Azure job health could not be inspected."
            ),
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(error),
            "thresholds": {
                "warning_after_hours": (
                    threshold
                    .warning_after_hours
                ),
                "critical_after_hours": (
                    threshold
                    .critical_after_hours
                ),
            },
        }


def build_feature_contracts(
    settings: MLOpsSettings,
) -> dict[str, FeatureGroupContract]:
    """Build the configured feature-group contracts."""

    feature_columns = load_feature_columns(
        PROJECT_ROOT
        / "models"
        / "model_feature_columns.json"
    )

    return build_feature_group_contracts(
        pm25_version=(
            settings
            .hopsworks_pm25_feature_group_version
        ),
        weather_version=(
            settings
            .hopsworks_weather_feature_group_version
        ),
        engineered_version=(
            settings
            .hopsworks_engineered_feature_group_version
        ),
        pm25_name=(
            settings
            .hopsworks_pm25_feature_group_name
        ),
        weather_name=(
            settings
            .hopsworks_weather_feature_group_name
        ),
        engineered_name=(
            settings
            .hopsworks_engineered_feature_group_name
        ),
        model_feature_columns=(
            feature_columns
        ),
    )


def read_latest_feature_timestamp(
    *,
    feature_group: Any,
    contract: FeatureGroupContract,
) -> datetime | None:
    """Read the latest valid event timestamp from a feature group."""

    try:
        dataframe = feature_group.read(
            dataframe_type="pandas"
        )
    except Exception as error:
        raise ProductionHealthError(
            "Could not read feature group: "
            f"{contract.name}"
        ) from error

    if dataframe is None or dataframe.empty:
        return None

    dataframe.columns = [
        str(column).lower()
        for column in dataframe.columns
    ]

    event_time_column = (
        contract.event_time.lower()
    )

    if (
        event_time_column
        not in dataframe.columns
    ):
        raise ProductionHealthError(
            f"{contract.name} does not contain "
            f"event-time column {contract.event_time!r}."
        )

    values = pd.to_datetime(
        dataframe[event_time_column],
        utc=True,
        errors="coerce",
    ).dropna()

    if values.empty:
        return None

    return values.max().to_pydatetime()


def inspect_hopsworks_freshness(
    *,
    settings: MLOpsSettings,
    now: datetime,
) -> dict[str, Any]:
    """Inspect latest event times in all production feature groups."""

    contracts = build_feature_contracts(
        settings
    )

    if (
        settings.feature_store_backend
        != FeatureStoreBackend.HOPSWORKS
    ):
        return {
            "status": UNKNOWN,
            "reason": (
                "FEATURE_STORE_BACKEND is not configured "
                "as hopsworks."
            ),
            "groups": {},
        }

    try:
        resources = connect_to_hopsworks(
            settings
        )

        if resources.feature_store is None:
            raise ProductionHealthError(
                "Hopsworks Feature Store was not resolved."
            )

        groups: dict[str, Any] = {}

        for logical_name, contract in (
            contracts.items()
        ):
            try:
                feature_group = (
                    resources.feature_store
                    .get_feature_group(
                        name=contract.name,
                        version=contract.version,
                    )
                )

                latest_timestamp = (
                    read_latest_feature_timestamp(
                        feature_group=feature_group,
                        contract=contract,
                    )
                )

                freshness = (
                    build_freshness_result(
                        latest_timestamp=(
                            latest_timestamp
                        ),
                        threshold=(
                            FEATURE_DATA_THRESHOLD
                        ),
                        now=now,
                    )
                )

                groups[logical_name] = {
                    "status": (
                        freshness["status"]
                    ),
                    "name": contract.name,
                    "version": contract.version,
                    "event_time_column": (
                        contract.event_time
                    ),
                    "primary_key": list(
                        contract.primary_key
                    ),
                    "latest_timestamp_utc": (
                        freshness[
                            "latest_timestamp_utc"
                        ]
                    ),
                    "age_hours": (
                        freshness[
                            "age_hours"
                        ]
                    ),
                    "thresholds": (
                        freshness[
                            "thresholds"
                        ]
                    ),
                }

            except Exception as error:
                groups[logical_name] = {
                    "status": UNKNOWN,
                    "name": contract.name,
                    "version": contract.version,
                    "event_time_column": (
                        contract.event_time
                    ),
                    "primary_key": list(
                        contract.primary_key
                    ),
                    "latest_timestamp_utc": None,
                    "age_hours": None,
                    "error_type": (
                        type(error).__name__
                    ),
                    "error_message": str(error),
                    "thresholds": {
                        "warning_after_hours": (
                            FEATURE_DATA_THRESHOLD
                            .warning_after_hours
                        ),
                        "critical_after_hours": (
                            FEATURE_DATA_THRESHOLD
                            .critical_after_hours
                        ),
                    },
                }

        overall_status = worst_status(
            [
                value["status"]
                for value in groups.values()
            ]
        )

        return {
            "status": overall_status,
            "project_name": (
                resources.project_name
            ),
            "feature_store_name": (
                resources.feature_store_name
            ),
            "sdk_version": (
                resources.sdk_version
            ),
            "groups": groups,
        }

    except Exception as error:
        return {
            "status": UNKNOWN,
            "reason": (
                "Hopsworks freshness could not be inspected."
            ),
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(error),
            "groups": {},
        }


def inspect_aqi_artifact(
    *,
    now: datetime,
) -> dict[str, Any]:
    """Inspect the latest durable AQI artifact pointer."""

    try:
        repository = (
            create_configured_repository()
        )

        pointer = (
            repository.get_latest_pointer(
                AQI_ARTIFACT_TYPE
            )
        )

        published_at = (
            parse_utc_timestamp(
                pointer.get(
                    "published_at_utc"
                )
            )
        )

        freshness = (
            build_freshness_result(
                latest_timestamp=(
                    published_at
                ),
                threshold=(
                    AQI_ARTIFACT_THRESHOLD
                ),
                now=now,
            )
        )

        validation_status = pointer.get(
            "validation_status"
        )

        component_status = (
            freshness["status"]
        )

        reason = (
            "Latest AQI artifact is valid."
        )

        if (
            validation_status
            != "AQI_ALERT_PIPELINE_APPROVED"
        ):
            component_status = CRITICAL
            reason = (
                "Latest AQI artifact does not have "
                "the approved validation status."
            )

        return {
            "status": component_status,
            "reason": reason,
            "artifact_type": (
                AQI_ARTIFACT_TYPE
            ),
            "run_id": pointer.get(
                "run_id"
            ),
            "artifact_prefix": (
                pointer.get(
                    "artifact_prefix"
                )
            ),
            "manifest_path": (
                pointer.get(
                    "manifest_path"
                )
            ),
            "validation_status": (
                validation_status
            ),
            "published_at_utc": (
                freshness[
                    "latest_timestamp_utc"
                ]
            ),
            "age_hours": (
                freshness["age_hours"]
            ),
            "thresholds": (
                freshness["thresholds"]
            ),
        }

    except Exception as error:
        return {
            "status": UNKNOWN,
            "reason": (
                "Latest AQI artifact could not be inspected."
            ),
            "artifact_type": (
                AQI_ARTIFACT_TYPE
            ),
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(error),
            "published_at_utc": None,
            "age_hours": None,
            "thresholds": {
                "warning_after_hours": (
                    AQI_ARTIFACT_THRESHOLD
                    .warning_after_hours
                ),
                "critical_after_hours": (
                    AQI_ARTIFACT_THRESHOLD
                    .critical_after_hours
                ),
            },
        }


def worst_status(
    statuses: list[str],
) -> str:
    """Return the most severe status."""

    severity = {
        HEALTHY: 0,
        UNKNOWN: 1,
        WARNING: 2,
        CRITICAL: 3,
    }

    normalized = [
        status
        if status in severity
        else UNKNOWN
        for status in statuses
    ]

    if not normalized:
        return UNKNOWN

    return max(
        normalized,
        key=lambda status: severity[
            status
        ],
    )


def build_recommendations(
    *,
    jobs: dict[str, dict[str, Any]],
    feature_store: dict[str, Any],
    artifact: dict[str, Any],
) -> list[str]:
    """Build concise operational recommendations."""

    recommendations: list[str] = []

    for logical_name, result in jobs.items():
        status = result.get(
            "status"
        )

        if status == CRITICAL:
            recommendations.append(
                "Inspect the latest failed or stale "
                f"{logical_name} Azure job execution."
            )

        elif status == WARNING:
            recommendations.append(
                "Watch the next scheduled "
                f"{logical_name} execution."
            )

        elif status == UNKNOWN:
            recommendations.append(
                "Restore visibility into the "
                f"{logical_name} Azure job."
            )

    for logical_name, result in (
        feature_store.get(
            "groups",
            {}
        ).items()
    ):
        status = result.get(
            "status"
        )

        if status == CRITICAL:
            recommendations.append(
                "Investigate stale Hopsworks data for "
                f"{logical_name}."
            )

        elif status == WARNING:
            recommendations.append(
                "Verify the next hourly synchronization "
                f"updates {logical_name}."
            )

        elif status == UNKNOWN:
            recommendations.append(
                "Restore Hopsworks visibility for "
                f"{logical_name}."
            )

    artifact_status = artifact.get(
        "status"
    )

    if artifact_status == CRITICAL:
        recommendations.append(
            "Inspect the forecast publication job and "
            "the AQI Blob latest pointer."
        )

    elif artifact_status == WARNING:
        recommendations.append(
            "Verify the next six-hour forecast "
            "publication updates the AQI pointer."
        )

    elif artifact_status == UNKNOWN:
        recommendations.append(
            "Restore access to the AQI artifact repository."
        )

    if not recommendations:
        recommendations.append(
            "No immediate operational action is required."
        )

    return recommendations


def map_overall_report_status(
    component_status: str,
) -> str:
    """Map component severity to the public report status."""

    mapping = {
        HEALTHY: "PRODUCTION_HEALTHY",
        WARNING: "PRODUCTION_HEALTH_WARNING",
        CRITICAL: "PRODUCTION_HEALTH_CRITICAL",
        UNKNOWN: "PRODUCTION_HEALTH_UNKNOWN",
    }

    return mapping.get(
        component_status,
        "PRODUCTION_HEALTH_UNKNOWN",
    )


def run_production_health(
    *,
    resource_group: str,
    feature_job_name: str,
    forecast_job_name: str,
    retraining_job_name: str,
) -> dict[str, Any]:
    """Run one complete read-only health inspection."""

    started_at = utc_now()
    started_monotonic = time.monotonic()

    jobs = {
        "hourly_feature_job": (
            inspect_azure_job(
                resource_group=resource_group,
                job_name=feature_job_name,
                threshold=(
                    FEATURE_JOB_THRESHOLD
                ),
                now=started_at,
            )
        ),
        "forecast_publication_job": (
            inspect_azure_job(
                resource_group=resource_group,
                job_name=forecast_job_name,
                threshold=(
                    FORECAST_JOB_THRESHOLD
                ),
                now=started_at,
            )
        ),
        "daily_retraining_job": (
            inspect_azure_job(
                resource_group=resource_group,
                job_name=retraining_job_name,
                threshold=(
                    RETRAINING_JOB_THRESHOLD
                ),
                now=started_at,
            )
        ),
    }

    settings = get_mlops_settings()

    feature_store = (
        inspect_hopsworks_freshness(
            settings=settings,
            now=started_at,
        )
    )

    artifact = inspect_aqi_artifact(
        now=started_at
    )

    component_statuses = [
        result["status"]
        for result in jobs.values()
    ]

    component_statuses.extend(
        [
            feature_store["status"],
            artifact["status"],
        ]
    )

    overall_component_status = (
        worst_status(
            component_statuses
        )
    )

    completed_at = utc_now()

    return {
        "phase": "10L",
        "subphase": "10L-A",
        "pipeline_name": (
            "production_health"
        ),
        "generated_at_utc": (
            completed_at.isoformat()
        ),
        "status": (
            map_overall_report_status(
                overall_component_status
            )
        ),
        "overall_component_status": (
            overall_component_status
        ),
        "duration_seconds": round(
            time.monotonic()
            - started_monotonic,
            3,
        ),
        "read_only": True,
        "resource_group": resource_group,
        "jobs": jobs,
        "feature_store": feature_store,
        "aqi_artifact": artifact,
        "recommendations": (
            build_recommendations(
                jobs=jobs,
                feature_store=feature_store,
                artifact=artifact,
            )
        ),
        "production_data_changed": False,
        "production_model_changed": False,
        "azure_resources_changed": False,
        "artifact_pointer_changed": False,
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Atomically save the production-health report."""

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
            "Inspect production jobs, feature freshness, "
            "and AQI artifact freshness."
        )
    )

    parser.add_argument(
        "--resource-group",
        default=DEFAULT_RESOURCE_GROUP,
    )

    parser.add_argument(
        "--feature-job-name",
        default=DEFAULT_FEATURE_JOB,
    )

    parser.add_argument(
        "--forecast-job-name",
        default=DEFAULT_FORECAST_JOB,
    )

    parser.add_argument(
        "--retraining-job-name",
        default=DEFAULT_RETRAINING_JOB,
    )

    arguments = parser.parse_args()

    try:
        report = run_production_health(
            resource_group=(
                arguments.resource_group
            ),
            feature_job_name=(
                arguments.feature_job_name
            ),
            forecast_job_name=(
                arguments.forecast_job_name
            ),
            retraining_job_name=(
                arguments.retraining_job_name
            ),
        )

        # Warnings are observable operational states but do not fail
        # the read-only health command. Critical and unknown states do.
        exit_code = (
            0
            if report["overall_component_status"]
            in {
                HEALTHY,
                WARNING,
            }
            else 1
        )

    except Exception as error:
        report = {
            "phase": "10L",
            "subphase": "10L-A",
            "pipeline_name": (
                "production_health"
            ),
            "generated_at_utc": (
                utc_now().isoformat()
            ),
            "status": (
                "PRODUCTION_HEALTH_CHECK_FAILED"
            ),
            "overall_component_status": (
                UNKNOWN
            ),
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(error),
            "read_only": True,
            "production_data_changed": False,
            "production_model_changed": False,
            "azure_resources_changed": False,
            "artifact_pointer_changed": False,
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