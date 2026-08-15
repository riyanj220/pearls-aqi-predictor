"""Dashboard hero and status presentation."""

from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.utils.constants import (
    AQI_COLOR_FALLBACKS,
)
from dashboard.utils.formatting import (
    format_aqi,
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
        return (
            status,
            f"{round(age * 60)} min ago",
        )

    return (
        status,
        f"{age:.1f}h ago",
    )


def _safe_category_color(
    category: str,
) -> str:
    """Resolve the AQI category accent color."""

    return AQI_COLOR_FALLBACKS.get(
        category,
        "#60A5FA",
    )


def render_dashboard_header(
    *,
    title: str,
    forecast_payload: dict[str, Any],
    readiness_payload: dict[str, Any],
    forecast_df: pd.DataFrame,
    timezone_name: str,
) -> None:
    """Render a concise product-style forecast header."""

    location = forecast_payload.get(
        "location",
        {},
    )

    location_name = str(
        location.get(
            "name",
            "Zafar Memon DHA",
        )
    )

    readiness_status = (
        _display_readiness_status(
            str(
                readiness_payload.get(
                    "status",
                    "UNKNOWN",
                )
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

    if forecast_df.empty:
        current_aqi = "—"
        category = "Not available"
        health_message = (
            "Forecast information is currently unavailable."
        )
    else:
        first_row = forecast_df.iloc[0]

        current_aqi = format_aqi(
            first_row.get(
                "indicative_hourly_pm25_aqi"
            )
        )

        category = str(
            first_row.get(
                "indicative_hourly_aqi_category",
                "Not available",
            )
        )

        health_message = str(
            first_row.get(
                "health_message",
                "Air-quality outlook available.",
            )
        )

    category_color = (
        _safe_category_color(category)
    )

    live_status = (
        readiness_status == "Ready"
        and freshness_value.lower() == "fresh"
    )

    live_label = (
        "LIVE"
        if live_status
        else readiness_status.upper()
    )

    st.html(
        f"""
        <div>
            <div class="section-kicker">
                Environmental forecast
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
                        {escape(title)}
                    </h1>
                    <div style="
                        color:#8d99aa;
                        margin-top:0.35rem;
                        font-size:0.92rem;
                    ">
                        72-hour PM2.5-based air-quality outlook
                    </div>
                </div>
            </div>
        </div>

        <div
            class="aqi-hero"
            style="
                --hero-accent:{category_color};
                --category-color:{category_color};
            "
        >
            <div class="aqi-hero-top">
                <div>
                    <div class="aqi-hero-eyebrow">
                        Current forecast outlook
                    </div>
                    <div class="aqi-hero-title">
                        {escape(location_name)} · Karachi
                    </div>
                </div>

                <div class="aqi-live-pill">
                    <span class="aqi-live-dot"></span>
                    {escape(live_label)}
                </div>
            </div>

            <div class="aqi-hero-main">
                <div>
                    <div class="aqi-value">
                        {escape(current_aqi)}
                    </div>
                    <div class="aqi-value-label">
                        Indicative AQI
                    </div>
                </div>

                <div class="aqi-category">
                    {escape(category)}
                </div>
            </div>

            <p class="aqi-hero-message">
                {escape(health_message)}
            </p>
        </div>

        <div class="status-strip">
            <div class="status-chip">
                <span class="status-dot success"></span>
                API {escape(readiness_status)}
            </div>

            <div class="status-chip">
                <span class="status-dot success"></span>
                Forecast {escape(freshness_value)}
            </div>

            <div class="status-chip">
                72-hour horizon
            </div>

            <div class="status-chip">
                Updated {escape(freshness_caption)}
            </div>

            <div class="status-chip">
                Generated {escape(generated_time)}
            </div>
        </div>
        """
    )