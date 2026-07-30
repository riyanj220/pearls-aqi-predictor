"""Reusable hourly gap detection."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class MissingInterval:
    """One consecutive missing hourly interval."""

    start_time_utc: pd.Timestamp
    end_time_utc: pd.Timestamp
    missing_hours: int

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe representation."""

        return {
            "start_time_utc": (
                self.start_time_utc.isoformat()
            ),
            "end_time_utc": (
                self.end_time_utc.isoformat()
            ),
            "missing_hours": self.missing_hours,
        }


def normalize_utc_hourly_series(
    values: pd.Series,
) -> pd.DatetimeIndex:
    """Normalize timestamp values into unique UTC hours."""

    timestamps = pd.to_datetime(
        values,
        utc=True,
        errors="coerce",
    )

    if timestamps.isna().any():
        raise ValueError(
            "Timestamp series contains invalid values."
        )

    return pd.DatetimeIndex(
        timestamps.dt.floor("h").drop_duplicates().sort_values()
    )


def detect_hourly_gaps(
    *,
    timestamps: pd.Series,
    start_time_utc: pd.Timestamp,
    end_time_utc: pd.Timestamp,
) -> list[MissingInterval]:
    """Detect consecutive missing hours in an inclusive range."""

    start = pd.Timestamp(start_time_utc)

    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    else:
        start = start.tz_convert("UTC")

    end = pd.Timestamp(end_time_utc)

    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    else:
        end = end.tz_convert("UTC")

    start = start.floor("h")
    end = end.floor("h")

    if start > end:
        raise ValueError(
            "Backfill start time must not be after end time."
        )

    expected = pd.date_range(
        start=start,
        end=end,
        freq="h",
        tz="UTC",
    )

    available = normalize_utc_hourly_series(
        timestamps
    )

    missing = expected.difference(
        available
    )

    if missing.empty:
        return []

    intervals: list[MissingInterval] = []

    group_start = missing[0]
    previous = missing[0]

    for timestamp in missing[1:]:
        if timestamp - previous == pd.Timedelta(
            hours=1
        ):
            previous = timestamp
            continue

        intervals.append(
            MissingInterval(
                start_time_utc=group_start,
                end_time_utc=previous,
                missing_hours=int(
                    (
                        previous
                        - group_start
                    )
                    / pd.Timedelta(hours=1)
                )
                + 1,
            )
        )

        group_start = timestamp
        previous = timestamp

    intervals.append(
        MissingInterval(
            start_time_utc=group_start,
            end_time_utc=previous,
            missing_hours=int(
                (
                    previous
                    - group_start
                )
                / pd.Timedelta(hours=1)
            )
            + 1,
        )
    )

    return intervals