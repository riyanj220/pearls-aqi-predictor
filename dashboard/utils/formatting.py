"""Reusable formatting utilities for Streamlit views."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from dashboard.utils.constants import (
    NULL_DISPLAY_VALUE,
)


def is_missing(value: Any) -> bool:
    """Return whether a value should display as unavailable."""

    if value is None:
        return True

    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def format_pm25(
    value: Any,
    *,
    include_unit: bool = True,
) -> str:
    """Format a PM2.5 concentration."""

    if is_missing(value):
        return NULL_DISPLAY_VALUE

    formatted = f"{float(value):.1f}"

    if include_unit:
        return f"{formatted} µg/m³"

    return formatted


def format_aqi(value: Any) -> str:
    """Format an AQI value."""

    if is_missing(value):
        return NULL_DISPLAY_VALUE

    return str(int(round(float(value))))


def format_duration_hours(
    value: Any,
) -> str:
    """Format an hourly duration."""

    if is_missing(value):
        return NULL_DISPLAY_VALUE

    hours = int(value)

    return (
        f"{hours} hour"
        if hours == 1
        else f"{hours} hours"
    )


def parse_utc_timestamp(
    value: Any,
) -> pd.Timestamp | None:
    """Parse a value into a timezone-aware UTC timestamp."""

    if is_missing(value):
        return None

    timestamp = pd.to_datetime(
        value,
        utc=True,
        errors="coerce",
    )

    if pd.isna(timestamp):
        return None

    return pd.Timestamp(timestamp)


def convert_timestamp(
    value: Any,
    *,
    timezone_name: str,
) -> pd.Timestamp | None:
    """Convert an API UTC timestamp into the selected timezone."""

    timestamp = parse_utc_timestamp(value)

    if timestamp is None:
        return None

    try:
        target_timezone = ZoneInfo(
            timezone_name
        )
    except Exception as exc:
        raise ValueError(
            f"Unsupported timezone: {timezone_name}"
        ) from exc

    return timestamp.tz_convert(
        target_timezone
    )


def format_timestamp(
    value: Any,
    *,
    timezone_name: str,
    include_timezone: bool = True,
) -> str:
    """Format a timestamp for dashboard display."""

    timestamp = convert_timestamp(
        value,
        timezone_name=timezone_name,
    )

    if timestamp is None:
        return NULL_DISPLAY_VALUE

    formatted = timestamp.strftime(
        "%d %b %Y, %I:%M %p"
    )

    if include_timezone:
        return (
            f"{formatted} "
            f"{timestamp.tzname() or timezone_name}"
        )

    return formatted


def format_freshness(
    *,
    status: Any,
    age_hours: Any,
) -> str:
    """Format a freshness status with its age."""

    normalized_status = (
        str(status).upper()
        if not is_missing(status)
        else "UNKNOWN"
    )

    if is_missing(age_hours):
        return normalized_status

    age = float(age_hours)

    if age < 1:
        minutes = max(
            0,
            round(age * 60),
        )

        return (
            f"{normalized_status} · "
            f"{minutes} min old"
        )

    return (
        f"{normalized_status} · "
        f"{age:.1f} hours old"
    )


def format_boolean_status(
    value: Any,
    *,
    true_label: str = "Yes",
    false_label: str = "No",
) -> str:
    """Format a boolean value."""

    if is_missing(value):
        return NULL_DISPLAY_VALUE

    return (
        true_label
        if bool(value)
        else false_label
    )


def utc_now() -> datetime:
    """Return a timezone-aware UTC datetime."""

    return datetime.now(
        tz=ZoneInfo("UTC")
    )