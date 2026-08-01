"""Focused integration tests for the FastAPI service."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.config import get_api_settings
from app.api.main import create_application
from app.core.config import PROJECT_ROOT


TEST_ARTIFACT_DIRECTORY = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "aqi"
    / "latest"
)


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """
    Create an API client using deterministic Phase 6 test artifacts.

    Large freshness thresholds prevent the committed test fixture from
    becoming stale over time.
    """

    required_fixture_files = [
        "live_pm25_aqi_forecast.parquet",
        "alert_episodes.json",
        "aqi_forecast_summary.json",
        "aqi_metadata.json",
        "phase_6_validation_report.json",
    ]

    missing_fixture_files = [
        filename
        for filename in required_fixture_files
        if not (
            TEST_ARTIFACT_DIRECTORY
            / filename
        ).exists()
    ]

    if missing_fixture_files:
        pytest.fail(
            "Required API test artifacts are missing: "
            + ", ".join(missing_fixture_files)
        )

    monkeypatch.setenv(
        "PEARLS_API_PHASE_6_LATEST_DIRECTORY",
        str(TEST_ARTIFACT_DIRECTORY),
    )

    monkeypatch.setenv(
        "PEARLS_API_ARTIFACT_CACHE_SECONDS",
        "0",
    )

    monkeypatch.setenv(
        "PEARLS_API_FORECAST_AGING_THRESHOLD_HOURS",
        "999998",
    )

    monkeypatch.setenv(
        "PEARLS_API_FORECAST_STALENESS_THRESHOLD_HOURS",
        "999999",
    )

    get_api_settings.cache_clear()

    application = create_application()

    with TestClient(application) as test_client:
        yield test_client

    get_api_settings.cache_clear()


def test_health_and_complete_forecast(
    client: TestClient,
) -> None:
    """Liveness, readiness, and the complete forecast should work."""

    live_response = client.get(
        "/api/v1/health/live"
    )

    ready_response = client.get(
        "/api/v1/health/ready"
    )

    forecast_response = client.get(
        "/api/v1/forecast"
    )

    assert live_response.status_code == 200
    assert ready_response.status_code == 200
    assert forecast_response.status_code == 200

    payload = forecast_response.json()
    records = payload["hourly_forecast"]

    assert len(records) == 72

    assert [
        record["forecast_horizon_hours"]
        for record in records
    ] == list(range(1, 73))

    assert payload["pipeline_run_id"]
    assert "artifact_path" not in str(payload)
    assert "traceback" not in str(payload).lower()


def test_hourly_filters_and_alerts(
    client: TestClient,
) -> None:
    """Essential forecast and alert filters should work."""

    hourly_response = client.get(
        "/api/v1/forecast/hourly",
        params={
            "minimum_horizon": 1,
            "maximum_horizon": 24,
        },
    )

    alerts_only_response = client.get(
        "/api/v1/forecast/hourly",
        params={
            "alerts_only": True,
        },
    )

    alerts_response = client.get(
        "/api/v1/alerts"
    )

    assert hourly_response.status_code == 200
    assert hourly_response.json()["result_count"] == 24

    assert alerts_only_response.status_code == 200
    assert (
        alerts_only_response.json()["result_count"]
        == 0
    )

    assert alerts_response.status_code == 200
    assert alerts_response.json()["episodes"] == []


def test_structured_errors(
    client: TestClient,
) -> None:
    """Invalid requests should use the standard error response."""

    invalid_range_response = client.get(
        "/api/v1/forecast/hourly",
        params={
            "minimum_horizon": 30,
            "maximum_horizon": 10,
        },
        headers={
            "X-Request-ID": "api-test-request"
        },
    )

    invalid_enum_response = client.get(
        "/api/v1/forecast/hourly",
        params={
            "alert_level": "CRITICAL",
        },
    )

    missing_route_response = client.get(
        "/api/v1/not-found"
    )

    assert invalid_range_response.status_code == 400
    assert (
        invalid_range_response.json()["error"]["code"]
        == "INVALID_QUERY_PARAMETER"
    )
    assert (
        invalid_range_response.json()["error"][
            "request_id"
        ]
        == "api-test-request"
    )

    assert invalid_enum_response.status_code == 422
    assert (
        invalid_enum_response.json()["error"]["code"]
        == "INVALID_QUERY_PARAMETER"
    )

    assert missing_route_response.status_code == 404
    assert (
        missing_route_response.json()["error"]["code"]
        == "RESOURCE_NOT_FOUND"
    )

    assert "traceback" not in str(
        missing_route_response.json()
    ).lower()


def test_missing_artifacts_report_not_ready(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    The API process should remain alive when artifacts are missing.

    Readiness must return 503.
    """

    empty_artifact_directory = (
        tmp_path / "missing-artifacts"
    )

    empty_artifact_directory.mkdir()

    monkeypatch.setenv(
        "PEARLS_API_PHASE_6_LATEST_DIRECTORY",
        str(empty_artifact_directory),
    )

    get_api_settings.cache_clear()

    application = create_application()

    with TestClient(application) as test_client:
        live_response = test_client.get(
            "/api/v1/health/live"
        )

        ready_response = test_client.get(
            "/api/v1/health/ready"
        )

        forecast_response = test_client.get(
            "/api/v1/forecast"
        )

    get_api_settings.cache_clear()

    assert live_response.status_code == 200
    assert ready_response.status_code == 503

    assert ready_response.json()["status"] in {
        "NOT_READY",
        "INVALID_ARTIFACTS",
    }

    assert forecast_response.status_code == 503
    assert (
        forecast_response.json()["error"]["code"]
        == "FORECAST_NOT_FOUND"
    )