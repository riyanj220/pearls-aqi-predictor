"""Dashboard-safe forecast preparation and filtering."""

from __future__ import annotations

from typing import Any

import pandas as pd

from dashboard.utils.constants import (
    ALERT_LEVELS,
    AQI_CATEGORIES,
)


class DashboardDataError(ValueError):
    """Raised when API data cannot be prepared safely."""


REQUIRED_HOURLY_FIELDS = {
    "target_time_utc",
    "forecast_horizon_hours",
    "predicted_pm25_ug_m3",
    "indicative_hourly_pm25_aqi",
    "indicative_hourly_aqi_category",
    "rolling_24h_pm25_ug_m3",
    "rolling_24h_pm25_aqi",
    "rolling_24h_aqi_category",
    "rolling_24h_pm25_is_complete",
    "alert_level",
    "alert_is_active",
    "health_message",
    "recommended_action",
}


def prepare_hourly_forecast(
    forecast_payload: dict[str, Any],
) -> pd.DataFrame:
    """Convert the complete forecast response into a validated DataFrame."""

    records = forecast_payload.get(
        "hourly_forecast"
    )

    if not isinstance(records, list):
        raise DashboardDataError(
            "Forecast response has no hourly forecast list."
        )

    if not records:
        raise DashboardDataError(
            "Forecast response contains no hourly records."
        )

    dataframe = pd.DataFrame(records)

    missing_columns = sorted(
        REQUIRED_HOURLY_FIELDS.difference(
            dataframe.columns
        )
    )

    if missing_columns:
        raise DashboardDataError(
            "Forecast records are missing fields: "
            f"{missing_columns}"
        )

    dataframe[
        "target_time_utc"
    ] = pd.to_datetime(
        dataframe["target_time_utc"],
        utc=True,
        errors="coerce",
    )

    numeric_columns = [
        "forecast_horizon_hours",
        "predicted_pm25_ug_m3",
        "indicative_hourly_pm25_aqi",
        "rolling_24h_pm25_ug_m3",
        "rolling_24h_pm25_aqi",
        "alert_trigger_aqi",
    ]

    for column in numeric_columns:
        if column in dataframe.columns:
            dataframe[column] = pd.to_numeric(
                dataframe[column],
                errors="coerce",
            )

    if dataframe[
        "target_time_utc"
    ].isna().any():
        raise DashboardDataError(
            "Forecast contains invalid target timestamps."
        )

    if dataframe[
        "forecast_horizon_hours"
    ].isna().any():
        raise DashboardDataError(
            "Forecast contains invalid horizons."
        )

    dataframe = (
        dataframe
        .sort_values(
            "forecast_horizon_hours"
        )
        .reset_index(drop=True)
    )

    horizons = dataframe[
        "forecast_horizon_hours"
    ].astype(int).tolist()

    if horizons != sorted(horizons):
        raise DashboardDataError(
            "Forecast horizons are not ordered."
        )

    unsupported_categories = set(
        dataframe[
            "indicative_hourly_aqi_category"
        ].dropna()
    ).difference(AQI_CATEGORIES)

    if unsupported_categories:
        raise DashboardDataError(
            "Unsupported AQI categories: "
            f"{sorted(unsupported_categories)}"
        )

    unsupported_levels = set(
        dataframe[
            "alert_level"
        ].dropna()
    ).difference(ALERT_LEVELS)

    if unsupported_levels:
        raise DashboardDataError(
            "Unsupported alert levels: "
            f"{sorted(unsupported_levels)}"
        )

    return dataframe


def filter_hourly_forecast(
    dataframe: pd.DataFrame,
    *,
    maximum_horizon: int,
    categories: list[str] | None = None,
    alert_levels: list[str] | None = None,
    alerts_only: bool = False,
) -> pd.DataFrame:
    """Apply dashboard-side display filters."""

    filtered = dataframe.loc[
        dataframe[
            "forecast_horizon_hours"
        ].le(maximum_horizon)
    ].copy()

    if categories:
        filtered = filtered.loc[
            filtered[
                "alert_trigger_category"
            ].isin(categories)
        ]

    if alert_levels:
        filtered = filtered.loc[
            filtered[
                "alert_level"
            ].isin(alert_levels)
        ]

    if alerts_only:
        filtered = filtered.loc[
            filtered[
                "alert_is_active"
            ].astype(bool)
        ]

    return filtered.reset_index(
        drop=True
    )


def add_display_timezone(
    dataframe: pd.DataFrame,
    *,
    timezone_name: str,
) -> pd.DataFrame:
    """Add a timezone-converted timestamp column."""

    converted = dataframe.copy()

    converted[
        "display_time"
    ] = converted[
        "target_time_utc"
    ].dt.tz_convert(
        timezone_name
    )

    return converted