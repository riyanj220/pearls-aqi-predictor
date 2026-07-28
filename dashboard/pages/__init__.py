"""Streamlit dashboard page exports."""

from dashboard.pages.alerts import (
    render_alerts_page,
)
from dashboard.pages.forecast import (
    render_forecast_page,
)
from dashboard.pages.system_status import (
    render_system_status_page,
)

__all__ = [
    "render_alerts_page",
    "render_forecast_page",
    "render_system_status_page",
]