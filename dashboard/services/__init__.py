"""Dashboard service exports."""

from dashboard.services.api_client import (
    APIResult,
    DashboardAPIConnectionError,
    DashboardAPIContractError,
    DashboardAPIError,
    DashboardAPIResponseError,
    DashboardAPITimeoutError,
    FastAPIClient,
    cached_forecast,
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
    "cached_forecast",
    "cached_readiness",
    "clear_dashboard_api_cache",
    "get_cached_api_client",
]