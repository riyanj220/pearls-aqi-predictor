"""Streamlit application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


st.set_page_config(
    page_title="Pearls AQI Predictor",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)


st.markdown(
    """
    <style>
        .block-container {
            max-width: 1500px;
            padding-top: 1.5rem;
            padding-bottom: 3rem;
        }

        [data-testid="stMetric"] {
            min-height: 118px;
            border: 1px solid rgba(128, 128, 128, 0.20);
            border-radius: 0.75rem;
            padding: 0.9rem;
            background: rgba(128, 128, 128, 0.04);
        }

        [data-testid="stMetricValue"] {
            font-size: 1.65rem;
            line-height: 1.2;
        }

        [data-testid="stMetricLabel"] {
            font-weight: 600;
            white-space: normal;
        }

        div[data-testid="stAlert"] {
            border-radius: 0.75rem;
        }

        .stPlotlyChart {
            border: 1px solid rgba(128, 128, 128, 0.14);
            border-radius: 0.75rem;
            padding: 0.35rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


from dashboard.pages import (
    render_alerts_page,
    render_forecast_page,
    render_system_status_page,
)


forecast_page = st.Page(
    render_forecast_page,
    title="Forecast",
    icon=":material/air:",
    default=True,
)

alerts_page = st.Page(
    render_alerts_page,
    title="Alerts",
    icon=":material/notifications_active:",
)

system_status_page = st.Page(
    render_system_status_page,
    title="System Status",
    icon=":material/monitor_heart:",
)

navigation = st.navigation(
    {
        "Dashboard": [
            forecast_page,
            alerts_page,
        ],
        "Operations": [
            system_status_page,
        ],
    }
)

navigation.run()