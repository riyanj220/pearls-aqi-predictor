"""Forecast alert endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.dependencies import (
    ArtifactBundleDependency,
    SettingsDependency,
)
from app.api.schemas.alerts import (
    ActiveAlertsResponse,
    AlertEpisodeCollectionResponse,
)
from app.api.services.alert_service import (
    AlertService,
)

router = APIRouter(
    prefix="/alerts",
    tags=["Alerts"],
)


@router.get(
    "",
    response_model=AlertEpisodeCollectionResponse,
    summary="Get all forecast alert episodes",
)
def get_alert_episodes(
    settings: SettingsDependency,
    bundle: ArtifactBundleDependency,
) -> AlertEpisodeCollectionResponse:
    """Return all grouped Phase 6 alert episodes."""

    return AlertService(
        settings=settings
    ).build_collection(
        bundle
    )


@router.get(
    "/active",
    response_model=ActiveAlertsResponse,
    summary="Get current and upcoming alert episodes",
)
def get_active_alerts(
    settings: SettingsDependency,
    bundle: ArtifactBundleDependency,
    include_upcoming: bool = Query(
        default=True,
    ),
) -> ActiveAlertsResponse:
    """Distinguish currently active and upcoming alerts."""

    return AlertService(
        settings=settings
    ).build_active_collection(
        bundle=bundle,
        include_upcoming=include_upcoming,
    )