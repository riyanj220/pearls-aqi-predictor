"""Tests for durable health incident management."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.artifacts.repository import (
    LocalArtifactRepository,
)
from app.operations.persist_production_health import (
    ACTIVE_INCIDENT_PATH,
    build_incident_fingerprint,
    evaluate_incident_state,
    extract_unhealthy_components,
)


NOW = datetime(
    2026,
    8,
    6,
    12,
    0,
    tzinfo=timezone.utc,
)


def build_health_report(
    *,
    job_status: str = "HEALTHY",
) -> dict:
    """Build a minimal production-health report."""

    return {
        "jobs": {
            "hourly_feature_job": {
                "status": job_status,
                "job_name": (
                    "job-pearls-aqi-features"
                ),
                "reason": "Test condition.",
                "latest_execution": {
                    "end_time_utc": (
                        "2026-08-06T11:00:00+00:00"
                    ),
                    "age_hours": 1,
                },
            },
        },
        "feature_store": {
            "groups": {
                "pm25": {
                    "status": "HEALTHY",
                },
                "weather": {
                    "status": "HEALTHY",
                },
                "engineered": {
                    "status": "HEALTHY",
                },
            },
        },
        "aqi_artifact": {
            "status": "HEALTHY",
        },
    }


def test_healthy_state_creates_no_incident(
    tmp_path: Path,
) -> None:
    """Healthy production should not create an incident."""

    repository = (
        LocalArtifactRepository(
            tmp_path
        )
    )

    result = evaluate_incident_state(
        repository=repository,
        health_report=(
            build_health_report()
        ),
        health_run_id="health-run-1",
        now=NOW,
    )

    assert (
        result["action"]
        == "NO_ACTIVE_INCIDENT"
    )

    assert (
        result["notification_required"]
        is False
    )

    assert not repository.exists(
        ACTIVE_INCIDENT_PATH
    )


def test_first_failure_opens_incident(
    tmp_path: Path,
) -> None:
    """First unhealthy result should open and notify."""

    repository = (
        LocalArtifactRepository(
            tmp_path
        )
    )

    result = evaluate_incident_state(
        repository=repository,
        health_report=(
            build_health_report(
                job_status="CRITICAL",
            )
        ),
        health_run_id="health-run-1",
        now=NOW,
    )

    assert (
        result["action"]
        == "INCIDENT_OPENED"
    )

    assert (
        result["notification_required"]
        is True
    )

    assert repository.exists(
        ACTIVE_INCIDENT_PATH
    )


def test_repeated_failure_is_deduplicated(
    tmp_path: Path,
) -> None:
    """Identical consecutive failures should not re-notify."""

    repository = (
        LocalArtifactRepository(
            tmp_path
        )
    )

    report = build_health_report(
        job_status="CRITICAL",
    )

    evaluate_incident_state(
        repository=repository,
        health_report=report,
        health_run_id="health-run-1",
        now=NOW,
    )

    result = evaluate_incident_state(
        repository=repository,
        health_report=report,
        health_run_id="health-run-2",
        now=NOW,
    )

    assert (
        result["action"]
        == "INCIDENT_STILL_ACTIVE"
    )

    assert (
        result["notification_required"]
        is False
    )

    assert (
        result["incident"][
            "occurrence_count"
        ]
        == 2
    )


def test_recovery_resolves_and_notifies(
    tmp_path: Path,
) -> None:
    """A healthy result after failure should resolve once."""

    repository = (
        LocalArtifactRepository(
            tmp_path
        )
    )

    evaluate_incident_state(
        repository=repository,
        health_report=(
            build_health_report(
                job_status="CRITICAL",
            )
        ),
        health_run_id="health-run-1",
        now=NOW,
    )

    result = evaluate_incident_state(
        repository=repository,
        health_report=(
            build_health_report()
        ),
        health_run_id="health-run-2",
        now=NOW,
    )

    assert (
        result["action"]
        == "INCIDENT_RESOLVED"
    )

    assert (
        result["notification_required"]
        is True
    )

    assert (
        result["incident"]["status"]
        == "RESOLVED"
    )


def test_fingerprint_is_stable() -> None:
    """Equivalent component sets should share a fingerprint."""

    report = build_health_report(
        job_status="WARNING",
    )

    components = (
        extract_unhealthy_components(
            report
        )
    )

    first = build_incident_fingerprint(
        components
    )

    second = build_incident_fingerprint(
        list(reversed(components))
    )

    assert first is not None
    assert first == second