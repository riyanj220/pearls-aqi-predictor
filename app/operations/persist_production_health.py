"""Persist production health and maintain deduplicated incidents.

This orchestration layer:

1. runs the read-only production health inspection;
2. publishes the complete report as an immutable artifact run;
3. compares current unhealthy components with active incident state;
4. creates, updates, or resolves incidents;
5. exposes whether an external notification should be delivered.

No external notification is sent in this subphase.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.artifacts.repository import (
    ArtifactRepository,
    ArtifactRepositoryError,
)
from app.core.config import PROJECT_ROOT
from app.operations.production_health import (
    CRITICAL,
    HEALTHY,
    UNKNOWN,
    WARNING,
    run_production_health,
)
from app.pipelines.publish_forecast import (
    create_configured_repository,
)


REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "production_health_delivery_report.json"
)

SNAPSHOT_DIRECTORY = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "production_health_snapshot"
)

HEALTH_ARTIFACT_TYPE = "production-health"

ACTIVE_INCIDENT_PATH = (
    "production-health/incidents/active.json"
)

INCIDENT_HISTORY_PREFIX = (
    "production-health/incidents/history"
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


class ProductionHealthPersistenceError(
    RuntimeError
):
    """Raised when durable health persistence fails."""


def utc_now() -> datetime:
    """Return current timezone-aware UTC time."""

    return datetime.now(
        timezone.utc
    )


def generate_health_run_id(
    now: datetime,
) -> str:
    """Generate one immutable health-run identifier."""

    timestamp = now.strftime(
        "%Y%m%dT%H%M%SZ"
    )

    suffix = uuid.uuid4().hex[:8]

    return (
        f"{timestamp}_production_health_"
        f"{suffix}"
    )


def write_json_atomically(
    *,
    path: Path,
    payload: dict[str, Any],
) -> None:
    """Write one local JSON file atomically."""

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = path.with_suffix(
        f"{path.suffix}.tmp"
    )

    temporary_path.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            default=str,
        ),
        encoding="utf-8",
    )

    temporary_path.replace(path)


def prepare_snapshot_directory(
    health_report: dict[str, Any],
) -> Path:
    """Create the source directory for immutable publication."""

    SNAPSHOT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    for existing_path in (
        SNAPSHOT_DIRECTORY.iterdir()
    ):
        if existing_path.is_file():
            existing_path.unlink()

    snapshot_path = (
        SNAPSHOT_DIRECTORY
        / "production_health_report.json"
    )

    write_json_atomically(
        path=snapshot_path,
        payload=health_report,
    )

    return SNAPSHOT_DIRECTORY


def normalize_component(
    *,
    category: str,
    name: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Normalize one unhealthy component."""

    return {
        "category": category,
        "name": name,
        "status": result.get(
            "status",
            UNKNOWN,
        ),
        "reason": result.get(
            "reason"
        ),
        "latest_timestamp_utc": (
            result.get(
                "latest_timestamp_utc"
            )
        ),
        "age_hours": result.get(
            "age_hours"
        ),
        "job_name": result.get(
            "job_name"
        ),
    }


def extract_unhealthy_components(
    health_report: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return warning, critical, and unknown components."""

    components: list[dict[str, Any]] = []

    for name, result in (
        health_report.get(
            "jobs",
            {}
        ).items()
    ):
        status = result.get(
            "status"
        )

        if status in {
            WARNING,
            CRITICAL,
            UNKNOWN,
        }:
            normalized = normalize_component(
                category="azure_job",
                name=name,
                result=result,
            )

            latest_execution = result.get(
                "latest_execution"
            )

            if isinstance(
                latest_execution,
                dict,
            ):
                normalized[
                    "latest_timestamp_utc"
                ] = (
                    latest_execution.get(
                        "end_time_utc"
                    )
                    or latest_execution.get(
                        "start_time_utc"
                    )
                )

                normalized[
                    "age_hours"
                ] = latest_execution.get(
                    "age_hours"
                )

            components.append(
                normalized
            )

    feature_store = health_report.get(
        "feature_store",
        {}
    )

    for name, result in (
        feature_store.get(
            "groups",
            {}
        ).items()
    ):
        if result.get(
            "status"
        ) in {
            WARNING,
            CRITICAL,
            UNKNOWN,
        }:
            components.append(
                normalize_component(
                    category=(
                        "hopsworks_feature_group"
                    ),
                    name=name,
                    result=result,
                )
            )

    artifact = health_report.get(
        "aqi_artifact",
        {}
    )

    if artifact.get(
        "status"
    ) in {
        WARNING,
        CRITICAL,
        UNKNOWN,
    }:
        components.append(
            normalize_component(
                category="aqi_artifact",
                name="aqi_latest_pointer",
                result=artifact,
            )
        )

    components.sort(
        key=lambda component: (
            str(
                component["category"]
            ),
            str(
                component["name"]
            ),
            str(
                component["status"]
            ),
        )
    )

    return components


def build_incident_fingerprint(
    components: list[dict[str, Any]],
) -> str | None:
    """Build a stable fingerprint for the active failure set."""

    if not components:
        return None

    fingerprint_payload = [
        {
            "category": component[
                "category"
            ],
            "name": component["name"],
            "status": component[
                "status"
            ],
        }
        for component in components
    ]

    serialized = json.dumps(
        fingerprint_payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(
        serialized
    ).hexdigest()


def load_active_incident(
    repository: ArtifactRepository,
) -> dict[str, Any] | None:
    """Load current active incident when present."""

    if not repository.exists(
        ACTIVE_INCIDENT_PATH
    ):
        return None

    incident = repository.download_json(
        ACTIVE_INCIDENT_PATH
    )

    if incident.get(
        "status"
    ) != "ACTIVE":
        return None

    return incident


def write_incident_history_event(
    *,
    repository: ArtifactRepository,
    event: dict[str, Any],
) -> str:
    """Write one immutable incident-history event."""

    event_id = str(
        event["event_id"]
    )

    destination_path = (
        f"{INCIDENT_HISTORY_PREFIX}/"
        f"{event_id}.json"
    )

    repository.upload_json(
        payload=event,
        destination_path=destination_path,
        overwrite=False,
    )

    return destination_path


def create_incident(
    *,
    repository: ArtifactRepository,
    components: list[dict[str, Any]],
    fingerprint: str,
    health_run_id: str,
    now: datetime,
) -> dict[str, Any]:
    """Create a new active incident."""

    incident_id = (
        f"{now.strftime('%Y%m%dT%H%M%SZ')}_"
        f"{fingerprint[:12]}"
    )

    event_id = (
        f"{now.strftime('%Y%m%dT%H%M%SZ')}_"
        f"opened_{uuid.uuid4().hex[:8]}"
    )

    incident = {
        "incident_id": incident_id,
        "status": "ACTIVE",
        "fingerprint": fingerprint,
        "opened_at_utc": (
            now.isoformat()
        ),
        "last_seen_at_utc": (
            now.isoformat()
        ),
        "last_health_run_id": (
            health_run_id
        ),
        "occurrence_count": 1,
        "components": components,
    }

    event = {
        "event_id": event_id,
        "event_type": (
            "INCIDENT_OPENED"
        ),
        "incident_id": incident_id,
        "occurred_at_utc": (
            now.isoformat()
        ),
        "health_run_id": (
            health_run_id
        ),
        "fingerprint": fingerprint,
        "components": components,
    }

    history_path = (
        write_incident_history_event(
            repository=repository,
            event=event,
        )
    )

    repository.upload_json(
        payload=incident,
        destination_path=(
            ACTIVE_INCIDENT_PATH
        ),
        overwrite=True,
    )

    return {
        "action": "INCIDENT_OPENED",
        "incident": incident,
        "history_path": history_path,
        "notification_required": True,
        "notification_type": (
            "INCIDENT_OPENED"
        ),
    }


def update_existing_incident(
    *,
    repository: ArtifactRepository,
    active_incident: dict[str, Any],
    components: list[dict[str, Any]],
    health_run_id: str,
    now: datetime,
) -> dict[str, Any]:
    """Update last-seen metadata without duplicate notification."""

    updated = {
        **active_incident,
        "last_seen_at_utc": (
            now.isoformat()
        ),
        "last_health_run_id": (
            health_run_id
        ),
        "occurrence_count": (
            int(
                active_incident.get(
                    "occurrence_count",
                    0,
                )
            )
            + 1
        ),
        "components": components,
    }

    repository.upload_json(
        payload=updated,
        destination_path=(
            ACTIVE_INCIDENT_PATH
        ),
        overwrite=True,
    )

    return {
        "action": (
            "INCIDENT_STILL_ACTIVE"
        ),
        "incident": updated,
        "history_path": None,
        "notification_required": False,
        "notification_type": None,
    }


def replace_changed_incident(
    *,
    repository: ArtifactRepository,
    active_incident: dict[str, Any],
    components: list[dict[str, Any]],
    fingerprint: str,
    health_run_id: str,
    now: datetime,
) -> dict[str, Any]:
    """Resolve the previous incident and open the changed incident."""

    resolution = resolve_incident(
        repository=repository,
        active_incident=(
            active_incident
        ),
        health_run_id=health_run_id,
        now=now,
        reason=(
            "Active unhealthy component set changed."
        ),
        notification_required=False,
    )

    opened = create_incident(
        repository=repository,
        components=components,
        fingerprint=fingerprint,
        health_run_id=health_run_id,
        now=now,
    )

    opened["previous_incident"] = (
        resolution["incident"]
    )

    opened["action"] = (
        "INCIDENT_CHANGED"
    )

    opened["notification_type"] = (
        "INCIDENT_CHANGED"
    )

    return opened


def resolve_incident(
    *,
    repository: ArtifactRepository,
    active_incident: dict[str, Any],
    health_run_id: str,
    now: datetime,
    reason: str,
    notification_required: bool = True,
) -> dict[str, Any]:
    """Resolve one active incident."""

    resolved_incident = {
        **active_incident,
        "status": "RESOLVED",
        "resolved_at_utc": (
            now.isoformat()
        ),
        "resolution_reason": reason,
        "last_health_run_id": (
            health_run_id
        ),
    }

    event_id = (
        f"{now.strftime('%Y%m%dT%H%M%SZ')}_"
        f"resolved_{uuid.uuid4().hex[:8]}"
    )

    event = {
        "event_id": event_id,
        "event_type": (
            "INCIDENT_RESOLVED"
        ),
        "incident_id": (
            resolved_incident[
                "incident_id"
            ]
        ),
        "occurred_at_utc": (
            now.isoformat()
        ),
        "health_run_id": (
            health_run_id
        ),
        "resolution_reason": reason,
        "incident": (
            resolved_incident
        ),
    }

    history_path = (
        write_incident_history_event(
            repository=repository,
            event=event,
        )
    )

    repository.upload_json(
        payload=resolved_incident,
        destination_path=(
            ACTIVE_INCIDENT_PATH
        ),
        overwrite=True,
    )

    return {
        "action": (
            "INCIDENT_RESOLVED"
        ),
        "incident": (
            resolved_incident
        ),
        "history_path": history_path,
        "notification_required": (
            notification_required
        ),
        "notification_type": (
            "INCIDENT_RESOLVED"
            if notification_required
            else None
        ),
    }


def evaluate_incident_state(
    *,
    repository: ArtifactRepository,
    health_report: dict[str, Any],
    health_run_id: str,
    now: datetime,
) -> dict[str, Any]:
    """Evaluate and persist deduplicated incident state."""

    components = (
        extract_unhealthy_components(
            health_report
        )
    )

    fingerprint = (
        build_incident_fingerprint(
            components
        )
    )

    active_incident = (
        load_active_incident(
            repository
        )
    )

    if not components:
        if active_incident is None:
            return {
                "action": (
                    "NO_ACTIVE_INCIDENT"
                ),
                "incident": None,
                "history_path": None,
                "notification_required": False,
                "notification_type": None,
                "fingerprint": None,
                "unhealthy_components": [],
            }

        result = resolve_incident(
            repository=repository,
            active_incident=(
                active_incident
            ),
            health_run_id=health_run_id,
            now=now,
            reason=(
                "All monitored production "
                "components recovered."
            ),
        )

        result["fingerprint"] = None
        result[
            "unhealthy_components"
        ] = []

        return result

    if fingerprint is None:
        raise (
            ProductionHealthPersistenceError(
                "Unhealthy components did not "
                "produce a fingerprint."
            )
        )

    if active_incident is None:
        result = create_incident(
            repository=repository,
            components=components,
            fingerprint=fingerprint,
            health_run_id=health_run_id,
            now=now,
        )

    elif (
        active_incident.get(
            "fingerprint"
        )
        == fingerprint
    ):
        result = update_existing_incident(
            repository=repository,
            active_incident=(
                active_incident
            ),
            components=components,
            health_run_id=health_run_id,
            now=now,
        )

    else:
        result = replace_changed_incident(
            repository=repository,
            active_incident=(
                active_incident
            ),
            components=components,
            fingerprint=fingerprint,
            health_run_id=health_run_id,
            now=now,
        )

    result["fingerprint"] = fingerprint
    result[
        "unhealthy_components"
    ] = components

    return result


def publish_health_snapshot(
    *,
    repository: ArtifactRepository,
    health_report: dict[str, Any],
    health_run_id: str,
) -> dict[str, Any]:
    """Publish one immutable production-health snapshot."""

    source_directory = (
        prepare_snapshot_directory(
            health_report
        )
    )

    publication = repository.publish_run(
        artifact_type=(
            HEALTH_ARTIFACT_TYPE
        ),
        run_id=health_run_id,
        source_directory=(
            source_directory
        ),
        validation_status=(
            "PRODUCTION_HEALTH_RECORDED"
        ),
        source_run_id=None,
    )

    pointer = repository.get_latest_pointer(
        HEALTH_ARTIFACT_TYPE
    )

    if (
        pointer.get("run_id")
        != health_run_id
    ):
        raise (
            ProductionHealthPersistenceError(
                "Latest health pointer does not "
                "reference the published run."
            )
        )

    return {
        "artifact_type": (
            HEALTH_ARTIFACT_TYPE
        ),
        "run_id": health_run_id,
        "artifact_prefix": (
            publication
            .latest_pointer
            .artifact_prefix
        ),
        "manifest_path": (
            publication
            .latest_pointer
            .manifest_path
        ),
        "published_at_utc": (
            publication
            .latest_pointer
            .published_at_utc
        ),
        "validation_status": (
            publication
            .latest_pointer
            .validation_status
        ),
        "file_count": len(
            publication.manifest.files
        ),
        "pointer_verified": True,
    }


def run_persisted_production_health(
    *,
    resource_group: str,
    feature_job_name: str,
    forecast_job_name: str,
    retraining_job_name: str,
) -> dict[str, Any]:
    """Run, persist, and evaluate production health."""

    started_at = utc_now()
    started_monotonic = (
        time.monotonic()
    )

    health_report = run_production_health(
        resource_group=resource_group,
        feature_job_name=feature_job_name,
        forecast_job_name=forecast_job_name,
        retraining_job_name=(
            retraining_job_name
        ),
    )

    health_run_id = (
        generate_health_run_id(
            started_at
        )
    )

    repository = (
        create_configured_repository()
    )

    publication = (
        publish_health_snapshot(
            repository=repository,
            health_report=health_report,
            health_run_id=health_run_id,
        )
    )

    incident = evaluate_incident_state(
        repository=repository,
        health_report=health_report,
        health_run_id=health_run_id,
        now=utc_now(),
    )

    completed_at = utc_now()

    return {
        "phase": "10L",
        "subphase": "10L-D1",
        "pipeline_name": (
            "persisted_production_health"
        ),
        "status": (
            "PRODUCTION_HEALTH_PERSISTED"
        ),
        "started_at_utc": (
            started_at.isoformat()
        ),
        "completed_at_utc": (
            completed_at.isoformat()
        ),
        "duration_seconds": round(
            time.monotonic()
            - started_monotonic,
            3,
        ),
        "health_run_id": (
            health_run_id
        ),
        "health_status": (
            health_report.get(
                "status"
            )
        ),
        "overall_component_status": (
            health_report.get(
                "overall_component_status"
            )
        ),
        "publication": publication,
        "incident_evaluation": (
            incident
        ),
        "external_notification_sent": (
            False
        ),
        "read_only_health_inspection": (
            True
        ),
        "production_data_changed": False,
        "production_model_changed": False,
        "azure_resources_changed": False,
        "aqi_artifact_pointer_changed": (
            False
        ),
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Atomically save the orchestration report."""

    write_json_atomically(
        path=REPORT_PATH,
        payload=report,
    )

    return REPORT_PATH


def main() -> int:
    """CLI entry point."""

    parser = argparse.ArgumentParser(
        description=(
            "Inspect production health, publish "
            "a durable snapshot, and maintain "
            "deduplicated incident state."
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
        report = (
            run_persisted_production_health(
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
        )

        # A warning or critical production state is an observed
        # condition, not an orchestration failure. The command fails
        # only when health collection or persistence itself fails.
        exit_code = 0

    except Exception as error:
        report = {
            "phase": "10L",
            "subphase": "10L-D1",
            "pipeline_name": (
                "persisted_production_health"
            ),
            "status": (
                "PRODUCTION_HEALTH_PERSISTENCE_FAILED"
            ),
            "failed_at_utc": (
                utc_now().isoformat()
            ),
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(error),
            "external_notification_sent": (
                False
            ),
            "production_data_changed": False,
            "production_model_changed": False,
            "azure_resources_changed": False,
            "aqi_artifact_pointer_changed": (
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