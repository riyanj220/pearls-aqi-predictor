"""Interactive Plotly charts for the forecast page."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from dashboard.utils.constants import (
    AQI_COLOR_FALLBACKS,
)


PLOT_CONFIG = {
    "displaylogo": False,
    "scrollZoom": False,
    "responsive": True,
}


def build_pm25_chart(
    forecast_df: pd.DataFrame,
) -> go.Figure:
    """Build the hourly PM2.5 forecast chart."""

    figure = px.line(
        forecast_df,
        x="display_time",
        y="predicted_pm25_ug_m3",
        markers=True,
        custom_data=[
            "forecast_horizon_hours",
            "indicative_hourly_aqi_category",
        ],
    )

    figure.update_traces(
        line={
            "width": 3,
        },
        marker={
            "size": 6,
        },
        hovertemplate=(
            "<b>%{x}</b><br>"
            "PM2.5: %{y:.1f} µg/m³<br>"
            "Horizon: %{customdata[0]} hours<br>"
            "AQI category: %{customdata[1]}"
            "<extra></extra>"
        ),
        name="Predicted PM2.5",
    )

    if not forecast_df.empty:
        peak_index = forecast_df[
            "predicted_pm25_ug_m3"
        ].idxmax()

        peak_row = forecast_df.loc[
            peak_index
        ]

        figure.add_annotation(
            x=peak_row["display_time"],
            y=peak_row[
                "predicted_pm25_ug_m3"
            ],
            text=(
                "Peak "
                f"{peak_row['predicted_pm25_ug_m3']:.1f}"
            ),
            showarrow=True,
            arrowhead=2,
            yshift=14,
        )

    figure.update_layout(
        title="Hourly PM2.5 forecast",
        xaxis_title="Forecast time",
        yaxis_title="PM2.5 (µg/m³)",
        hovermode="x unified",
        margin={
            "l": 20,
            "r": 20,
            "t": 60,
            "b": 20,
        },
        height=430,
    )

    return figure


def _add_aqi_bands(
    figure: go.Figure,
) -> None:
    """Add standard AQI category background bands."""

    bands = [
        (0, 50, "Good"),
        (51, 100, "Moderate"),
        (
            101,
            150,
            "Unhealthy for Sensitive Groups",
        ),
        (151, 200, "Unhealthy"),
        (201, 300, "Very Unhealthy"),
        (301, 500, "Hazardous"),
    ]

    for lower, upper, category in bands:
        figure.add_hrect(
            y0=lower,
            y1=upper,
            fillcolor=(
                AQI_COLOR_FALLBACKS[
                    category
                ]
            ),
            opacity=0.09,
            line_width=0,
            layer="below",
        )


def build_indicative_aqi_chart(
    forecast_df: pd.DataFrame,
) -> go.Figure:
    """Build the indicative hourly AQI chart."""

    marker_colors = forecast_df[
        "indicative_hourly_aqi_color_hex"
    ].fillna(
        forecast_df[
            "indicative_hourly_aqi_category"
        ].map(AQI_COLOR_FALLBACKS)
    )

    figure = go.Figure()

    figure.add_trace(
        go.Scatter(
            x=forecast_df["display_time"],
            y=forecast_df[
                "indicative_hourly_pm25_aqi"
            ],
            mode="lines+markers",
            line={
                "width": 2,
            },
            marker={
                "size": 7,
                "color": marker_colors,
                "line": {
                    "width": 1,
                },
            },
            customdata=forecast_df[
                [
                    "forecast_horizon_hours",
                    "indicative_hourly_aqi_category",
                    "predicted_pm25_ug_m3",
                    "alert_level",
                ]
            ],
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Indicative AQI: %{y}<br>"
                "Horizon: %{customdata[0]} hours<br>"
                "Category: %{customdata[1]}<br>"
                "PM2.5: %{customdata[2]:.1f} µg/m³<br>"
                "Alert: %{customdata[3]}"
                "<extra></extra>"
            ),
            name="Indicative hourly AQI",
        )
    )

    _add_aqi_bands(figure)

    figure.update_layout(
        title=(
            "Indicative hourly PM2.5-based AQI"
        ),
        xaxis_title="Forecast time",
        yaxis_title="AQI",
        hovermode="x unified",
        height=430,
        margin={
            "l": 20,
            "r": 20,
            "t": 60,
            "b": 20,
        },
    )

    return figure


def build_rolling_aqi_chart(
    forecast_df: pd.DataFrame,
) -> go.Figure | None:
    """Build the complete rolling 24-hour AQI chart."""

    rolling_df = forecast_df.loc[
        forecast_df[
            "rolling_24h_pm25_is_complete"
        ].astype(bool)
        & forecast_df[
            "rolling_24h_pm25_aqi"
        ].notna()
    ].copy()

    if rolling_df.empty:
        return None

    figure = go.Figure()

    figure.add_trace(
        go.Scatter(
            x=rolling_df["display_time"],
            y=rolling_df[
                "rolling_24h_pm25_aqi"
            ],
            mode="lines+markers",
            line={
                "width": 3,
            },
            marker={
                "size": 6,
                "color": rolling_df[
                    "rolling_24h_aqi_color_hex"
                ],
            },
            customdata=rolling_df[
                [
                    "rolling_24h_pm25_ug_m3",
                    "rolling_24h_aqi_category",
                    "rolling_observed_hour_count",
                    "rolling_predicted_hour_count",
                ]
            ],
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Rolling AQI: %{y}<br>"
                "Rolling PM2.5: %{customdata[0]:.1f} µg/m³<br>"
                "Category: %{customdata[1]}<br>"
                "Observed hours: %{customdata[2]}<br>"
                "Predicted hours: %{customdata[3]}"
                "<extra></extra>"
            ),
            name="Rolling 24-hour AQI",
        )
    )

    _add_aqi_bands(figure)

    figure.update_layout(
        title="Rolling 24-hour PM2.5-based AQI",
        xaxis_title="Forecast time",
        yaxis_title="AQI",
        hovermode="x unified",
        height=430,
        margin={
            "l": 20,
            "r": 20,
            "t": 60,
            "b": 20,
        },
    )

    return figure


def build_category_timeline(
    forecast_df: pd.DataFrame,
) -> go.Figure:
    """Build a compact category strip by forecast hour."""

    timeline_df = forecast_df.copy()

    timeline_df["timeline_value"] = 1

    color_mapping = {
        category: (
            timeline_df.loc[
                timeline_df[
                    "alert_trigger_category"
                ].eq(category),
                "rolling_24h_aqi_color_hex",
            ].dropna().iloc[0]
            if (
                timeline_df[
                    "alert_trigger_category"
                ].eq(category)
                & timeline_df[
                    "rolling_24h_aqi_color_hex"
                ].notna()
            ).any()
            else AQI_COLOR_FALLBACKS.get(
                category,
                "#64748B",
            )
        )
        for category in timeline_df[
            "alert_trigger_category"
        ].dropna().unique()
    }

    figure = px.bar(
        timeline_df,
        x="display_time",
        y="timeline_value",
        color="alert_trigger_category",
        color_discrete_map=color_mapping,
        custom_data=[
            "forecast_horizon_hours",
            "alert_level",
            "alert_trigger_aqi",
        ],
    )

    figure.update_traces(
        hovertemplate=(
            "<b>%{x}</b><br>"
            "Category: %{fullData.name}<br>"
            "Horizon: %{customdata[0]} hours<br>"
            "Alert level: %{customdata[1]}<br>"
            "AQI: %{customdata[2]}"
            "<extra></extra>"
        )
    )

    figure.update_layout(
        title="AQI category timeline",
        xaxis_title="Forecast time",
        yaxis_visible=False,
        barmode="stack",
        height=240,
        legend_title="AQI category",
        margin={
            "l": 20,
            "r": 20,
            "t": 60,
            "b": 20,
        },
    )

    return figure