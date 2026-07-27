"""FastAPI dependencies shared by route modules."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.api.config import (
    APISettings,
    get_api_settings,
)
from app.api.errors import APIServiceError
from app.api.schemas.common import (
    FreshnessStatus,
)
from app.api.services.artifact_repository import (
    ArtifactBundle,
    ArtifactRepository,
)


def get_artifact_repository(
    request: Request,
) -> ArtifactRepository:
    """Return the repository created during application startup."""

    repository = getattr(
        request.app.state,
        "artifact_repository",
        None,
    )

    if not isinstance(
        repository,
        ArtifactRepository,
    ):
        raise RuntimeError(
            "Artifact repository is not initialized."
        )

    return repository


def get_latest_artifact_bundle(
    repository: Annotated[
        ArtifactRepository,
        Depends(get_artifact_repository),
    ],
) -> ArtifactBundle:
    """
    Return the latest validated and sufficiently fresh forecast.

    Readiness uses the repository directly so that it can report stale
    status without this dependency converting it into a data error.
    """

    bundle = repository.load_latest()

    if (
        bundle.freshness.status
        == FreshnessStatus.STALE
    ):
        raise APIServiceError(
            status_code=503,
            code="FORECAST_STALE",
            message=(
                "The latest validated forecast is stale "
                "and cannot be served as current data."
            ),
            details={
                "generated_at_utc": (
                    bundle.generated_at_utc.isoformat()
                ),
                "age_hours": (
                    bundle.freshness.age_hours
                ),
            },
        )

    return bundle


SettingsDependency = Annotated[
    APISettings,
    Depends(get_api_settings),
]

RepositoryDependency = Annotated[
    ArtifactRepository,
    Depends(get_artifact_repository),
]

ArtifactBundleDependency = Annotated[
    ArtifactBundle,
    Depends(get_latest_artifact_bundle),
]