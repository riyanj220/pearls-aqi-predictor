"""Forecast alert dashboard page."""

from __future__ import annotations

import streamlit as st

from dashboard.components.alert_cards import (
    render_alert_episode,
    render_alert_summary,
    render_no_alert_state,
)
from dashboard.components.states import (
    render_api_error,
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


def render_alerts_page() -> None:
    """Render active, upcoming, and grouped alerts."""

    st.title(
        "Air-quality alerts"
    )

    st.caption(
        "Current, upcoming, and grouped alert conditions "
        "from the latest 72-hour forecast."
    )

    with st.sidebar:
        st.header(
            "Alert controls"
        )

        timezone_label = st.selectbox(
            "Display timezone",
            options=list(
                SUPPORTED_TIMEZONES.keys()
            ),
            index=0,
            key="alerts_timezone",
        )

        if st.button(
            "Refresh alerts",
            width="stretch",
            type="primary",
        ):
            clear_dashboard_api_cache()
            st.rerun()

    timezone_name = (
        SUPPORTED_TIMEZONES[
            timezone_label
        ]
    )

    try:
        with st.spinner(
            "Loading alert information..."
        ):
            all_alerts = cached_alerts()

            active_alerts = (
                cached_active_alerts()
            )

    except DashboardAPIError as error:
        render_api_error(error)
        return

    render_alert_summary(
        all_alerts=all_alerts,
        active_alerts=active_alerts,
    )

    st.divider()

    episodes = all_alerts.get(
        "episodes",
        [],
    )

    current_count = int(
        active_alerts.get(
            "current_count",
            0,
        )
    )

    upcoming_count = int(
        active_alerts.get(
            "upcoming_count",
            0,
        )
    )

    if (
        not episodes
        and current_count == 0
        and upcoming_count == 0
    ):
        render_no_alert_state()
        return

    active_episode_records = (
        active_alerts.get(
            "episodes",
            [],
        )
    )

    currently_active = [
        episode
        for episode
        in active_episode_records
        if episode.get(
            "currently_active"
        )
    ]

    upcoming = [
        episode
        for episode
        in active_episode_records
        if episode.get(
            "upcoming"
        )
    ]

    if currently_active:
        st.subheader(
            "Currently active"
        )

        for episode in currently_active:
            render_alert_episode(
                episode=episode,
                timezone_name=timezone_name,
            )

    if upcoming:
        st.subheader(
            "Upcoming alerts"
        )

        for episode in upcoming:
            render_alert_episode(
                episode=episode,
                timezone_name=timezone_name,
            )

    st.subheader(
        "All alert episodes"
    )

    for episode in episodes:
        render_alert_episode(
            episode=episode,
            timezone_name=timezone_name,
        )