"""Public metadata and pipeline-status endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.dependencies import (
    ArtifactBundleDependency,
    SettingsDependency,
)
from app.api.schemas.metadata import (
    MetadataResponse,
    PipelineStatusResponse,
)
from app.api.services.metadata_service import (
    MetadataService,
)

router = APIRouter(
    tags=["Metadata and operations"],
)


@router.get(
    "/metadata",
    response_model=MetadataResponse,
    summary="Get public project metadata",
)
def get_metadata(
    settings: SettingsDependency,
    bundle: ArtifactBundleDependency,
) -> MetadataResponse:
    """Return public-safe location, source, and AQI metadata."""

    return MetadataService(
        settings=settings
    ).build_metadata(
        bundle
    )


@router.get(
    "/pipeline/status",
    response_model=PipelineStatusResponse,
    summary="Get the latest pipeline status",
)
def get_pipeline_status(
    settings: SettingsDependency,
    bundle: ArtifactBundleDependency,
) -> PipelineStatusResponse:
    """Return read-only Phase 5 and Phase 6 status."""

    return MetadataService(
        settings=settings
    ).build_pipeline_status(
        bundle
    )