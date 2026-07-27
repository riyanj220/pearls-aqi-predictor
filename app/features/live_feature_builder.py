"""Reusable feature engineering for PM2.5 model inference."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


class FeatureBuildError(ValueError):
    """Raised when model features cannot be built safely."""


PM25_LAG_HOURS = (1, 3, 6, 12, 24)
PM25_ROLLING_WINDOWS = (3, 6, 12, 24)
PM25_CHANGE_HOURS = (1, 6, 24)

WEATHER_COLUMNS = (
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "surface_pressure",
    "precipitation",
    "rain",
    "cloud_cover",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
)


def validate_hourly_timeline(
    dataframe: pd.DataFrame,
    *,
    timestamp_column: str,
) -> pd.DataFrame:
    """
    Validate and return a chronologically sorted UTC hourly timeline.

    The function does not interpolate or create missing timestamps.
    """

    if timestamp_column not in dataframe.columns:
        raise FeatureBuildError(
            f"Timestamp column is missing: {timestamp_column}"
        )

    validated_df = dataframe.copy()

    validated_df[timestamp_column] = pd.to_datetime(
        validated_df[timestamp_column],
        utc=True,
        errors="coerce",
    )

    if validated_df[timestamp_column].isna().any():
        invalid_count = int(
            validated_df[timestamp_column].isna().sum()
        )

        raise FeatureBuildError(
            f"Found {invalid_count} invalid timestamps."
        )

    duplicate_count = int(
        validated_df[timestamp_column].duplicated().sum()
    )

    if duplicate_count > 0:
        raise FeatureBuildError(
            f"Found {duplicate_count} duplicate timestamps."
        )

    validated_df = (
        validated_df
        .sort_values(timestamp_column)
        .reset_index(drop=True)
    )

    return validated_df


def add_pm25_history_features(
    dataframe: pd.DataFrame,
    *,
    pm25_column: str = "pm25_ug_m3",
) -> pd.DataFrame:
    """
    Create PM2.5 current, lag, rolling-mean, and change features.

    Rolling windows include the reference hour and require a complete
    window. Missing PM2.5 values are not interpolated.
    """

    if pm25_column not in dataframe.columns:
        raise FeatureBuildError(
            f"PM2.5 column is missing: {pm25_column}"
        )

    feature_df = dataframe.copy()

    feature_df["pm25_current"] = feature_df[pm25_column]

    for lag_hour in PM25_LAG_HOURS:
        feature_df[f"pm25_lag_{lag_hour}h"] = (
            feature_df[pm25_column].shift(lag_hour)
        )

    for window_hour in PM25_ROLLING_WINDOWS:
        feature_df[f"pm25_mean_{window_hour}h"] = (
            feature_df[pm25_column]
            .rolling(
                window=window_hour,
                min_periods=window_hour,
            )
            .mean()
        )

    for change_hour in PM25_CHANGE_HOURS:
        feature_df[f"pm25_change_{change_hour}h"] = (
            feature_df[pm25_column]
            - feature_df[pm25_column].shift(change_hour)
        )

    return feature_df


def add_wind_direction_features(
    dataframe: pd.DataFrame,
    *,
    source_column: str,
    output_prefix: str,
) -> pd.DataFrame:
    """Encode wind direction in degrees using sine and cosine."""

    if source_column not in dataframe.columns:
        raise FeatureBuildError(
            f"Wind-direction column is missing: {source_column}"
        )

    feature_df = dataframe.copy()

    radians = np.deg2rad(
        feature_df[source_column].astype(float)
    )

    feature_df[f"{output_prefix}_sin"] = np.sin(radians)
    feature_df[f"{output_prefix}_cos"] = np.cos(radians)

    return feature_df


def add_time_features(
    dataframe: pd.DataFrame,
    *,
    timestamp_column: str,
    prefix: str,
) -> pd.DataFrame:
    """
    Create hour, weekday, month, and cyclical time features.

    Weekday follows pandas convention:
    Monday=0 through Sunday=6.
    """

    if timestamp_column not in dataframe.columns:
        raise FeatureBuildError(
            f"Timestamp column is missing: {timestamp_column}"
        )

    feature_df = dataframe.copy()

    timestamp_series = pd.to_datetime(
        feature_df[timestamp_column],
        utc=True,
        errors="coerce",
    )

    if timestamp_series.isna().any():
        raise FeatureBuildError(
            f"Invalid timestamps found in {timestamp_column}."
        )

    hour = timestamp_series.dt.hour
    day_of_week = timestamp_series.dt.dayofweek
    month = timestamp_series.dt.month
    month_zero_based = month - 1

    feature_df[f"{prefix}_hour"] = hour
    feature_df[f"{prefix}_day_of_week"] = day_of_week
    feature_df[f"{prefix}_month"] = month

    feature_df[f"{prefix}_hour_sin"] = np.sin(
        2 * np.pi * hour / 24
    )
    feature_df[f"{prefix}_hour_cos"] = np.cos(
        2 * np.pi * hour / 24
    )

    feature_df[f"{prefix}_day_of_week_sin"] = np.sin(
        2 * np.pi * day_of_week / 7
    )
    feature_df[f"{prefix}_day_of_week_cos"] = np.cos(
        2 * np.pi * day_of_week / 7
    )

    feature_df[f"{prefix}_month_sin"] = np.sin(
        2 * np.pi * month_zero_based / 12
    )

    feature_df[f"{prefix}_month_cos"] = np.cos(
        2 * np.pi * month_zero_based / 12
    )

    return feature_df


def build_reference_feature_table(
    canonical_hourly_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build PM2.5, current-weather, and reference-time features.

    One output row represents one possible reference timestamp.
    """

    required_columns = {
        "datetime_utc",
        "pm25_ug_m3",
        *WEATHER_COLUMNS,
    }

    missing_columns = sorted(
        required_columns.difference(
            canonical_hourly_df.columns
        )
    )

    if missing_columns:
        raise FeatureBuildError(
            "Canonical dataset is missing required columns: "
            f"{missing_columns}"
        )

    feature_df = validate_hourly_timeline(
        canonical_hourly_df,
        timestamp_column="datetime_utc",
    )

    feature_df = add_pm25_history_features(
        feature_df,
        pm25_column="pm25_ug_m3",
    )

    feature_df = add_wind_direction_features(
        feature_df,
        source_column="wind_direction_10m",
        output_prefix="wind_direction_10m",
    )

    feature_df = feature_df.rename(
        columns={"datetime_utc": "reference_time"}
    )

    feature_df = add_time_features(
        feature_df,
        timestamp_column="reference_time",
        prefix="reference",
    )

    return feature_df


def build_target_weather_feature_table(
    canonical_hourly_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build target-hour weather and target-time features.

    During live inference this table will be built from forecast weather.
    """

    required_columns = {
        "datetime_utc",
        *WEATHER_COLUMNS,
    }

    missing_columns = sorted(
        required_columns.difference(
            canonical_hourly_df.columns
        )
    )

    if missing_columns:
        raise FeatureBuildError(
            "Weather dataset is missing required columns: "
            f"{missing_columns}"
        )

    target_df = validate_hourly_timeline(
        canonical_hourly_df[
            [
                "datetime_utc",
                *WEATHER_COLUMNS,
            ]
        ],
        timestamp_column="datetime_utc",
    )

    target_df = target_df.rename(
        columns={"datetime_utc": "target_time"}
    )

    target_df = target_df.rename(
        columns={
            column: f"target_{column}"
            for column in WEATHER_COLUMNS
        }
    )

    target_df = add_wind_direction_features(
        target_df,
        source_column="target_wind_direction_10m",
        output_prefix="target_wind_direction_10m",
    )

    target_df = add_time_features(
        target_df,
        timestamp_column="target_time",
        prefix="target",
    )

    return target_df


def build_feature_rows(
    *,
    reference_feature_df: pd.DataFrame,
    target_weather_feature_df: pd.DataFrame,
    reference_times: Sequence[pd.Timestamp],
    forecast_horizons: Sequence[int],
    model_feature_columns: Sequence[str],
) -> pd.DataFrame:
    """
    Build model feature rows for supplied references and horizons.

    This function is shared by parity checks and future live inference.
    """

    reference_input_df = pd.DataFrame(
        {
            "reference_time": pd.to_datetime(
                list(reference_times),
                utc=True,
            )
        }
    )

    horizon_input_df = pd.DataFrame(
        {
            "forecast_horizon_hours": list(
                forecast_horizons
            )
        }
    )

    if reference_input_df.empty:
        raise FeatureBuildError(
            "At least one reference timestamp is required."
        )

    if horizon_input_df.empty:
        raise FeatureBuildError(
            "At least one forecast horizon is required."
        )

    if (
        horizon_input_df["forecast_horizon_hours"] <= 0
    ).any():
        raise FeatureBuildError(
            "Forecast horizons must be positive integers."
        )

    expanded_df = reference_input_df.merge(
        horizon_input_df,
        how="cross",
    )

    expanded_df["target_time"] = (
        expanded_df["reference_time"]
        + pd.to_timedelta(
            expanded_df["forecast_horizon_hours"],
            unit="h",
        )
    )

    expanded_df = expanded_df.merge(
        reference_feature_df,
        on="reference_time",
        how="left",
        validate="many_to_one",
    )

    expanded_df = expanded_df.merge(
        target_weather_feature_df,
        on="target_time",
        how="left",
        validate="many_to_one",
    )

    missing_model_columns = [
        column
        for column in model_feature_columns
        if column not in expanded_df.columns
    ]

    if missing_model_columns:
        raise FeatureBuildError(
            "Generated rows are missing model features: "
            f"{missing_model_columns}"
        )

    model_feature_df = expanded_df[
        list(model_feature_columns)
    ].copy()

    return model_feature_df