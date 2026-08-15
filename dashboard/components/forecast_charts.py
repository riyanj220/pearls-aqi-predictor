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
    "modeBarButtonsToRemove": [
        "lasso2d",
        "select2d",
    ],
}


PLOT_BACKGROUND = "rgba(0,0,0,0)"
GRID_COLOR = "rgba(148,163,184,0.16)"
TEXT_COLOR = "#CBD5E1"
MUTED_TEXT_COLOR = "#94A3B8"
PRIMARY_LINE = "#7DD3FC"


def _apply_common_layout(
    figure: go.Figure,
    *,
    title: str,
    xaxis_title: str,
    yaxis_title: str,
    height: int = 400,
) -> None:
    """Apply the shared visual language to Plotly charts."""

    figure.update_layout(
        title={
            "text": title,
            "x": 0.01,
            "xanchor": "left",
            "font": {
                "size": 16,
                "color": "#F8FAFC",
            },
        },
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
        hovermode="x unified",
        height=height,
        paper_bgcolor=PLOT_BACKGROUND,
        plot_bgcolor=PLOT_BACKGROUND,
        font={
            "color": TEXT_COLOR,
            "size": 12,
        },
        margin={
            "l": 28,
            "r": 24,
            "t": 58,
            "b": 24,
        },
        legend={
            "title": None,
            "bgcolor": "rgba(0,0,0,0)",
        },
        hoverlabel={
            "bgcolor": "#111827",
            "bordercolor": "rgba(148,163,184,0.20)",
            "font": {
                "color": "#F8FAFC",
            },
        },
    )

    figure.update_xaxes(
        showgrid=False,
        zeroline=False,
        linecolor="rgba(148,163,184,0.10)",
        tickfont={
            "color": MUTED_TEXT_COLOR,
        },
        title_font={
            "color": MUTED_TEXT_COLOR,
        },
    )

    figure.update_yaxes(
        gridcolor=GRID_COLOR,
        zeroline=False,
        linecolor="rgba(148,163,184,0.10)",
        tickfont={
            "color": MUTED_TEXT_COLOR,
        },
        title_font={
            "color": MUTED_TEXT_COLOR,
        },
    )


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
            "color": PRIMARY_LINE,
        },
        marker={
            "size": 6,
            "color": PRIMARY_LINE,
            "line": {
                "width": 0,
            },
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
            arrowcolor="#64748B",
            font={
                "color": "#E2E8F0",
                "size": 11,
            },
            bgcolor="rgba(15,23,42,0.85)",
            borderpad=5,
            yshift=14,
        )

    _apply_common_layout(
        figure,
        title="Hourly PM2.5 forecast",
        xaxis_title="Forecast time",
        yaxis_title="PM2.5 (µg/m³)",
        height=410,
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
            opacity=0.075,
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
                "width": 2.3,
                "color": PRIMARY_LINE,
            },
            marker={
                "size": 7,
                "color": marker_colors,
                "line": {
                    "width": 1,
                    "color": "#0B0F15",
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

    _apply_common_layout(
        figure,
        title="Indicative hourly PM2.5-based AQI",
        xaxis_title="Forecast time",
        yaxis_title="AQI",
        height=410,
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
                "width": 2.7,
                "color": PRIMARY_LINE,
            },
            marker={
                "size": 6,
                "color": rolling_df[
                    "rolling_24h_aqi_color_hex"
                ],
                "line": {
                    "width": 1,
                    "color": "#0B0F15",
                },
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

    _apply_common_layout(
        figure,
        title="Rolling 24-hour PM2.5-based AQI",
        xaxis_title="Forecast time",
        yaxis_title="AQI",
        height=410,
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
        marker_line_width=0,
        opacity=0.84,
        hovertemplate=(
            "<b>%{x}</b><br>"
            "Category: %{fullData.name}<br>"
            "Horizon: %{customdata[0]} hours<br>"
            "Alert level: %{customdata[1]}<br>"
            "AQI: %{customdata[2]}"
            "<extra></extra>"
        ),
    )

    _apply_common_layout(
        figure,
        title="AQI category timeline",
        xaxis_title="Forecast time",
        yaxis_title="",
        height=230,
    )

    figure.update_yaxes(
        visible=False,
    )

    figure.update_layout(
        bargap=0.14,
        legend={
            "title": {
                "text": "AQI category",
            },
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.01,
            "xanchor": "right",
            "x": 1,
        },
    )

    return figure