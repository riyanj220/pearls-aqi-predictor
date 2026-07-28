"""Tests for dashboard formatting utilities."""

from __future__ import annotations

from dashboard.utils.formatting import (
    format_aqi,
    format_freshness,
    format_pm25,
    format_timestamp,
)


def test_numeric_and_missing_formatting() -> None:
    """PM2.5 and AQI values should display consistently."""

    assert format_pm25(14.34) == "14.3 µg/m³"
    assert format_aqi(61) == "61"

    assert format_pm25(None) == "Not available"
    assert format_aqi(None) == "Not available"


def test_timezone_conversion() -> None:
    """UTC timestamps should convert into Karachi time."""

    value = "2026-07-28T14:00:00Z"

    karachi_result = format_timestamp(
        value,
        timezone_name="Asia/Karachi",
    )

    utc_result = format_timestamp(
        value,
        timezone_name="UTC",
    )

    assert "07:00 PM" in karachi_result
    assert "02:00 PM" in utc_result


def test_freshness_formatting() -> None:
    """Freshness should show a readable age."""

    assert (
        format_freshness(
            status="FRESH",
            age_hours=0.5,
        )
        == "FRESH · 30 min old"
    )

    assert (
        format_freshness(
            status="AGING",
            age_hours=7.25,
        )
        == "AGING · 7.2 hours old"
    )