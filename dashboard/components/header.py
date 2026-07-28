"""Dashboard header and status presentation."""

from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.utils.formatting import (
    format_timestamp,
)


def _display_readiness_status(
    status: str,
) -> str:
    """Convert internal readiness values into concise UI text."""

    normalized = status.upper()

    if normalized in {
        "READY",
        "READY_WITH_LIMITATIONS",
    }:
        return "Ready"

    if normalized == "STALE_FORECAST":
        return "Stale"

    if normalized in {
        "NOT_READY",
        "INVALID_ARTIFACTS",
    }:
        return "Unavailable"

    return "Unknown"


def _display_freshness(
    freshness: dict[str, Any],
) -> tuple[str, str]:
    """Return a short freshness value and supporting caption."""

    status = str(
        freshness.get(
            "status",
            "UNKNOWN",
        )
    ).title()

    age_hours = freshness.get(
        "age_hours"
    )

    if age_hours is None:
        return status, "Age unavailable"

    age = float(age_hours)

    if age < 1:
        return status, f"{round(age * 60)} minutes old"

    return status, f"{age:.1f} hours old"


def render_dashboard_header(
    *,
    title: str,
    forecast_payload: dict[str, Any],
    readiness_payload: dict[str, Any],
    timezone_name: str,
) -> None:
    """Render the main forecast page header."""

    location = forecast_payload.get(
        "location",
        {},
    )

    location_name = location.get(
        "name",
        "Zafar Memon DHA",
    )

    readiness_status = _display_readiness_status(
        str(
            readiness_payload.get(
                "status",
                "UNKNOWN",
            )
        )
    )

    freshness_value, freshness_caption = (
        _display_freshness(
            forecast_payload.get(
                "freshness",
                {},
            )
        )
    )

    generated_time = format_timestamp(
        forecast_payload.get(
            "generated_at_utc"
        ),
        timezone_name=timezone_name,
        include_timezone=False,
    )

    st.title(title)

    st.markdown(
        "### 72-hour PM2.5-based AQI forecast"
    )

    st.caption(
        f"Reference location: **{location_name}**"
    )

    status_columns = st.columns(4)

    with status_columns[0]:
        st.metric(
            "Service status",
            readiness_status,
        )

        st.caption(
            "Forecast API available"
        )

    with status_columns[1]:
        st.metric(
            "Forecast horizon",
            "72 hours",
        )

        st.caption(
            "Hourly predictions"
        )

    with status_columns[2]:
        st.metric(
            "Freshness",
            freshness_value,
        )

        st.caption(
            freshness_caption
        )

    with status_columns[3]:
        st.metric(
            "Generated",
            generated_time,
        )

        st.caption(
            timezone_name
        )