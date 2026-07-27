"""Health and readiness response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.schemas.common import (
    FreshnessResponse,
    PublicSchema,
    ReadinessStatus,
)


class LivenessResponse(PublicSchema):
    """Response for the process liveness endpoint."""

    status: str = "ALIVE"
    service: str
    version: str
    timestamp_utc: datetime


class ReadinessResponse(PublicSchema):
    """Response for artifact and forecast readiness."""

    status: ReadinessStatus
    service: str
    version: str
    timestamp_utc: datetime

    forecast_available: bool
    artifacts_valid: bool

    pipeline_run_id: str | None = None
    forecast_rows: int | None = Field(
        default=None,
        ge=0,
    )

    freshness: FreshnessResponse | None = None

    limitations: list[str] = Field(
        default_factory=list
    )

    message: str