"""Tests for operational PM2.5 short-gap recovery."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from app.core.config import settings
from app.data.pm25_gap_policy import (
    PM25_QUALITY_DEGRADED,
    PM25_QUALITY_GOOD,
    recover_short_pm25_gaps,
)


def _frame(
    values: list[
        tuple[str, float | None]
    ],
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "datetime_utc": [
                timestamp
                for timestamp, _
                in values
            ],
            "pm25_ug_m3": [
                value
                for _, value
                in values
            ],
        }
    )


def test_continuous_data_is_unchanged() -> None:
    dataframe = _frame(
        [
            ("2026-08-18T00:00:00Z", 5.0),
            ("2026-08-18T01:00:00Z", 6.0),
            ("2026-08-18T02:00:00Z", 7.0),
        ]
    )

    result = recover_short_pm25_gaps(
        dataframe
    )

    assert not result.imputation_used

    assert (
        result.dataframe[
            "pm25_is_imputed"
        ].sum()
        == 0
    )


def test_three_hour_bounded_gap_is_interpolated() -> None:
    dataframe = _frame(
        [
            ("2026-08-17T02:00:00Z", 12.1),
            ("2026-08-17T06:00:00Z", 4.3),
        ]
    )

    result = recover_short_pm25_gaps(
        dataframe
    )

    assert result.imputation_used

    assert len(
        result.imputed_timestamps
    ) == 3

    recovered = (
        result.dataframe
        .set_index("datetime_utc")
    )

    assert recovered.loc[
        pd.Timestamp(
            "2026-08-17T03:00:00Z"
        ),
        "pm25_is_imputed",
    ]

    assert recovered.loc[
        pd.Timestamp(
            "2026-08-17T04:00:00Z"
        ),
        "pm25_is_imputed",
    ]

    assert recovered.loc[
        pd.Timestamp(
            "2026-08-17T05:00:00Z"
        ),
        "pm25_is_imputed",
    ]


def test_four_hour_gap_is_not_interpolated() -> None:
    dataframe = _frame(
        [
            ("2026-08-17T01:00:00Z", 10.0),
            ("2026-08-17T06:00:00Z", 5.0),
        ]
    )

    result = recover_short_pm25_gaps(
        dataframe
    )

    assert not result.imputation_used

    assert len(
        result.unresolved_timestamps
    ) == 4


def test_disabled_policy_does_not_interpolate() -> None:
    disabled_settings = replace(
        settings,
        pm25_short_gap_imputation_enabled=False,
    )

    dataframe = _frame(
        [
            ("2026-08-17T02:00:00Z", 12.1),
            ("2026-08-17T06:00:00Z", 4.3),
        ]
    )

    result = recover_short_pm25_gaps(
        dataframe,
        app_settings=disabled_settings,
    )

    assert not result.imputation_used


def test_quality_only_counts_values_used_by_model_window() -> None:
    dataframe = _frame(
        [
            ("2026-08-17T02:00:00Z", 12.1),
            ("2026-08-17T06:00:00Z", 4.3),
            ("2026-08-18T06:00:00Z", 8.0),
        ]
    )

    result = recover_short_pm25_gaps(
        dataframe
    )

    degraded_quality = (
        result.quality_for_window(
            start_time=pd.Timestamp(
                "2026-08-17T02:00:00Z"
            ),
            end_time=pd.Timestamp(
                "2026-08-17T06:00:00Z"
            ),
        )
    )

    good_quality = (
        result.quality_for_window(
            start_time=pd.Timestamp(
                "2026-08-17T07:00:00Z"
            ),
            end_time=pd.Timestamp(
                "2026-08-18T06:00:00Z"
            ),
        )
    )

    assert (
        degraded_quality["status"]
        == PM25_QUALITY_DEGRADED
    )

    assert (
        degraded_quality[
            "imputed_hours"
        ]
        == 3
    )

    assert (
        good_quality["status"]
        == PM25_QUALITY_GOOD
    )
