"""FastAPI dependencies shared by route modules."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.api.config import (
    APISettings,
    get_api_settings,
)
from app.api.services.artifact_repository import (
    ArtifactBundle,
    ArtifactRepository,
)


def get_artifact_repository(
    request: Request,
) -> ArtifactRepository:
    """Return the repository initialized during application lifespan."""

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
    """Load the latest validated artifact bundle."""

    return repository.load_latest()


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