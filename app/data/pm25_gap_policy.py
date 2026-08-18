"""Controlled recovery for short PM2.5 sensor-data gaps."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.core.config import Settings, settings


PM25_QUALITY_GOOD = "GOOD"
PM25_QUALITY_DEGRADED = "DEGRADED"

PM25_IMPUTATION_METHOD = "linear"


class PM25GapRecoveryError(ValueError):
    """Raised when PM2.5 gap recovery cannot be evaluated safely."""


@dataclass(frozen=True)
class PM25GapRecoveryResult:
    """Result of one PM2.5 short-gap recovery pass."""

    dataframe: pd.DataFrame

    imputation_used: bool

    imputed_timestamps: tuple[
        pd.Timestamp,
        ...,
    ]

    unresolved_timestamps: tuple[
        pd.Timestamp,
        ...,
    ]

    maximum_imputed_gap_hours: int

    def quality_for_window(
        self,
        *,
        start_time: pd.Timestamp,
        end_time: pd.Timestamp,
    ) -> dict[str, object]:
        """
        Return data-quality metadata for one model input window.

        Only imputed values actually used inside the model's
        PM2.5 history window mark the forecast as degraded.
        """

        start = _ensure_utc(
            start_time,
            name="start_time",
        )

        end = _ensure_utc(
            end_time,
            name="end_time",
        )

        used_imputed_timestamps = [
            timestamp
            for timestamp in self.imputed_timestamps
            if start <= timestamp <= end
        ]

        unresolved_in_window = [
            timestamp
            for timestamp in self.unresolved_timestamps
            if start <= timestamp <= end
        ]

        degraded = bool(
            used_imputed_timestamps
        )

        return {
            "status": (
                PM25_QUALITY_DEGRADED
                if degraded
                else PM25_QUALITY_GOOD
            ),
            "pm25_imputation_used": degraded,
            "imputation_method": (
                PM25_IMPUTATION_METHOD
                if degraded
                else None
            ),
            "imputed_hours": len(
                used_imputed_timestamps
            ),
            "imputed_timestamps": [
                timestamp.isoformat()
                for timestamp
                in used_imputed_timestamps
            ],
            "unresolved_hours": len(
                unresolved_in_window
            ),
            "unresolved_timestamps": [
                timestamp.isoformat()
                for timestamp
                in unresolved_in_window
            ],
        }


def _ensure_utc(
    value: pd.Timestamp,
    *,
    name: str,
) -> pd.Timestamp:
    """Normalize one timezone-aware timestamp to UTC."""

    timestamp = pd.Timestamp(value)

    if timestamp.tzinfo is None:
        raise PM25GapRecoveryError(
            f"{name} must be timezone-aware."
        )

    return timestamp.tz_convert("UTC")


def _missing_groups(
    missing_mask: pd.Series,
) -> list[list[pd.Timestamp]]:
    """Return consecutive groups of missing hourly timestamps."""

    groups: list[list[pd.Timestamp]] = []

    current_group: list[pd.Timestamp] = []

    for timestamp, is_missing in missing_mask.items():
        if bool(is_missing):
            current_group.append(
                pd.Timestamp(timestamp)
            )

        elif current_group:
            groups.append(
                current_group
            )

            current_group = []

    if current_group:
        groups.append(
            current_group
        )

    return groups


def recover_short_pm25_gaps(
    dataframe: pd.DataFrame,
    *,
    app_settings: Settings = settings,
) -> PM25GapRecoveryResult:
    """
    Recover small bounded PM2.5 gaps using linear interpolation.

    Rules:

    - existing valid observations are never overwritten;
    - only consecutive gaps up to the configured maximum are filled;
    - interpolation requires valid observations immediately before
      and after the gap;
    - leading/trailing gaps are never filled;
    - gaps larger than the configured maximum remain missing;
    - the OpenAQ source dataframe itself is not modified.
    """

    required_columns = {
        "datetime_utc",
        "pm25_ug_m3",
    }

    missing_columns = sorted(
        required_columns.difference(
            dataframe.columns
        )
    )

    if missing_columns:
        raise PM25GapRecoveryError(
            "PM2.5 gap recovery is missing required columns: "
            f"{missing_columns}"
        )

    if dataframe.empty:
        raise PM25GapRecoveryError(
            "PM2.5 gap recovery received an empty dataframe."
        )

    source_df = dataframe.copy()

    source_df["datetime_utc"] = pd.to_datetime(
        source_df["datetime_utc"],
        utc=True,
        errors="coerce",
    )

    source_df["pm25_ug_m3"] = pd.to_numeric(
        source_df["pm25_ug_m3"],
        errors="coerce",
    )

    if source_df["datetime_utc"].isna().any():
        raise PM25GapRecoveryError(
            "PM2.5 gap recovery received invalid timestamps."
        )

    if source_df["datetime_utc"].duplicated().any():
        raise PM25GapRecoveryError(
            "PM2.5 gap recovery received duplicate timestamps."
        )

    source_df = (
        source_df
        .sort_values("datetime_utc")
        .reset_index(drop=True)
    )

    start_time = source_df[
        "datetime_utc"
    ].min()

    end_time = source_df[
        "datetime_utc"
    ].max()

    complete_timeline = pd.date_range(
        start=start_time,
        end=end_time,
        freq="h",
        tz="UTC",
    )

    working_df = (
        source_df
        .set_index("datetime_utc")
        .reindex(complete_timeline)
    )

    working_df.index.name = (
        "datetime_utc"
    )

    working_df["pm25_is_imputed"] = False
    working_df["pm25_imputation_method"] = None

    missing_mask = (
        working_df["pm25_ug_m3"].isna()
    )

    missing_groups = _missing_groups(
        missing_mask
    )

    imputed_timestamps: list[
        pd.Timestamp
    ] = []

    maximum_imputed_gap_hours = 0

    if (
        app_settings
        .pm25_short_gap_imputation_enabled
    ):
        for group in missing_groups:
            gap_size = len(group)

            if (
                gap_size
                > app_settings
                .pm25_max_imputation_gap_hours
            ):
                continue

            first_missing = group[0]
            last_missing = group[-1]

            previous_time = (
                first_missing
                - pd.Timedelta(hours=1)
            )

            next_time = (
                last_missing
                + pd.Timedelta(hours=1)
            )

            if (
                previous_time
                not in working_df.index
                or next_time
                not in working_df.index
            ):
                continue

            previous_value = (
                working_df.at[
                    previous_time,
                    "pm25_ug_m3",
                ]
            )

            next_value = (
                working_df.at[
                    next_time,
                    "pm25_ug_m3",
                ]
            )

            if (
                pd.isna(previous_value)
                or pd.isna(next_value)
            ):
                continue

            previous_value = float(
                previous_value
            )

            next_value = float(
                next_value
            )

            if (
                not np.isfinite(previous_value)
                or not np.isfinite(next_value)
                or previous_value <= 0
                or next_value <= 0
            ):
                continue

            interpolated_values = (
                np.linspace(
                    previous_value,
                    next_value,
                    gap_size + 2,
                )[1:-1]
            )

            for (
                timestamp,
                interpolated_value,
            ) in zip(
                group,
                interpolated_values,
                strict=True,
            ):
                working_df.at[
                    timestamp,
                    "pm25_ug_m3",
                ] = float(
                    interpolated_value
                )

                working_df.at[
                    timestamp,
                    "pm25_is_imputed",
                ] = True

                working_df.at[
                    timestamp,
                    "pm25_imputation_method",
                ] = PM25_IMPUTATION_METHOD

                imputed_timestamps.append(
                    timestamp
                )

            maximum_imputed_gap_hours = max(
                maximum_imputed_gap_hours,
                gap_size,
            )

    unresolved_mask = (
        working_df["pm25_ug_m3"].isna()
    )

    unresolved_timestamps = [
        pd.Timestamp(timestamp)
        for timestamp
        in working_df.index[
            unresolved_mask
        ]
    ]

    result_df = (
        working_df
        .reset_index()
        .sort_values("datetime_utc")
        .reset_index(drop=True)
    )

    return PM25GapRecoveryResult(
        dataframe=result_df,
        imputation_used=bool(
            imputed_timestamps
        ),
        imputed_timestamps=tuple(
            imputed_timestamps
        ),
        unresolved_timestamps=tuple(
            unresolved_timestamps
        ),
        maximum_imputed_gap_hours=(
            maximum_imputed_gap_hours
        ),
    )
