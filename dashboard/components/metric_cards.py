"""Top-level forecast metric cards."""

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
    """Render the primary dashboard summary metrics."""

    if forecast_df.empty:
        return

    first_row = forecast_df.iloc[0]

    first_row_columns = st.columns(3)

    with first_row_columns[0]:
        st.metric(
            "First forecast-hour PM2.5",
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

    with first_row_columns[1]:
        st.metric(
            "Indicative hourly AQI",
            format_aqi(
                first_row.get(
                    "indicative_hourly_pm25_aqi"
                )
            ),
            help=str(
                first_row.get(
                    "indicative_hourly_aqi_category",
                    "Not available",
                )
            ),
        )

    with first_row_columns[2]:
        st.metric(
            "Rolling 24-hour AQI",
            format_aqi(
                first_row.get(
                    "rolling_24h_pm25_aqi"
                )
            ),
            help=str(
                first_row.get(
                    "rolling_24h_aqi_category",
                    "Not available",
                )
            ),
        )

    summary_columns = st.columns(3)

    with summary_columns[0]:
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

    with summary_columns[1]:
        st.metric(
            "Worst forecast AQI",
            format_aqi(
                summary.get(
                    "maximum_rolling_24h_aqi"
                )
                or summary.get(
                    "maximum_indicative_hourly_aqi"
                )
            ),
            help=str(
                summary.get(
                    "worst_aqi_category",
                    "Not available",
                )
            ),
        )

    with summary_columns[2]:
        active_alert_hours = int(
            summary.get(
                "active_alert_hours",
                0,
            )
        )

        st.metric(
            "Active alert hours",
            str(active_alert_hours),
            help=(
                f"{summary.get('alert_episode_count', 0)} "
                "grouped alert episode(s)"
            ),
        )