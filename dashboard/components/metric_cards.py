"""Primary forecast metric cards."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from dashboard.utils.formatting import (
    format_aqi,
    format_pm25,
    format_timestamp,
)


def render_metric_cards(
    *,
    summary: dict[str, Any],
    forecast_df: pd.DataFrame,
    timezone_name: str,
) -> None:
    """Render the four most useful forecast summary metrics."""

    if forecast_df.empty:
        return

    first_row = forecast_df.iloc[0]

    active_alert_hours = int(
        summary.get(
            "active_alert_hours",
            0,
        )
    )

    metric_columns = st.columns(4)

    with metric_columns[0]:
        st.metric(
            "Current forecast PM2.5",
            format_pm25(
                first_row.get(
                    "predicted_pm25_ug_m3"
                )
            ),
            help=format_timestamp(
                first_row.get(
                    "target_time_utc"
                ),
                timezone_name=timezone_name,
            ),
        )

        st.caption(
            str(
                first_row.get(
                    "indicative_hourly_aqi_category",
                    "Not available",
                )
            )
        )

    with metric_columns[1]:
        st.metric(
            "Peak forecast PM2.5",
            format_pm25(
                summary.get(
                    "maximum_predicted_pm25_ug_m3"
                )
            ),
            help=format_timestamp(
                summary.get(
                    "peak_pm25_time_utc"
                ),
                timezone_name=timezone_name,
            ),
        )

        st.caption(
            "Maximum in selected range"
        )

    with metric_columns[2]:
        worst_aqi = (
            summary.get(
                "maximum_rolling_24h_aqi"
            )
            or summary.get(
                "maximum_indicative_hourly_aqi"
            )
        )

        worst_category = str(
            summary.get(
                "worst_aqi_category",
                "Not available",
            )
        )

        st.metric(
            "Worst forecast AQI",
            format_aqi(worst_aqi),
            help=worst_category,
        )

        st.caption(
            worst_category
        )

    with metric_columns[3]:
        st.metric(
            "Alert hours",
            str(active_alert_hours),
            help=(
                f"{summary.get('alert_episode_count', 0)} "
                "grouped alert episode(s)"
            ),
        )

        st.caption(
            "None expected"
            if active_alert_hours == 0
            else "Review alert timeline"
        )