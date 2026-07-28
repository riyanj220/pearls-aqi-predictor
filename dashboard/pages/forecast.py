"""Primary professional forecast dashboard page."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.components import (
    PLOT_CONFIG,
    build_category_timeline,
    build_indicative_aqi_chart,
    build_pm25_chart,
    build_rolling_aqi_chart,
    render_api_error,
    render_dashboard_header,
    render_empty_forecast,
    render_metric_cards,
    render_no_alerts,
    render_no_rolling_aqi,
    render_stale_warning,
)
from dashboard.config import (
    get_dashboard_settings,
)
from dashboard.services.api_client import (
    DashboardAPIError,
    cached_forecast,
    cached_readiness,
    clear_dashboard_api_cache,
)
from dashboard.utils.constants import (
    ALERT_LEVELS,
    AQI_CATEGORIES,
    FORECAST_RANGES,
    SUPPORTED_TIMEZONES,
)
from dashboard.utils.data import (
    DashboardDataError,
    add_display_timezone,
    filter_hourly_forecast,
    prepare_hourly_forecast,
)
from dashboard.utils.formatting import (
    format_aqi,
    format_boolean_status,
    format_pm25,
    format_timestamp,
    utc_now,
)


def _render_sidebar() -> dict[str, Any]:
    """Render and return forecast display controls."""

    settings = get_dashboard_settings()

    st.sidebar.header(
        "Forecast controls"
    )

    range_hours = st.sidebar.selectbox(
        "Forecast range",
        options=FORECAST_RANGES,
        index=1,
        format_func=lambda value: (
            f"Next {value} hours"
        ),
    )

    timezone_label = st.sidebar.selectbox(
        "Display timezone",
        options=list(
            SUPPORTED_TIMEZONES.keys()
        ),
        index=0,
    )

    categories = st.sidebar.multiselect(
        "AQI categories",
        options=AQI_CATEGORIES,
        default=[],
    )

    alert_levels = st.sidebar.multiselect(
        "Alert levels",
        options=ALERT_LEVELS,
        default=[],
    )

    alerts_only = st.sidebar.toggle(
        "Show alert hours only",
        value=False,
    )

    if st.sidebar.button(
        "Refresh dashboard",
        width='stretch',
        type="primary",
    ):
        clear_dashboard_api_cache()

        st.session_state[
            "last_manual_refresh_utc"
        ] = utc_now()

        st.rerun()

    st.sidebar.divider()

    st.sidebar.caption(
        f"API: {settings.fastapi_base_url}"
    )

    last_refresh = st.session_state.get(
        "last_manual_refresh_utc"
    )

    if isinstance(
        last_refresh,
        datetime,
    ):
        st.sidebar.caption(
            "Last manual refresh: "
            + format_timestamp(
                last_refresh,
                timezone_name=(
                    SUPPORTED_TIMEZONES[
                        timezone_label
                    ]
                ),
            )
        )

    return {
        "range_hours": int(
            range_hours
        ),
        "timezone_name": (
            SUPPORTED_TIMEZONES[
                timezone_label
            ]
        ),
        "categories": list(categories),
        "alert_levels": list(
            alert_levels
        ),
        "alerts_only": bool(
            alerts_only
        ),
    }


def _render_selected_hour(
    *,
    forecast_df: pd.DataFrame,
    timezone_name: str,
) -> None:
    """Render details for one selected forecast hour."""

    st.subheader(
        "Forecast-hour details"
    )

    horizon_options = forecast_df[
        "forecast_horizon_hours"
    ].astype(int).tolist()

    selected_horizon = st.selectbox(
        "Select a forecast hour",
        options=horizon_options,
        format_func=lambda horizon: (
            f"Hour {horizon}"
        ),
    )

    selected_row = forecast_df.loc[
        forecast_df[
            "forecast_horizon_hours"
        ].eq(selected_horizon)
    ].iloc[0]

    detail_columns = st.columns(4)

    with detail_columns[0]:
        st.metric(
            "Target time",
            format_timestamp(
                selected_row[
                    "target_time_utc"
                ],
                timezone_name=timezone_name,
            ),
        )

    with detail_columns[1]:
        st.metric(
            "PM2.5",
            format_pm25(
                selected_row[
                    "predicted_pm25_ug_m3"
                ]
            ),
        )

    with detail_columns[2]:
        st.metric(
            "Indicative AQI",
            format_aqi(
                selected_row[
                    "indicative_hourly_pm25_aqi"
                ]
            ),
        )

    with detail_columns[3]:
        st.metric(
            "Rolling AQI",
            format_aqi(
                selected_row[
                    "rolling_24h_pm25_aqi"
                ]
            ),
        )

    guidance_columns = st.columns(2)

    with guidance_columns[0]:
        st.markdown(
            "**AQI interpretation**"
        )

        st.write(
            "Indicative category: "
            f"**{selected_row['indicative_hourly_aqi_category']}**"
        )

        st.write(
            "Rolling category: "
            f"**{selected_row['rolling_24h_aqi_category'] or 'Not available'}**"
        )

        st.write(
            "Alert level: "
            f"**{selected_row['alert_level']}**"
        )

        st.write(
            "Alert basis: "
            f"`{selected_row['alert_basis']}`"
        )

    with guidance_columns[1]:
        st.markdown(
            "**Health guidance**"
        )

        st.write(
            selected_row[
                "health_message"
            ]
        )

        st.info(
            selected_row[
                "recommended_action"
            ]
        )

        st.caption(
            "Official local guidance and professional "
            "medical advice take priority."
        )


def _render_hourly_table(
    *,
    forecast_df: pd.DataFrame,
    timezone_name: str,
) -> None:
    """Render a clean hourly forecast table."""

    st.subheader(
        "Hourly forecast table"
    )

    table_df = forecast_df.copy()

    table_df["Forecast time"] = (
        table_df["target_time_utc"]
        .apply(
            lambda value: format_timestamp(
                value,
                timezone_name=timezone_name,
                include_timezone=True,
            )
        )
    )

    table_df["PM2.5"] = (
        table_df[
            "predicted_pm25_ug_m3"
        ].apply(format_pm25)
    )

    table_df["Indicative AQI"] = (
        table_df[
            "indicative_hourly_pm25_aqi"
        ].apply(format_aqi)
    )

    table_df["Rolling AQI"] = (
        table_df[
            "rolling_24h_pm25_aqi"
        ].apply(format_aqi)
    )

    table_df["Alert active"] = (
        table_df[
            "alert_is_active"
        ].apply(
            format_boolean_status
        )
    )

    display_columns = {
        "forecast_horizon_hours": (
            "Horizon"
        ),
        "Forecast time": "Forecast time",
        "PM2.5": "PM2.5",
        "Indicative AQI": (
            "Indicative AQI"
        ),
        "indicative_hourly_aqi_category": (
            "Indicative category"
        ),
        "Rolling AQI": "Rolling AQI",
        "rolling_24h_aqi_category": (
            "Rolling category"
        ),
        "alert_level": "Alert level",
        "Alert active": "Alert active",
        "health_message": (
            "Health guidance"
        ),
    }

    final_table_df = (
        table_df[
            list(display_columns.keys())
        ]
        .rename(
            columns=display_columns
        )
    )

    st.dataframe(
        final_table_df,
        width="stretch",
        hide_index=True,
        height=480,
    )


def render_forecast_page() -> None:
    """Render the complete Forecast dashboard page."""

    settings = get_dashboard_settings()

    controls = _render_sidebar()

    try:
        with st.spinner(
            "Loading the latest forecast..."
        ):
            readiness_payload = (
                cached_readiness()
            )

            forecast_payload = (
                cached_forecast()
            )

            full_forecast_df = (
                prepare_hourly_forecast(
                    forecast_payload
                )
            )

    except (
        DashboardAPIError,
        DashboardDataError,
    ) as error:
        render_api_error(error)
        return

    render_dashboard_header(
        title=settings.dashboard_title,
        forecast_payload=forecast_payload,
        readiness_payload=(
            readiness_payload
        ),
        timezone_name=(
            controls["timezone_name"]
        ),
    )

    freshness = forecast_payload.get(
        "freshness",
        {},
    )

    if freshness.get(
        "status"
    ) == "STALE":
        render_stale_warning(
            age_hours=freshness.get(
                "age_hours"
            )
        )

    prepared_df = add_display_timezone(
        full_forecast_df,
        timezone_name=(
            controls["timezone_name"]
        ),
    )

    filtered_df = filter_hourly_forecast(
        prepared_df,
        maximum_horizon=(
            controls["range_hours"]
        ),
        categories=(
            controls["categories"]
        ),
        alert_levels=(
            controls["alert_levels"]
        ),
        alerts_only=(
            controls["alerts_only"]
        ),
    )

    if filtered_df.empty:
        render_empty_forecast()
        return

    render_metric_cards(
        summary=forecast_payload.get(
            "summary",
            {},
        ),
        forecast_df=filtered_df,
        timezone_name=(
            controls["timezone_name"]
        ),
    )

    if not filtered_df[
        "alert_is_active"
    ].astype(bool).any():
        render_no_alerts()

    st.divider()

    st.plotly_chart(
        build_pm25_chart(filtered_df),
        width="stretch",
        config=PLOT_CONFIG,
    )

    st.plotly_chart(
        build_indicative_aqi_chart(
            filtered_df
        ),
        width="stretch",
        config=PLOT_CONFIG,
    )

    st.caption(
        "Indicative AQI shows the expected air-quality category "
        "for each hourly PM2.5 prediction."
    )

    rolling_figure = (
        build_rolling_aqi_chart(
            filtered_df
        )
    )

    if rolling_figure is None:
        render_no_rolling_aqi()
    else:
        st.plotly_chart(
            rolling_figure,
            width="stretch",
            config=PLOT_CONFIG,
        )

        st.caption(
            "Rolling AQI summarizes the trailing 24-hour PM2.5 window."
        )

    st.plotly_chart(
        build_category_timeline(
            filtered_df
        ),
        width="stretch",
        config=PLOT_CONFIG,
    )

    st.divider()

    _render_selected_hour(
        forecast_df=filtered_df,
        timezone_name=(
            controls["timezone_name"]
        ),
    )

    st.divider()

    _render_hourly_table(
        forecast_df=filtered_df,
        timezone_name=(
            controls["timezone_name"]
        ),
    )

    st.divider()

    with st.expander(
        "Location and forecast methodology",
        expanded=False,
    ):
        location = forecast_payload.get(
            "location",
            {},
        )

        st.write(
            f"**Reference location:** "
            f"{location.get('name', 'Zafar Memon DHA')}"
        )

        st.write(
            f"**Coordinates:** "
            f"{location.get('latitude', 24.814741)}, "
            f"{location.get('longitude', 67.067062)}"
        )

        st.write(
            "**Scope:** One reference monitoring location, "
            "not all of Karachi."
        )

        st.write(
            "**Forecast source:** Pearls AQI Predictor FastAPI service"
        )