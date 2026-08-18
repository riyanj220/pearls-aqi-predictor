"""Reusable dashboard loading, error, and empty states."""

from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.services.api_client import (
    DashboardAPIConnectionError,
    DashboardAPIContractError,
    DashboardAPIResponseError,
    DashboardAPITimeoutError,
)


def render_api_error(
    error: Exception,
) -> None:
    """Display a public-safe API failure message."""

    if isinstance(
        error,
        DashboardAPITimeoutError,
    ):
        st.warning(
            "The forecast service is taking longer than expected."
        )

        st.caption(
            "Please refresh the page in a moment."
        )

        return

    if isinstance(
        error,
        DashboardAPIConnectionError,
    ):
        st.warning(
            "The live forecast service is temporarily unavailable."
        )

        st.caption(
            "The service may be restarting or receiving an update. "
            "Please try again shortly."
        )

        return

    if isinstance(
        error,
        DashboardAPIResponseError,
    ):
        if error.code == "FORECAST_STALE":
            age_hours = error.details.get(
                "age_hours"
            )

            render_stale_warning(
                age_hours=(
                    float(age_hours)
                    if age_hours is not None
                    else None
                )
            )

            return

        if error.code in {
            "FORECAST_NOT_FOUND",
            "ARTIFACT_NOT_FOUND",
        }:
            st.warning(
                "A fresh air-quality forecast is temporarily unavailable."
            )

            st.caption(
                "Recent source observations may be incomplete. "
                "The forecasting pipeline will retry automatically."
            )

            return

        st.warning(
            error.message
            or (
                "The forecast could not be loaded "
                "at this time."
            )
        )

        if error.request_id:
            st.caption(
                "Reference ID: "
                f"`{error.request_id}`"
            )

        return

    if isinstance(
        error,
        DashboardAPIContractError,
    ):
        st.warning(
            "The forecast service returned data "
            "that could not be displayed safely."
        )

        st.caption(
            "Please refresh the dashboard shortly."
        )

        return

    st.warning(
        "The latest forecast could not be loaded."
    )


def render_forecast_status_notice(
    readiness_payload: dict[str, Any],
) -> None:
    """Render freshness and source-quality notices."""

    freshness = (
        readiness_payload.get(
            "freshness",
            {},
        )
        or {}
    )

    freshness_status = str(
        freshness.get(
            "status",
            "",
        )
    ).upper()

    age_hours_raw = (
        freshness.get(
            "age_hours"
        )
    )

    age_hours = (
        float(age_hours_raw)
        if age_hours_raw is not None
        else None
    )

    if freshness_status == "STALE":
        render_stale_warning(
            age_hours=age_hours
        )

        return

    if bool(
        readiness_payload.get(
            "source_degraded",
            False,
        )
    ):
        st.warning(
            "Recent PM2.5 sensor data contained a short gap. "
            "Missing hourly readings were estimated using "
            "bounded interpolation so the forecast could "
            "continue running."
        )

        st.caption(
            "Data quality: Degraded · "
            "Forecast service remains operational"
        )

        return

    if freshness_status == "AGING":
        st.info(
            "Live source data is arriving more slowly than usual. "
            "The latest validated forecast remains available."
        )


def render_stale_warning(
    *,
    age_hours: float | None,
) -> None:
    """Display a user-friendly stale-forecast warning."""

    age_text = (
        f"{age_hours:.1f} hours old"
        if age_hours is not None
        else "older than the normal refresh window"
    )

    st.warning(
        "Fresh sensor observations are temporarily delayed. "
        "The dashboard is showing the most recent validated "
        f"forecast, which is {age_text}."
    )

    st.caption(
        "Forecast values should be treated as older model output "
        "until fresh source data becomes available."
    )


def render_ready_with_limitations(
    limitations: list[str],
) -> None:
    """Display readiness limitations without blocking rendering."""

    if not limitations:
        return

    with st.expander(
        "Forecast limitations",
        expanded=False,
    ):
        for limitation in limitations:
            st.write(
                f"- {limitation}"
            )


def render_empty_forecast() -> None:
    """Display the empty result state."""

    st.info(
        "No forecast hours match the selected filters."
    )


def render_no_rolling_aqi() -> None:
    """Explain unavailable rolling AQI."""

    st.info(
        "Rolling 24-hour AQI is not available because "
        "a complete trailing PM2.5 exposure window "
        "could not be constructed."
    )


def render_no_alerts() -> None:
    """Display the normal no-alert state."""

    st.success(
        "No active alert conditions are present "
        "in the selected forecast range."
    )