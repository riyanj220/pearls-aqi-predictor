"""Shared enums and schemas for the public API contract."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AQICategory(str, Enum):
    """Supported PM2.5 AQI categories."""

    GOOD = "Good"
    MODERATE = "Moderate"

    UNHEALTHY_FOR_SENSITIVE_GROUPS = (
        "Unhealthy for Sensitive Groups"
    )

    UNHEALTHY = "Unhealthy"
    VERY_UNHEALTHY = "Very Unhealthy"
    HAZARDOUS = "Hazardous"
    BEYOND_AQI = "Beyond the AQI"


class AlertLevel(str, Enum):
    """Operational AQI alert levels."""

    NORMAL = "NORMAL"
    ADVISORY = "ADVISORY"
    WARNING = "WARNING"
    SEVERE = "SEVERE"
    EMERGENCY = "EMERGENCY"


class FreshnessStatus(str, Enum):
    """Freshness classification for the latest forecast."""

    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class ReadinessStatus(str, Enum):
    """Readiness state exposed by the API."""

    READY = "READY"

    READY_WITH_LIMITATIONS = (
        "READY_WITH_LIMITATIONS"
    )

    NOT_READY = "NOT_READY"
    STALE_FORECAST = "STALE_FORECAST"

    INVALID_ARTIFACTS = (
        "INVALID_ARTIFACTS"
    )


class PipelineStatus(str, Enum):
    """Public Phase 6 pipeline status values."""

    APPROVED = "AQI_ALERT_PIPELINE_APPROVED"

    APPROVED_WITH_LIMITATIONS = (
        "AQI_ALERT_PIPELINE_APPROVED_WITH_LIMITATIONS"
    )

    NOT_READY = "AQI_ALERT_PIPELINE_NOT_READY"


class PublicSchema(BaseModel):
    """Base configuration for public API models."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        use_enum_values=True,
    )


class LocationResponse(PublicSchema):
    """Public reference-location information."""

    name: str
    latitude: float
    longitude: float


class FreshnessResponse(PublicSchema):
    """Age and freshness of the latest artifact package."""

    generated_at_utc: datetime | None = None

    age_minutes: float | None = Field(
        default=None,
        ge=0,
    )

    age_hours: float | None = Field(
        default=None,
        ge=0,
    )

    status: FreshnessStatus

    aging_threshold_hours: float = Field(
        gt=0,
    )

    staleness_threshold_hours: float = Field(
        gt=0,
    )


class StandardErrorDetail(PublicSchema):
    """Public-safe API error information."""

    code: str
    message: str
    details: dict[str, Any] = Field(
        default_factory=dict
    )

    request_id: str
    timestamp_utc: datetime


class StandardErrorResponse(PublicSchema):
    """Consistent API error response body."""

    error: StandardErrorDetail