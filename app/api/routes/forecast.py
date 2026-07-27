"""Forecast retrieval endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.dependencies import (
    ArtifactBundleDependency,
    SettingsDependency,
)
from app.api.schemas.common import (
    AQICategory,
    AlertLevel,
)
from app.api.schemas.forecast import (
    CompleteForecastResponse,
    ForecastSummaryResponse,
    HourlyForecastResponse,
)
from app.api.services.forecast_service import (
    ForecastService,
)

router = APIRouter(
    prefix="/forecast",
    tags=["Forecast"],
)


@router.get(
    "",
    response_model=CompleteForecastResponse,
    summary="Get the complete 72-hour forecast",
)
def get_complete_forecast(
    settings: SettingsDependency,
    bundle: ArtifactBundleDependency,
) -> CompleteForecastResponse:
    """Return the complete dashboard-oriented forecast."""

    return ForecastService(
        settings=settings
    ).build_complete_forecast(
        bundle
    )


@router.get(
    "/hourly",
    response_model=HourlyForecastResponse,
    summary="Get filterable hourly forecasts",
)
def get_hourly_forecast(
    settings: SettingsDependency,
    bundle: ArtifactBundleDependency,
    minimum_horizon: int | None = Query(
        default=None,
        ge=1,
        le=72,
    ),
    maximum_horizon: int | None = Query(
        default=None,
        ge=1,
        le=72,
    ),
    category: AQICategory | None = Query(
        default=None,
    ),
    alert_level: AlertLevel | None = Query(
        default=None,
    ),
    alerts_only: bool = Query(
        default=False,
    ),
) -> HourlyForecastResponse:
    """Filter the 72-hour forecast by horizon, category, or alert."""

    return ForecastService(
        settings=settings
    ).filter_hourly(
        bundle=bundle,
        minimum_horizon=minimum_horizon,
        maximum_horizon=maximum_horizon,
        category=category,
        alert_level=alert_level,
        alerts_only=alerts_only,
    )


@router.get(
    "/summary",
    response_model=ForecastSummaryResponse,
    summary="Get the forecast summary",
)
def get_forecast_summary(
    settings: SettingsDependency,
    bundle: ArtifactBundleDependency,
) -> ForecastSummaryResponse:
    """Return a compact public forecast summary."""

    return ForecastService(
        settings=settings
    ).build_summary(
        bundle
    )