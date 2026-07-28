"""Reusable alert presentation components."""

from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.utils.formatting import (
    format_aqi,
    format_duration_hours,
    format_timestamp,
)


def render_alert_summary(
    *,
    all_alerts: dict[str, Any],
    active_alerts: dict[str, Any],
) -> None:
    """Render compact alert summary cards."""

    columns = st.columns(4)

    with columns[0]:
        st.metric(
            "Alert episodes",
            int(
                all_alerts.get(
                    "episode_count",
                    0,
                )
            ),
        )

    with columns[1]:
        st.metric(
            "Currently active",
            int(
                active_alerts.get(
                    "current_count",
                    0,
                )
            ),
        )

    with columns[2]:
        st.metric(
            "Upcoming",
            int(
                active_alerts.get(
                    "upcoming_count",
                    0,
                )
            ),
        )

    hazardous_count = sum(
        bool(
            episode.get(
                "hazardous",
                False,
            )
        )
        for episode in all_alerts.get(
            "episodes",
            [],
        )
    )

    with columns[3]:
        st.metric(
            "Hazardous episodes",
            hazardous_count,
        )


def render_no_alert_state() -> None:
    """Render a clean normal-condition state."""

    st.success(
        "No active or upcoming air-quality alerts "
        "are present in the forecast."
    )

    st.caption(
        "The forecast currently remains below the "
        "configured operational alert thresholds."
    )


def render_alert_episode(
    *,
    episode: dict[str, Any],
    timezone_name: str,
) -> None:
    """Render one grouped alert episode."""

    alert_level = str(
        episode.get(
            "maximum_alert_level",
            "UNKNOWN",
        )
    )

    maximum_category = str(
        episode.get(
            "maximum_category",
            "Not available",
        )
    )

    title = (
        f"{alert_level.title()} · "
        f"{maximum_category}"
    )

    with st.container(
        border=True
    ):
        st.subheader(title)

        metric_columns = st.columns(4)

        with metric_columns[0]:
            st.metric(
                "Peak AQI",
                format_aqi(
                    episode.get(
                        "maximum_aqi"
                    )
                ),
            )

        with metric_columns[1]:
            st.metric(
                "Duration",
                format_duration_hours(
                    episode.get(
                        "duration_hours"
                    )
                ),
            )

        with metric_columns[2]:
            st.metric(
                "Starts",
                format_timestamp(
                    episode.get(
                        "start_time_utc"
                    ),
                    timezone_name=timezone_name,
                    include_timezone=False,
                ),
            )

        with metric_columns[3]:
            st.metric(
                "Ends",
                format_timestamp(
                    episode.get(
                        "end_time_utc"
                    ),
                    timezone_name=timezone_name,
                    include_timezone=False,
                ),
            )

        st.write(
            episode.get(
                "summary_message",
                "Air-quality alert episode.",
            )
        )

        recommended_action = episode.get(
            "recommended_action"
        )

        if recommended_action:
            st.info(
                recommended_action
            )

        status_parts = []

        if episode.get(
            "sensitive_groups_affected"
        ):
            status_parts.append(
                "Sensitive groups affected"
            )

        if episode.get(
            "general_population_affected"
        ):
            status_parts.append(
                "General population affected"
            )

        if episode.get("hazardous"):
            status_parts.append(
                "Hazardous condition"
            )

        if status_parts:
            st.caption(
                " · ".join(status_parts)
            )