"""Dashboard service exports."""

from dashboard.services.api_client import (
    APIResult,
    DashboardAPIConnectionError,
    DashboardAPIContractError,
    DashboardAPIError,
    DashboardAPIResponseError,
    DashboardAPITimeoutError,
    FastAPIClient,
    cached_active_alerts,
    cached_alerts,
    cached_forecast,
    cached_liveness,
    cached_metadata,
    cached_pipeline_status,
    cached_readiness,
    clear_dashboard_api_cache,
    get_cached_api_client,
)

__all__ = [
    "APIResult",
    "DashboardAPIConnectionError",
    "DashboardAPIContractError",
    "DashboardAPIError",
    "DashboardAPIResponseError",
    "DashboardAPITimeoutError",
    "FastAPIClient",
    "cached_active_alerts",
    "cached_alerts",
    "cached_forecast",
    "cached_liveness",
    "cached_metadata",
    "cached_pipeline_status",
    "cached_readiness",
    "clear_dashboard_api_cache",
    "get_cached_api_client",
]
