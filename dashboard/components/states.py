"""Reusable dashboard loading, error, and empty states."""

from __future__ import annotations

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
        st.error(
            "The forecast service took too long to respond."
        )

        st.caption(
            "Check that FastAPI is running, then refresh the dashboard."
        )
        return

    if isinstance(
        error,
        DashboardAPIConnectionError,
    ):
        st.error(
            "The dashboard cannot connect to the forecast service."
        )

        st.caption(
            "Start FastAPI and confirm that FASTAPI_BASE_URL is correct."
        )
        return

    if isinstance(
        error,
        DashboardAPIResponseError,
    ):
        st.error(error.message)

        details = []

        if error.code:
            details.append(
                f"Error code: `{error.code}`"
            )

        if error.request_id:
            details.append(
                f"Request ID: `{error.request_id}`"
            )

        if details:
            st.caption(" · ".join(details))

        return

    if isinstance(
        error,
        DashboardAPIContractError,
    ):
        st.error(
            "The forecast service returned an unexpected response."
        )

        st.caption(
            "The dashboard could not safely interpret the API payload."
        )
        return

    st.error(
        "The dashboard could not load the forecast."
    )


def render_stale_warning(
    *,
    age_hours: float | None,
) -> None:
    """Display a prominent stale-forecast warning."""

    age_text = (
        f"{age_hours:.1f} hours old"
        if age_hours is not None
        else "older than the configured limit"
    )

    st.warning(
        "The latest forecast is stale. "
        f"It is currently {age_text}. "
        "Treat the displayed values as historical forecast output."
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
            st.write(f"- {limitation}")


def render_empty_forecast() -> None:
    """Display the empty result state."""

    st.info(
        "No forecast hours match the selected filters."
    )


def render_no_rolling_aqi() -> None:
    """Explain unavailable rolling AQI."""

    st.info(
        "Rolling 24-hour AQI is not available because "
        "a complete trailing 24-hour PM2.5 window could "
        "not be constructed."
    )


def render_no_alerts() -> None:
    """Display the normal no-alert state."""

    st.success(
        "No active alert conditions are present in the selected forecast range."
    )