"""Reusable alert and AQI-risk presentation components."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from dashboard.utils.constants import (
    AQI_COLOR_FALLBACKS,
)
from dashboard.utils.formatting import (
    format_aqi,
    format_duration_hours,
    format_timestamp,
)


AQI_GUIDE = [
    {
        "range": "0–50",
        "category": "Good",
        "description": (
            "Air quality is generally satisfactory."
        ),
    },
    {
        "range": "51–100",
        "category": "Moderate",
        "description": (
            "Air quality is generally acceptable."
        ),
    },
    {
        "range": "101–150",
        "category": (
            "Unhealthy for Sensitive Groups"
        ),
        "description": (
            "Sensitive groups may require "
            "additional awareness."
        ),
    },
    {
        "range": "151–200",
        "category": "Unhealthy",
        "description": (
            "Elevated air-quality risk may "
            "affect more people."
        ),
    },
    {
        "range": "201–300",
        "category": "Very Unhealthy",
        "description": (
            "Air-quality conditions represent "
            "a substantially elevated risk."
        ),
    },
    {
        "range": "301–500",
        "category": "Hazardous",
        "description": (
            "The highest AQI risk category."
        ),
    },
]


def _category_color(
    category: str,
) -> str:
    """Return the project AQI color for a category."""

    return AQI_COLOR_FALLBACKS.get(
        category,
        "#60A5FA",
    )


def _find_primary_episode(
    *,
    all_alerts: dict[str, Any],
    active_alerts: dict[str, Any],
) -> dict[str, Any] | None:
    """Return the most relevant active/upcoming alert episode."""

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

    if currently_active:
        return currently_active[0]

    upcoming = [
        episode
        for episode in active_episode_records
        if episode.get(
            "upcoming"
        )
    ]

    if upcoming:
        return upcoming[0]

    episodes = all_alerts.get(
        "episodes",
        [],
    )

    if episodes:
        return episodes[0]

    return None


def render_alert_hero(
    *,
    all_alerts: dict[str, Any],
    active_alerts: dict[str, Any],
) -> None:
    """Render the current 72-hour alert posture."""

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

    primary_episode = (
        _find_primary_episode(
            all_alerts=all_alerts,
            active_alerts=active_alerts,
        )
    )

    if current_count > 0:
        title = "Active air-quality alert"
        state_label = "ACTIVE"
        state_class = "danger"
        eyebrow = "Current risk status"

        category = str(
            (
                primary_episode
                or {}
            ).get(
                "maximum_category",
                "Alert condition",
            )
        )

        peak_aqi = format_aqi(
            (
                primary_episode
                or {}
            ).get(
                "maximum_aqi"
            )
        )

        description = str(
            (
                primary_episode
                or {}
            ).get(
                "summary_message",
                "An air-quality alert is currently active.",
            )
        )

        accent = _category_color(
            category
        )

        main_value = peak_aqi
        main_label = "Peak episode AQI"

    elif upcoming_count > 0:
        title = "Upcoming air-quality alert"
        state_label = "UPCOMING"
        state_class = "warning"
        eyebrow = "Forecast risk status"

        category = str(
            (
                primary_episode
                or {}
            ).get(
                "maximum_category",
                "Upcoming alert",
            )
        )

        peak_aqi = format_aqi(
            (
                primary_episode
                or {}
            ).get(
                "maximum_aqi"
            )
        )

        description = str(
            (
                primary_episode
                or {}
            ).get(
                "summary_message",
                "An alert condition is expected later "
                "in the current forecast horizon.",
            )
        )

        accent = _category_color(
            category
        )

        main_value = peak_aqi
        main_label = "Expected peak AQI"

    else:
        title = "No active alerts"
        state_label = "MONITORING"
        state_class = "normal"
        eyebrow = "Current risk status"

        category = "Normal conditions"

        description = (
            "The latest 72-hour forecast does not "
            "currently contain an active or upcoming "
            "air-quality alert episode."
        )

        accent = "#4ADE80"
        main_value = "72h"
        main_label = "Forecast coverage"

    st.html(
        f"""
        <div
            class="alert-hero"
            style="--alert-accent:{accent};"
        >
            <div class="alert-hero-top">
                <div>
                    <div class="aqi-hero-eyebrow">
                        {escape(eyebrow)}
                    </div>

                    <div class="alert-hero-title">
                        {escape(title)}
                    </div>
                </div>

                <div class="alert-state-pill {state_class}">
                    <span class="alert-state-dot"></span>
                    {escape(state_label)}
                </div>
            </div>

            <div class="alert-hero-main">
                <div>
                    <div class="alert-main-value">
                        {escape(main_value)}
                    </div>

                    <div class="alert-main-label">
                        {escape(main_label)}
                    </div>
                </div>

                <div
                    class="alert-category-pill"
                    style="--category-color:{accent};"
                >
                    {escape(category)}
                </div>
            </div>

            <p class="alert-hero-message">
                {escape(description)}
            </p>
        </div>
        """
    )


def render_alert_summary(
    *,
    all_alerts: dict[str, Any],
    active_alerts: dict[str, Any],
) -> None:
    """Render compact alert summary cards."""

    episode_count = int(
        all_alerts.get(
            "episode_count",
            0,
        )
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

    columns = st.columns(4)

    with columns[0]:
        st.metric(
            "Currently active",
            current_count,
        )

        st.caption(
            "Active now"
            if current_count
            else "None active"
        )

    with columns[1]:
        st.metric(
            "Upcoming",
            upcoming_count,
        )

        st.caption(
            "Expected later"
            if upcoming_count
            else "None expected"
        )

    with columns[2]:
        st.metric(
            "Alert episodes",
            episode_count,
        )

        st.caption(
            "Grouped forecast events"
        )

    with columns[3]:
        st.metric(
            "Hazardous episodes",
            hazardous_count,
        )

        st.caption(
            "Highest-risk events"
        )


def render_no_alert_state() -> None:
    """Render a subtle normal-condition empty state."""

    st.html(
        """
        <div class="alert-empty-state">
            <div class="alert-empty-icon">
                ✓
            </div>

            <div>
                <div class="alert-empty-title">
                    No alert episodes in this forecast
                </div>

                <div class="alert-empty-description">
                    The current forecast does not contain
                    an active or upcoming air-quality alert.
                    Monitoring continues across the full
                    forecast horizon.
                </div>
            </div>
        </div>
        """
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

    accent = _category_color(
        maximum_category
    )

    title = (
        f"{maximum_category}"
    )

    with st.container(
        border=True
    ):
        st.html(
            f"""
            <div
                class="episode-heading"
                style="--episode-accent:{accent};"
            >
                <div class="episode-accent"></div>

                <div>
                    <div class="episode-kicker">
                        {escape(alert_level)}
                    </div>

                    <div class="episode-title">
                        {escape(title)}
                    </div>
                </div>
            </div>
            """
        )

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

        st.markdown("")

        summary_message = episode.get(
            "summary_message"
        )

        if summary_message:
            st.write(
                summary_message
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

        if episode.get(
            "hazardous"
        ):
            status_parts.append(
                "Hazardous condition"
            )

        if status_parts:
            badges = "".join(
                (
                    '<span class="episode-status-badge">'
                    f"{escape(part)}"
                    "</span>"
                )
                for part in status_parts
            )

            st.html(
                f"""
                <div class="episode-status-row">
                    {badges}
                </div>
                """
            )

        recommended_action = (
            episode.get(
                "recommended_action"
            )
        )

        if recommended_action:
            st.markdown(
                "#### Recommended action"
            )

            st.info(
                recommended_action
            )


def render_aqi_guide() -> None:
    """Render the AQI category guide used by the dashboard."""

    st.html(
        """
        <div class="section-kicker">
            AQI REFERENCE
        </div>

        <div class="section-title">
            Understanding the AQI scale
        </div>

        <div class="section-description">
            The dashboard interprets forecast PM2.5
            values using these AQI category bands.
        </div>
        """
    )

    rows = [
        AQI_GUIDE[:3],
        AQI_GUIDE[3:],
    ]

    for row in rows:
        columns = st.columns(
            len(row)
        )

        for column, item in zip(
            columns,
            row,
            strict=True,
        ):
            color = _category_color(
                item["category"]
            )

            with column:
                st.html(
                    f"""
                    <div
                        class="aqi-guide-card"
                        style="--guide-color:{color};"
                    >
                        <div class="aqi-guide-range">
                            {escape(item["range"])}
                        </div>

                        <div class="aqi-guide-category">
                            {escape(item["category"])}
                        </div>

                        <div class="aqi-guide-description">
                            {escape(item["description"])}
                        </div>
                    </div>
                    """
                )

    st.markdown("")

    st.caption(
        "These category bands support forecast interpretation. "
        "The application's configured alert policy determines "
        "whether a forecast hour becomes an operational alert."
    )


def render_aqi_types_explanation() -> None:
    """Explain the AQI representations used in the project."""

    st.markdown("### AQI values used by the system")

    hourly_column, rolling_column = (
        st.columns(
            2,
            gap="large",
        )
    )

    with hourly_column:
        st.html(
            """
            <div class="aqi-explainer-card">
                <div class="aqi-explainer-label">
                    INDICATIVE HOURLY AQI
                </div>

                <div class="aqi-explainer-title">
                    Single-hour interpretation
                </div>

                <div class="aqi-explainer-body">
                    Each predicted hourly PM2.5 value is
                    converted into an indicative AQI value
                    and category for forecast interpretation.
                </div>
            </div>
            """
        )

    with rolling_column:
        st.html(
            """
            <div class="aqi-explainer-card">
                <div class="aqi-explainer-label">
                    ROLLING 24-HOUR AQI
                </div>

                <div class="aqi-explainer-title">
                    Trailing exposure interpretation
                </div>

                <div class="aqi-explainer-body">
                    Where a complete trailing window is
                    available, observed and forecast PM2.5
                    values are combined into a rolling
                    24-hour AQI interpretation.
                </div>
            </div>
            """
        )


def render_alert_methodology() -> None:
    """Explain the project's operational alert pipeline."""

    st.html(
        """
        <div class="section-kicker">
            ALERT PIPELINE
        </div>

        <div class="section-title">
            How forecast alerts are determined
        </div>

        <div class="section-description">
            Alerts are generated from the same validated
            forecast data shown elsewhere in the dashboard.
        </div>
        """
    )

    steps = [
        (
            "01",
            "PM2.5 forecast",
            (
                "The forecasting pipeline produces "
                "hourly PM2.5 predictions across the "
                "72-hour horizon."
            ),
        ),
        (
            "02",
            "AQI interpretation",
            (
                "Predicted PM2.5 values are converted "
                "into indicative hourly AQI values "
                "and categories."
            ),
        ),
        (
            "03",
            "Rolling exposure",
            (
                "A trailing 24-hour PM2.5 window is "
                "evaluated where sufficient observed "
                "and forecast information is available."
            ),
        ),
        (
            "04",
            "Alert evaluation",
            (
                "The configured alert policy evaluates "
                "each forecast hour and records the "
                "alert level, basis, trigger AQI, and "
                "trigger category."
            ),
        ),
        (
            "05",
            "Episode grouping",
            (
                "Consecutive alert hours are grouped "
                "into episodes with start/end times, "
                "duration, peak AQI, and severity."
            ),
        ),
        (
            "06",
            "Health guidance",
            (
                "Each alert episode carries a summary "
                "and recommended action based on the "
                "evaluated forecast condition."
            ),
        ),
    ]

    for number, title, description in steps:
        st.html(
            f"""
            <div class="method-step">
                <div class="method-step-number">
                    {number}
                </div>

                <div>
                    <div class="method-step-title">
                        {escape(title)}
                    </div>

                    <div class="method-step-description">
                        {escape(description)}
                    </div>
                </div>
            </div>
            """
        )

    st.markdown("")

    with st.expander(
        "Important interpretation notes",
        expanded=False,
    ):
        st.write(
            "- Forecast AQI values are generated from "
            "predicted PM2.5 and are indicative rather "
            "than an official regulatory AQI product."
        )

        st.write(
            "- Rolling 24-hour AQI requires a complete "
            "trailing PM2.5 window."
        )

        st.write(
            "- Alert generation uses the configured "
            "operational alert policy rather than the "
            "dashboard presentation layer."
        )

        st.write(
            "- Consecutive triggered hours may be "
            "represented as a single grouped alert episode."
        )