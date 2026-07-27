"""Validation utilities for data preparation and live inference."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from app.core.config import Settings, settings


REFERENCE_READY = "READY"
REFERENCE_STALE_PM25 = "STALE_PM25_DATA"
REFERENCE_INSUFFICIENT_HISTORY = (
    "NOT_READY_INSUFFICIENT_PM25_HISTORY"
)
REFERENCE_WEATHER_INCOMPLETE = (
    "WEATHER_FORECAST_INCOMPLETE"
)


@dataclass(frozen=True)
class ReferenceSelectionResult:
    """Result of live reference-time readiness validation."""

    status: str
    message: str
    selected_reference_time: pd.Timestamp | None
    latest_valid_pm25_time: pd.Timestamp | None
    latest_pm25_age_hours: float | None
    inspected_candidates: int
    candidate_checks: list[dict[str, object]] = field(
        default_factory=list
    )

    @property
    def is_ready(self) -> bool:
        """Return whether live inference may continue."""

        return self.status == REFERENCE_READY


def _normalize_utc_timestamp(
    value: pd.Timestamp,
    *,
    name: str,
) -> pd.Timestamp:
    """Return one timezone-aware UTC timestamp."""

    timestamp = pd.Timestamp(value)

    if timestamp.tzinfo is None:
        raise ValueError(
            f"{name} must be timezone-aware."
        )

    return timestamp.tz_convert("UTC")


def select_latest_safe_reference_time(
    pm25_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    *,
    app_settings: Settings = settings,
    as_of_time: pd.Timestamp | None = None,
) -> ReferenceSelectionResult:
    """
    Select the newest reference hour that satisfies all live inputs.

    Requirements:

    - a valid current PM2.5 observation
    - exact hourly PM2.5 values from reference minus 24 hours
      through the reference hour
    - weather at the reference hour
    - weather for all 72 target hours
    - PM2.5 freshness within the configured threshold

    Missing pollution or weather values are never interpolated.
    """

    required_pm25_columns = {
        "datetime_utc",
        "pm25_ug_m3",
    }

    missing_pm25_columns = sorted(
        required_pm25_columns.difference(
            pm25_df.columns
        )
    )

    if missing_pm25_columns:
        raise ValueError(
            "PM2.5 data is missing required columns: "
            f"{missing_pm25_columns}"
        )

    if "datetime_utc" not in weather_df.columns:
        raise ValueError(
            "Weather data is missing datetime_utc."
        )

    pollution_df = pm25_df[
        [
            "datetime_utc",
            "pm25_ug_m3",
        ]
    ].copy()

    pollution_df["datetime_utc"] = pd.to_datetime(
        pollution_df["datetime_utc"],
        utc=True,
        errors="coerce",
    )

    pollution_df["pm25_ug_m3"] = pd.to_numeric(
        pollution_df["pm25_ug_m3"],
        errors="coerce",
    )

    weather_timestamps = pd.to_datetime(
        weather_df["datetime_utc"],
        utc=True,
        errors="coerce",
    )

    if pollution_df["datetime_utc"].isna().any():
        raise ValueError(
            "PM2.5 data contains invalid timestamps."
        )

    if weather_timestamps.isna().any():
        raise ValueError(
            "Weather data contains invalid timestamps."
        )

    if pollution_df["datetime_utc"].duplicated().any():
        raise ValueError(
            "PM2.5 data contains duplicate timestamps."
        )

    if weather_timestamps.duplicated().any():
        raise ValueError(
            "Weather data contains duplicate timestamps."
        )

    pollution_df = (
        pollution_df
        .sort_values("datetime_utc")
        .reset_index(drop=True)
    )

    valid_pm25_df = pollution_df.loc[
        pollution_df["pm25_ug_m3"].notna()
        & pollution_df["pm25_ug_m3"].gt(0)
    ].copy()

    if valid_pm25_df.empty:
        return ReferenceSelectionResult(
            status=REFERENCE_INSUFFICIENT_HISTORY,
            message=(
                "No valid positive PM2.5 observation is "
                "available."
            ),
            selected_reference_time=None,
            latest_valid_pm25_time=None,
            latest_pm25_age_hours=None,
            inspected_candidates=0,
        )

    current_time = (
        pd.Timestamp.now(tz="UTC")
        if as_of_time is None
        else _normalize_utc_timestamp(
            as_of_time,
            name="as_of_time",
        )
    )

    latest_valid_pm25_time = valid_pm25_df[
        "datetime_utc"
    ].max()

    latest_pm25_age_hours = (
        current_time - latest_valid_pm25_time
    ).total_seconds() / 3_600

    if (
        latest_pm25_age_hours
        > app_settings.pm25_freshness_threshold_hours
    ):
        return ReferenceSelectionResult(
            status=REFERENCE_STALE_PM25,
            message=(
                "The latest valid PM2.5 observation exceeds "
                "the configured freshness threshold."
            ),
            selected_reference_time=None,
            latest_valid_pm25_time=latest_valid_pm25_time,
            latest_pm25_age_hours=float(
                latest_pm25_age_hours
            ),
            inspected_candidates=0,
        )

    pollution_indexed = pollution_df.set_index(
        "datetime_utc"
    )

    weather_timestamp_index = pd.DatetimeIndex(
        weather_timestamps
    )

    candidate_times = (
        valid_pm25_df["datetime_utc"]
        .sort_values(ascending=False)
        .tolist()
    )

    candidate_checks: list[dict[str, object]] = []
    history_ready_candidate_found = False

    for candidate_time in candidate_times:
        candidate_age_hours = (
            current_time - candidate_time
        ).total_seconds() / 3_600

        if (
            candidate_age_hours
            > app_settings.pm25_freshness_threshold_hours
        ):
            break

        # A 24-hour lag requires t-24, while the 24-hour
        # rolling mean requires t-23 through t. Therefore,
        # the complete safe input range is t-24 through t.
        required_history_timeline = pd.date_range(
            start=(
                candidate_time
                - pd.Timedelta(
                    hours=app_settings.minimum_pm25_history_hours
                )
            ),
            end=candidate_time,
            freq="h",
            tz="UTC",
        )

        candidate_history = pollution_indexed.reindex(
            required_history_timeline
        )

        missing_history_timestamps = int(
            candidate_history[
                "pm25_ug_m3"
            ].isna().sum()
        )

        history_complete = (
            missing_history_timestamps == 0
        )

        reference_weather_available = (
            candidate_time
            in weather_timestamp_index
        )

        target_timeline = pd.date_range(
            start=candidate_time + pd.Timedelta(hours=1),
            periods=app_settings.forecast_horizon_hours,
            freq="h",
            tz="UTC",
        )

        missing_target_weather = (
            target_timeline.difference(
                weather_timestamp_index
            )
        )

        target_weather_complete = (
            len(missing_target_weather) == 0
        )

        candidate_check = {
            "candidate_reference_time": candidate_time,
            "candidate_age_hours": float(
                candidate_age_hours
            ),
            "required_pm25_history_rows": len(
                required_history_timeline
            ),
            "missing_pm25_history_hours": (
                missing_history_timestamps
            ),
            "pm25_history_complete": history_complete,
            "reference_weather_available": (
                reference_weather_available
            ),
            "required_target_weather_hours": len(
                target_timeline
            ),
            "missing_target_weather_hours": len(
                missing_target_weather
            ),
            "target_weather_complete": (
                target_weather_complete
            ),
        }

        candidate_checks.append(candidate_check)

        if not history_complete:
            continue

        history_ready_candidate_found = True

        if not reference_weather_available:
            continue

        if not target_weather_complete:
            continue

        return ReferenceSelectionResult(
            status=REFERENCE_READY,
            message=(
                "A fresh reference timestamp with complete "
                "PM2.5 history and weather coverage was found."
            ),
            selected_reference_time=candidate_time,
            latest_valid_pm25_time=latest_valid_pm25_time,
            latest_pm25_age_hours=float(
                latest_pm25_age_hours
            ),
            inspected_candidates=len(candidate_checks),
            candidate_checks=candidate_checks,
        )

    if history_ready_candidate_found:
        final_status = REFERENCE_WEATHER_INCOMPLETE
        final_message = (
            "A candidate with complete PM2.5 history was "
            "found, but reference or target weather coverage "
            "was incomplete."
        )
    else:
        final_status = REFERENCE_INSUFFICIENT_HISTORY
        final_message = (
            "No fresh candidate contained every exact "
            "PM2.5 hour required for lag, rolling, and "
            "change features."
        )

    return ReferenceSelectionResult(
        status=final_status,
        message=final_message,
        selected_reference_time=None,
        latest_valid_pm25_time=latest_valid_pm25_time,
        latest_pm25_age_hours=float(
            latest_pm25_age_hours
        ),
        inspected_candidates=len(candidate_checks),
        candidate_checks=candidate_checks,
    )