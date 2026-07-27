"""Public alert response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.schemas.common import (
    AQICategory,
    AlertLevel,
    FreshnessResponse,
    PublicSchema,
)


class AlertEpisodeResponse(PublicSchema):
    """One continuous forecast alert episode."""

    alert_episode_id: str

    start_time_utc: datetime
    end_time_utc: datetime

    duration_hours: int = Field(
        ge=1,
    )

    start_horizon: int = Field(
        ge=1,
        le=72,
    )

    end_horizon: int = Field(
        ge=1,
        le=72,
    )

    maximum_aqi: int = Field(
        ge=0,
    )

    maximum_category: AQICategory
    maximum_alert_level: AlertLevel

    peak_time_utc: datetime
    alert_basis: str

    sensitive_groups_affected: bool
    general_population_affected: bool
    hazardous: bool

    summary_message: str
    recommended_action: str


class AlertEpisodeCollectionResponse(PublicSchema):
    """Collection of forecast alert episodes."""

    pipeline_run_id: str
    generated_at_utc: datetime
    freshness: FreshnessResponse

    episode_count: int = Field(
        ge=0,
    )

    episodes: list[AlertEpisodeResponse]


class ActiveAlertEpisodeResponse(
    AlertEpisodeResponse
):
    """Alert episode classified relative to current UTC."""

    currently_active: bool
    upcoming: bool


class ActiveAlertsResponse(PublicSchema):
    """Current and upcoming forecast alert episodes."""

    pipeline_run_id: str
    checked_at_utc: datetime

    current_count: int = Field(
        ge=0,
    )

    upcoming_count: int = Field(
        ge=0,
    )

    episodes: list[ActiveAlertEpisodeResponse]