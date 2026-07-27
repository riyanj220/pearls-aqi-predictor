"""Public metadata and pipeline-status schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.schemas.common import (
    FreshnessResponse,
    LocationResponse,
    PublicSchema,
)


class AQIInterpretationResponse(PublicSchema):
    """Public explanation of the two AQI interpretations."""

    indicative_hourly: str
    rolling_24h: str


class MetadataResponse(PublicSchema):
    """Public-safe project and data-source metadata."""

    project_name: str
    application_description: str

    location: LocationResponse

    pollution_source: str
    original_sensor_provider: str
    weather_sources: list[str]

    pollutant: str
    concentration_unit: str

    forecast_horizon_hours: int = Field(
        ge=1,
    )

    internal_timezone: str
    aqi_standard_name: str
    aqi_standard_version: str

    aqi_interpretation: (
        AQIInterpretationResponse
    )

    latest_phase_6_run_id: str
    latest_phase_5_run_id: str

    processing_timestamp_utc: datetime

    freshness: FreshnessResponse

    known_limitations: list[str]


class PipelineStatusResponse(PublicSchema):
    """Operational status of the latest saved pipeline."""

    phase_5_run_id: str
    phase_5_status: str

    phase_6_run_id: str
    phase_6_status: str

    generated_at_utc: datetime

    artifact_consistency_passed: bool

    forecast_row_count: int = Field(
        ge=0,
    )

    prediction_count: int = Field(
        ge=0,
    )

    active_alert_count: int = Field(
        ge=0,
    )

    alert_episode_count: int = Field(
        ge=0,
    )

    freshness: FreshnessResponse
    limitations: list[str]