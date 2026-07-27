"""Public forecast response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.schemas.common import (
    AQICategory,
    AlertLevel,
    FreshnessResponse,
    LocationResponse,
    PublicSchema,
)


class HourlyForecastRecord(PublicSchema):
    """One public hourly PM2.5 and AQI forecast row."""

    target_time_utc: datetime

    forecast_horizon_hours: int = Field(
        ge=1,
        le=72,
    )

    predicted_pm25_ug_m3: float = Field(
        ge=0,
    )

    indicative_hourly_pm25_aqi: int = Field(
        ge=0,
    )

    indicative_hourly_aqi_category: AQICategory

    indicative_hourly_aqi_color_hex: str = Field(
        pattern=r"^#[0-9A-Fa-f]{6}$"
    )

    rolling_24h_pm25_ug_m3: float | None = Field(
        default=None,
        ge=0,
    )

    rolling_24h_pm25_aqi: int | None = Field(
        default=None,
        ge=0,
    )

    rolling_24h_aqi_category: AQICategory | None = None

    rolling_24h_aqi_color_hex: str | None = Field(
        default=None,
        pattern=r"^#[0-9A-Fa-f]{6}$",
    )

    rolling_24h_pm25_is_complete: bool

    rolling_24h_missing_hours: int = Field(
        ge=0,
        le=24,
    )

    rolling_observed_hour_count: int = Field(
        ge=0,
        le=24,
    )

    rolling_predicted_hour_count: int = Field(
        ge=0,
        le=24,
    )

    alert_level: AlertLevel
    alert_basis: str

    alert_trigger_aqi: int = Field(
        ge=0,
    )

    alert_trigger_category: AQICategory

    alert_is_active: bool
    sensitive_groups_alert: bool
    general_population_alert: bool
    hazardous_alert: bool

    health_message: str
    recommended_action: str


class ForecastSummaryResponse(PublicSchema):
    """Stable public summary of one 72-hour forecast."""

    phase_6_run_id: str
    source_phase_5_run_id: str

    generated_at_utc: datetime
    reference_time_utc: datetime

    forecast_start_utc: datetime
    forecast_end_utc: datetime

    forecast_rows: int = Field(
        ge=0,
    )

    minimum_predicted_pm25_ug_m3: float = Field(
        ge=0,
    )

    maximum_predicted_pm25_ug_m3: float = Field(
        ge=0,
    )

    average_predicted_pm25_ug_m3: float = Field(
        ge=0,
    )

    peak_pm25_time_utc: datetime

    minimum_indicative_hourly_aqi: int = Field(
        ge=0,
    )

    maximum_indicative_hourly_aqi: int = Field(
        ge=0,
    )

    maximum_rolling_24h_aqi: int | None = Field(
        default=None,
        ge=0,
    )

    worst_aqi_category: AQICategory

    active_alert_hours: int = Field(
        ge=0,
    )

    alert_episode_count: int = Field(
        ge=0,
    )

    hazardous_condition: bool


class HourlyFiltersResponse(PublicSchema):
    """Filters applied to an hourly request."""

    minimum_horizon: int | None = Field(
        default=None,
        ge=1,
        le=72,
    )

    maximum_horizon: int | None = Field(
        default=None,
        ge=1,
        le=72,
    )

    category: AQICategory | None = None
    alert_level: AlertLevel | None = None
    alerts_only: bool = False


class HourlyForecastResponse(PublicSchema):
    """Filterable hourly forecast collection."""

    pipeline_run_id: str
    generated_at_utc: datetime

    freshness: FreshnessResponse

    applied_filters: HourlyFiltersResponse

    result_count: int = Field(
        ge=0,
    )

    records: list[HourlyForecastRecord]


class CompleteForecastResponse(PublicSchema):
    """Complete dashboard-oriented forecast response."""

    project_name: str
    description: str

    location: LocationResponse

    pipeline_run_id: str
    source_phase_5_run_id: str

    generated_at_utc: datetime
    reference_time_utc: datetime
    forecast_start_utc: datetime
    forecast_end_utc: datetime

    freshness: FreshnessResponse
    summary: ForecastSummaryResponse

    active_alert_count: int = Field(
        ge=0,
    )

    hourly_forecast: list[HourlyForecastRecord]

    limitations: list[str]
    disclaimer: str