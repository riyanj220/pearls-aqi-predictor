"""Tests for dashboard forecast preparation and filtering."""

from __future__ import annotations

import pytest

from dashboard.utils.data import (
    DashboardDataError,
    filter_hourly_forecast,
    prepare_hourly_forecast,
)


def build_forecast_payload() -> dict:
    """Create a minimal valid forecast payload."""

    records = []

    for horizon in range(1, 73):
        records.append(
            {
                "target_time_utc": (
                    f"2026-07-28T"
                    f"{(horizon - 1) % 24:02d}:00:00Z"
                ),
                "forecast_horizon_hours": horizon,
                "predicted_pm25_ug_m3": 14.3,
                "indicative_hourly_pm25_aqi": 61,
                "indicative_hourly_aqi_category": (
                    "Moderate"
                ),
                "rolling_24h_pm25_ug_m3": 14.0,
                "rolling_24h_pm25_aqi": 60,
                "rolling_24h_aqi_category": (
                    "Moderate"
                ),
                "rolling_24h_pm25_is_complete": True,
                "alert_level": "NORMAL",
                "alert_is_active": False,
                "alert_trigger_category": "Moderate",
                "alert_trigger_aqi": 60,
                "health_message": (
                    "Air quality is acceptable."
                ),
                "recommended_action": (
                    "Continue normal activities."
                ),
            }
        )

    return {
        "hourly_forecast": records,
    }


def test_prepare_and_filter_forecast() -> None:
    """Valid payloads should become ordered filterable DataFrames."""

    dataframe = prepare_hourly_forecast(
        build_forecast_payload()
    )

    filtered = filter_hourly_forecast(
        dataframe,
        maximum_horizon=24,
    )

    assert len(dataframe) == 72
    assert len(filtered) == 24

    assert (
        dataframe[
            "forecast_horizon_hours"
        ].astype(int).tolist()
        == list(range(1, 73))
    )


def test_category_and_alert_filters() -> None:
    """Category and active-alert filters should work."""

    dataframe = prepare_hourly_forecast(
        build_forecast_payload()
    )

    moderate = filter_hourly_forecast(
        dataframe,
        maximum_horizon=72,
        categories=["Moderate"],
    )

    alerts_only = filter_hourly_forecast(
        dataframe,
        maximum_horizon=72,
        alerts_only=True,
    )

    assert len(moderate) == 72
    assert alerts_only.empty


def test_invalid_payload_is_rejected() -> None:
    """Missing hourly records should raise a clear data error."""

    with pytest.raises(
        DashboardDataError
    ):
        prepare_hourly_forecast(
            {
                "hourly_forecast": [],
            }
        )