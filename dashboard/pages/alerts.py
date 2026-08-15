"""Forecast alert and AQI-risk dashboard page."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from dashboard.components.alert_cards import (
    render_alert_episode,
    render_alert_hero,
    render_alert_methodology,
    render_alert_summary,
    render_aqi_guide,
    render_aqi_types_explanation,
    render_no_alert_state,
)
from dashboard.components.states import (
    render_api_error,
)
from dashboard.components.theme import (
    apply_dashboard_theme,
)
from dashboard.services.api_client import (
    DashboardAPIError,
    cached_active_alerts,
    cached_alerts,
    clear_dashboard_api_cache,
)
from dashboard.utils.constants import (
    SUPPORTED_TIMEZONES,
)
from dashboard.utils.formatting import (
    format_timestamp,
    utc_now,
)


def _render_alert_sidebar() -> str:
    """Render alert-page controls and return timezone."""

    st.sidebar.html(
        """
        <div class="sidebar-section-label">
            ALERT VIEW
        </div>

        <div class="sidebar-section-title">
            Alert controls
        </div>
        """
    )

    st.sidebar.caption(
        "Review forecast alerts in your preferred timezone."
    )

    timezone_label = (
        st.sidebar.selectbox(
            "Display timezone",
            options=list(
                SUPPORTED_TIMEZONES.keys()
            ),
            index=0,
            key="alerts_timezone",
        )
    )

    st.sidebar.divider()

    refresh_clicked = (
        st.sidebar.button(
            "↻  Refresh alerts",
            help=(
                "Fetch the latest available "
                "alert information."
            ),
            key="alerts_refresh",
            width="stretch",
        )
    )

    if refresh_clicked:
        clear_dashboard_api_cache()

        st.session_state[
            "last_alert_refresh_utc"
        ] = utc_now()

        st.rerun()

    timezone_name = (
        SUPPORTED_TIMEZONES[
            timezone_label
        ]
    )

    last_refresh = (
        st.session_state.get(
            "last_alert_refresh_utc"
        )
    )

    if isinstance(
        last_refresh,
        datetime,
    ):
        st.sidebar.caption(
            "Manually refreshed "
            + format_timestamp(
                last_refresh,
                timezone_name=timezone_name,
            )
        )
    else:
        st.sidebar.caption(
            "Alert data follows the latest "
            "published forecast."
        )

    return timezone_name


def _render_page_heading() -> None:
    """Render the page title using the forecast visual language."""

    st.html(
        """
        <div class="section-kicker">
            FORECAST SAFETY
        </div>

        <div style="
            display:flex;
            justify-content:space-between;
            gap:1rem;
            align-items:flex-end;
            flex-wrap:wrap;
        ">
            <div>
                <h1 style="
                    margin:0;
                    font-size:2.15rem;
                ">
                    Air-quality alerts
                </h1>

                <div style="
                    color:#8d99aa;
                    margin-top:0.35rem;
                    font-size:0.92rem;
                ">
                    Risk monitoring across the latest
                    72-hour PM2.5 forecast
                </div>
            </div>
        </div>
        """
    )


def _render_overview(
    *,
    all_alerts: dict,
    active_alerts: dict,
    timezone_name: str,
) -> None:
    """Render operational alert state."""

    episodes = all_alerts.get(
        "episodes",
        [],
    )

    active_episode_records = (
        active_alerts.get(
            "episodes",
            [],
        )
    )

    currently_active = [
        episode
        for episode in active_episode_records
        if episode.get(
            "currently_active"
        )
    ]

    upcoming = [
        episode
        for episode in active_episode_records
        if episode.get(
            "upcoming"
        )
    ]

    if (
        not episodes
        and not currently_active
        and not upcoming
    ):
        st.html(
            """
            <div class="section-kicker">
                FORECAST STATUS
            </div>

            <div class="section-title">
                Current alert outlook
            </div>

            <div class="section-description">
                Operational alerts identified within
                the latest forecast horizon.
            </div>
            """
        )

        render_no_alert_state()
        return

    if currently_active:
        st.html(
            """
            <div class="section-kicker">
                ACTIVE NOW
            </div>

            <div class="section-title">
                Current alert episodes
            </div>

            <div class="section-description">
                Alert conditions currently active
                within the forecast.
            </div>
            """
        )

        for episode in currently_active:
            render_alert_episode(
                episode=episode,
                timezone_name=timezone_name,
            )

        st.markdown("")

    if upcoming:
        st.html(
            """
            <div class="section-kicker">
                UPCOMING RISK
            </div>

            <div class="section-title">
                Upcoming alert episodes
            </div>

            <div class="section-description">
                Conditions expected later within
                the forecast horizon.
            </div>
            """
        )

        for episode in upcoming:
            render_alert_episode(
                episode=episode,
                timezone_name=timezone_name,
            )

        st.markdown("")

    if episodes:
        st.divider()

        st.html(
            """
            <div class="section-kicker">
                FORECAST EPISODES
            </div>

            <div class="section-title">
                All alert episodes
            </div>

            <div class="section-description">
                Grouped alert events generated from
                the current 72-hour forecast.
            </div>
            """
        )

        for episode in episodes:
            render_alert_episode(
                episode=episode,
                timezone_name=timezone_name,
            )


def render_alerts_page() -> None:
    """Render alerts, AQI interpretation, and methodology."""

    apply_dashboard_theme()

    timezone_name = (
        _render_alert_sidebar()
    )

    try:
        with st.spinner(
            "Loading alert information..."
        ):
            all_alerts = (
                cached_alerts()
            )

            active_alerts = (
                cached_active_alerts()
            )

    except DashboardAPIError as error:
        render_api_error(error)
        return

    _render_page_heading()

    st.markdown("")

    render_alert_hero(
        all_alerts=all_alerts,
        active_alerts=active_alerts,
    )

    render_alert_summary(
        all_alerts=all_alerts,
        active_alerts=active_alerts,
    )

    st.markdown("")

    (
        overview_tab,
        guide_tab,
        methodology_tab,
    ) = st.tabs(
        [
            "Overview",
            "AQI guide",
            "Alert methodology",
        ]
    )

    with overview_tab:
        st.markdown("")

        _render_overview(
            all_alerts=all_alerts,
            active_alerts=active_alerts,
            timezone_name=timezone_name,
        )

    with guide_tab:
        st.markdown("")

        render_aqi_guide()

        st.divider()

        render_aqi_types_explanation()

    with methodology_tab:
        st.markdown("")

        render_alert_methodology()