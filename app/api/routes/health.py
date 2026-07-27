"""Liveness and readiness endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.dependencies import (
    RepositoryDependency,
    SettingsDependency,
)
from app.api.schemas.health import (
    LivenessResponse,
    ReadinessResponse,
)
from app.api.services.readiness_service import (
    ReadinessService,
)

router = APIRouter(
    prefix="/health",
    tags=["Health"],
)


@router.get(
    "/live",
    response_model=LivenessResponse,
    summary="Check service liveness",
)
def get_liveness(
    settings: SettingsDependency,
) -> LivenessResponse:
    """Confirm that the FastAPI process is running."""

    return LivenessResponse(
        status="ALIVE",
        service=settings.application_name,
        version=settings.application_version,
        timestamp_utc=datetime.now(
            timezone.utc
        ),
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={
        503: {
            "description": (
                "Forecast data is unavailable, "
                "invalid, or stale."
            )
        }
    },
    summary="Check forecast readiness",
)
def get_readiness(
    settings: SettingsDependency,
    repository: RepositoryDependency,
) -> ReadinessResponse | JSONResponse:
    """Evaluate artifact validity and freshness."""

    readiness = ReadinessService(
        settings=settings,
        repository=repository,
    ).evaluate()

    if readiness.status in {
        "NOT_READY",
        "STALE_FORECAST",
        "INVALID_ARTIFACTS",
    }:
        return JSONResponse(
            status_code=503,
            content=readiness.model_dump(
                mode="json"
            ),
        )

    return readiness