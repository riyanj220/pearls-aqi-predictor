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
from app.api.schemas.common import (
    AlertLevel,
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
    summary="Get forecast alert episodes",
)
def get_alert_episodes(
    settings: SettingsDependency,
    bundle: ArtifactBundleDependency,
    minimum_level: AlertLevel | None = Query(
        default=None,
    ),
    hazardous_only: bool = Query(
        default=False,
    ),
) -> AlertEpisodeCollectionResponse:
    """Return alert episodes matching optional severity filters."""

    return AlertService(
        settings=settings
    ).build_collection(
        bundle=bundle,
        minimum_level=minimum_level,
        hazardous_only=hazardous_only,
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
    minimum_level: AlertLevel | None = Query(
        default=None,
    ),
    hazardous_only: bool = Query(
        default=False,
    ),
) -> ActiveAlertsResponse:
    """Return current or upcoming episodes matching filters."""

    return AlertService(
        settings=settings
    ).build_active_collection(
        bundle=bundle,
        include_upcoming=include_upcoming,
        minimum_level=minimum_level,
        hazardous_only=hazardous_only,
    )