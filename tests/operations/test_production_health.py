"""Tests for production health classification rules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.operations.production_health import (
    CRITICAL,
    HEALTHY,
    UNKNOWN,
    WARNING,
    FreshnessThreshold,
    build_freshness_result,
    classify_age,
    map_overall_report_status,
    worst_status,
)


NOW = datetime(
    2026,
    8,
    6,
    12,
    0,
    tzinfo=timezone.utc,
)

THRESHOLD = FreshnessThreshold(
    warning_after_hours=3,
    critical_after_hours=6,
)


@pytest.mark.parametrize(
    (
        "age_hours",
        "expected_status",
    ),
    [
        (0.0, HEALTHY),
        (3.0, HEALTHY),
        (3.001, WARNING),
        (6.0, WARNING),
        (6.001, CRITICAL),
        (None, UNKNOWN),
    ],
)
def test_classify_age(
    age_hours: float | None,
    expected_status: str,
) -> None:
    """Age boundaries should follow the configured rules."""

    assert (
        classify_age(
            age_hours=age_hours,
            threshold=THRESHOLD,
        )
        == expected_status
    )


def test_build_freshness_result() -> None:
    """Freshness output should contain age and thresholds."""

    result = build_freshness_result(
        latest_timestamp=(
            NOW - timedelta(hours=4)
        ),
        threshold=THRESHOLD,
        now=NOW,
    )

    assert result["status"] == WARNING
    assert result["age_hours"] == 4.0

    assert result["thresholds"] == {
        "warning_after_hours": 3,
        "critical_after_hours": 6,
    }


@pytest.mark.parametrize(
    (
        "statuses",
        "expected_status",
    ),
    [
        (
            [HEALTHY, HEALTHY],
            HEALTHY,
        ),
        (
            [HEALTHY, UNKNOWN],
            UNKNOWN,
        ),
        (
            [UNKNOWN, WARNING],
            WARNING,
        ),
        (
            [HEALTHY, WARNING],
            WARNING,
        ),
        (
            [HEALTHY, CRITICAL],
            CRITICAL,
        ),
        (
            [
                UNKNOWN,
                WARNING,
                CRITICAL,
            ],
            CRITICAL,
        ),
        (
            [],
            UNKNOWN,
        ),
    ],
)
def test_worst_status(
    statuses: list[str],
    expected_status: str,
) -> None:
    """The most severe component should determine health."""

    assert (
        worst_status(statuses)
        == expected_status
    )


@pytest.mark.parametrize(
    (
        "component_status",
        "expected_report_status",
    ),
    [
        (
            HEALTHY,
            "PRODUCTION_HEALTHY",
        ),
        (
            WARNING,
            "PRODUCTION_HEALTH_WARNING",
        ),
        (
            CRITICAL,
            "PRODUCTION_HEALTH_CRITICAL",
        ),
        (
            UNKNOWN,
            "PRODUCTION_HEALTH_UNKNOWN",
        ),
    ],
)
def test_map_overall_report_status(
    component_status: str,
    expected_report_status: str,
) -> None:
    """Internal severity should map to public report status."""

    assert (
        map_overall_report_status(
            component_status
        )
        == expected_report_status
    )


def test_threshold_rejects_negative_warning() -> None:
    """Negative warning thresholds are invalid."""

    with pytest.raises(
        ValueError,
        match="cannot be negative",
    ):
        FreshnessThreshold(
            warning_after_hours=-1,
            critical_after_hours=6,
        )


def test_threshold_requires_larger_critical_value() -> None:
    """Critical age must be greater than warning age."""

    with pytest.raises(
        ValueError,
        match="must be greater",
    ):
        FreshnessThreshold(
            warning_after_hours=6,
            critical_after_hours=6,
        )


def test_future_timestamp_has_zero_age() -> None:
    """Clock skew must not produce a negative age."""

    result = build_freshness_result(
        latest_timestamp=(
            NOW + timedelta(minutes=10)
        ),
        threshold=THRESHOLD,
        now=NOW,
    )

    assert result["age_hours"] == 0.0
    assert result["status"] == HEALTHY