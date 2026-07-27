"""AQI enrichment for hourly PM2.5 forecasts."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.aqi.pm25_aqi import (
    PM25AQIConversionError,
    convert_pm25_series_to_aqi,
)


class AQIForecastEnrichmentError(ValueError):
    """Raised when a forecast cannot be enriched safely."""


def _normalize_pm25_timeline(
    observed_pm25_df: pd.DataFrame,
    forecast_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Combine observed and predicted PM2.5 into one hourly timeline.

    Observed values end at the reference timestamp. Predicted values
    begin at the first forecast target timestamp.
    """

    required_observed_columns = {
        "datetime_utc",
        "pm25_ug_m3",
    }

    required_forecast_columns = {
        "target_time",
        "predicted_pm25_ug_m3",
    }

    missing_observed_columns = sorted(
        required_observed_columns.difference(
            observed_pm25_df.columns
        )
    )

    missing_forecast_columns = sorted(
        required_forecast_columns.difference(
            forecast_df.columns
        )
    )

    if missing_observed_columns:
        raise AQIForecastEnrichmentError(
            "Observed PM2.5 data is missing columns: "
            f"{missing_observed_columns}"
        )

    if missing_forecast_columns:
        raise AQIForecastEnrichmentError(
            "Forecast data is missing columns: "
            f"{missing_forecast_columns}"
        )

    observed_timeline_df = (
        observed_pm25_df[
            [
                "datetime_utc",
                "pm25_ug_m3",
            ]
        ]
        .rename(
            columns={
                "datetime_utc": "timestamp_utc",
            }
        )
        .assign(pm25_source="observed")
    )

    predicted_timeline_df = (
        forecast_df[
            [
                "target_time",
                "predicted_pm25_ug_m3",
            ]
        ]
        .rename(
            columns={
                "target_time": "timestamp_utc",
                "predicted_pm25_ug_m3": "pm25_ug_m3",
            }
        )
        .assign(pm25_source="predicted")
    )

    combined_timeline_df = pd.concat(
        [
            observed_timeline_df,
            predicted_timeline_df,
        ],
        ignore_index=True,
    )

    combined_timeline_df["timestamp_utc"] = pd.to_datetime(
        combined_timeline_df["timestamp_utc"],
        utc=True,
        errors="coerce",
    )

    combined_timeline_df["pm25_ug_m3"] = pd.to_numeric(
        combined_timeline_df["pm25_ug_m3"],
        errors="coerce",
    )

    if combined_timeline_df["timestamp_utc"].isna().any():
        raise AQIForecastEnrichmentError(
            "Combined PM2.5 timeline contains invalid timestamps."
        )

    if combined_timeline_df["pm25_ug_m3"].isna().any():
        raise AQIForecastEnrichmentError(
            "Combined PM2.5 timeline contains missing values."
        )

    pm25_values = combined_timeline_df[
        "pm25_ug_m3"
    ].to_numpy(dtype=float)

    if not np.isfinite(pm25_values).all():
        raise AQIForecastEnrichmentError(
            "Combined PM2.5 timeline contains infinite values."
        )

    if combined_timeline_df["pm25_ug_m3"].lt(0).any():
        raise AQIForecastEnrichmentError(
            "Combined PM2.5 timeline contains negative values."
        )

    combined_timeline_df = (
        combined_timeline_df
        .sort_values("timestamp_utc")
        .drop_duplicates(
            subset=["timestamp_utc"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    if combined_timeline_df[
        "timestamp_utc"
    ].duplicated().any():
        raise AQIForecastEnrichmentError(
            "Duplicate timestamps remain in the PM2.5 timeline."
        )

    return combined_timeline_df


def _calculate_rolling_24h_metrics(
    *,
    target_times: pd.Series,
    combined_timeline_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Calculate exact trailing 24-hour PM2.5 windows.

    Each window covers target_time - 23 hours through target_time.
    Incomplete windows remain unavailable rather than being filled.
    """

    indexed_timeline_df = (
        combined_timeline_df
        .set_index("timestamp_utc")
        .sort_index()
    )

    rolling_records: list[dict[str, object]] = []

    for target_time in target_times:
        normalized_target_time = pd.Timestamp(
            target_time
        )

        required_window = pd.date_range(
            end=normalized_target_time,
            periods=24,
            freq="h",
            tz="UTC",
        )

        window_df = indexed_timeline_df.reindex(
            required_window
        )

        missing_timestamp_count = int(
            window_df["pm25_ug_m3"].isna().sum()
        )

        window_complete = (
            missing_timestamp_count == 0
        )

        if window_complete:
            rolling_pm25_mean = float(
                window_df["pm25_ug_m3"].mean()
            )

            observed_hour_count = int(
                window_df["pm25_source"]
                .eq("observed")
                .sum()
            )

            predicted_hour_count = int(
                window_df["pm25_source"]
                .eq("predicted")
                .sum()
            )
        else:
            rolling_pm25_mean = np.nan

            observed_hour_count = int(
                window_df["pm25_source"]
                .eq("observed")
                .sum()
            )

            predicted_hour_count = int(
                window_df["pm25_source"]
                .eq("predicted")
                .sum()
            )

        rolling_records.append(
            {
                "target_time": normalized_target_time,
                "rolling_24h_pm25_ug_m3": (
                    rolling_pm25_mean
                ),
                "rolling_24h_pm25_is_complete": (
                    window_complete
                ),
                "rolling_24h_required_hours": 24,
                "rolling_24h_missing_hours": (
                    missing_timestamp_count
                ),
                "rolling_observed_hour_count": (
                    observed_hour_count
                ),
                "rolling_predicted_hour_count": (
                    predicted_hour_count
                ),
            }
        )

    return pd.DataFrame(rolling_records)


def enrich_forecast_with_aqi(
    forecast_df: pd.DataFrame,
    observed_pm25_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Add indicative hourly and rolling 24-hour AQI to a forecast.

    The original forecast columns and row order are preserved.
    """

    required_forecast_columns = {
        "target_time",
        "forecast_horizon_hours",
        "predicted_pm25_ug_m3",
    }

    missing_forecast_columns = sorted(
        required_forecast_columns.difference(
            forecast_df.columns
        )
    )

    if missing_forecast_columns:
        raise AQIForecastEnrichmentError(
            "Forecast is missing required columns: "
            f"{missing_forecast_columns}"
        )

    enriched_df = forecast_df.copy()

    enriched_df["target_time"] = pd.to_datetime(
        enriched_df["target_time"],
        utc=True,
        errors="coerce",
    )

    if enriched_df["target_time"].isna().any():
        raise AQIForecastEnrichmentError(
            "Forecast contains invalid target timestamps."
        )

    enriched_df = (
        enriched_df
        .sort_values("forecast_horizon_hours")
        .reset_index(drop=True)
    )

    try:
        hourly_aqi_df = convert_pm25_series_to_aqi(
            enriched_df["predicted_pm25_ug_m3"]
        )
    except PM25AQIConversionError as exc:
        raise AQIForecastEnrichmentError(
            "Indicative hourly AQI conversion failed."
        ) from exc

    hourly_aqi_df = hourly_aqi_df.rename(
        columns={
            "pm25_ug_m3_truncated": (
                "predicted_pm25_ug_m3_truncated"
            ),
            "aqi": "indicative_hourly_pm25_aqi",
            "aqi_category": (
                "indicative_hourly_aqi_category"
            ),
            "aqi_color_name": (
                "indicative_hourly_aqi_color_name"
            ),
            "aqi_color_hex": (
                "indicative_hourly_aqi_color_hex"
            ),
            "aqi_severity_rank": (
                "indicative_hourly_aqi_severity_rank"
            ),
            "is_beyond_aqi": (
                "indicative_hourly_is_beyond_aqi"
            ),
        }
    )

    hourly_columns_to_add = [
        "predicted_pm25_ug_m3_truncated",
        "indicative_hourly_pm25_aqi",
        "indicative_hourly_aqi_category",
        "indicative_hourly_aqi_color_name",
        "indicative_hourly_aqi_color_hex",
        "indicative_hourly_aqi_severity_rank",
        "indicative_hourly_is_beyond_aqi",
    ]

    enriched_df = pd.concat(
        [
            enriched_df.reset_index(drop=True),
            hourly_aqi_df[
                hourly_columns_to_add
            ].reset_index(drop=True),
        ],
        axis=1,
    )

    combined_timeline_df = _normalize_pm25_timeline(
        observed_pm25_df=observed_pm25_df,
        forecast_df=enriched_df,
    )

    rolling_metrics_df = _calculate_rolling_24h_metrics(
        target_times=enriched_df["target_time"],
        combined_timeline_df=combined_timeline_df,
    )

    try:
        rolling_aqi_df = convert_pm25_series_to_aqi(
            rolling_metrics_df[
                "rolling_24h_pm25_ug_m3"
            ]
        )
    except PM25AQIConversionError as exc:
        raise AQIForecastEnrichmentError(
            "Rolling 24-hour AQI conversion failed."
        ) from exc

    rolling_aqi_df = rolling_aqi_df.rename(
        columns={
            "pm25_ug_m3_truncated": (
                "rolling_24h_pm25_ug_m3_truncated"
            ),
            "aqi": "rolling_24h_pm25_aqi",
            "aqi_category": (
                "rolling_24h_aqi_category"
            ),
            "aqi_color_name": (
                "rolling_24h_aqi_color_name"
            ),
            "aqi_color_hex": (
                "rolling_24h_aqi_color_hex"
            ),
            "aqi_severity_rank": (
                "rolling_24h_aqi_severity_rank"
            ),
            "is_beyond_aqi": (
                "rolling_24h_is_beyond_aqi"
            ),
        }
    )

    rolling_aqi_columns = [
        "rolling_24h_pm25_ug_m3_truncated",
        "rolling_24h_pm25_aqi",
        "rolling_24h_aqi_category",
        "rolling_24h_aqi_color_name",
        "rolling_24h_aqi_color_hex",
        "rolling_24h_aqi_severity_rank",
        "rolling_24h_is_beyond_aqi",
    ]

    rolling_result_df = pd.concat(
        [
            rolling_metrics_df.reset_index(drop=True),
            rolling_aqi_df[
                rolling_aqi_columns
            ].reset_index(drop=True),
        ],
        axis=1,
    )

    enriched_df = enriched_df.merge(
        rolling_result_df,
        on="target_time",
        how="left",
        validate="one_to_one",
    )

    return enriched_df