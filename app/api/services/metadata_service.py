"""Public metadata and pipeline-status response mapping."""

from __future__ import annotations

from app.api.config import APISettings
from app.api.schemas.common import (
    LocationResponse,
)
from app.api.schemas.metadata import (
    AQIInterpretationResponse,
    MetadataResponse,
    PipelineStatusResponse,
)
from app.api.services.artifact_repository import (
    ArtifactBundle,
)
from app.api.services.readiness_service import (
    freshness_response,
)


class MetadataService:
    """Build public-safe metadata and operational status."""

    def __init__(
        self,
        *,
        settings: APISettings,
    ) -> None:
        self._settings = settings

    def build_metadata(
        self,
        bundle: ArtifactBundle,
    ) -> MetadataResponse:
        """Return project metadata without secrets or paths."""

        project = bundle.metadata.get(
            "project",
            {},
        )

        aqi_standard = (
            bundle.metadata.get(
                "aqi_standard",
                {},
            )
        )

        forecast_df = bundle.forecast_df

        limitations = list(
            bundle.validation_report.get(
                "limitations",
                [],
            )
        )

        return MetadataResponse(
            project_name=(
                "Pearls AQI Predictor"
            ),
            application_description=(
                self._settings
                .application_description
            ),
            location=LocationResponse(
                name=str(
                    project.get(
                        "location",
                        forecast_df[
                            "location_name"
                        ].iloc[0],
                    )
                ),
                latitude=24.814741,
                longitude=67.067062,
            ),
            pollution_source="OpenAQ",
            original_sensor_provider=(
                "AirGradient"
            ),
            weather_sources=[
                (
                    "Open-Meteo Historical "
                    "Weather API"
                ),
                "Open-Meteo Forecast API",
            ],
            pollutant="PM2.5",
            concentration_unit="µg/m³",
            forecast_horizon_hours=72,
            internal_timezone="UTC",
            aqi_standard_name=str(
                aqi_standard.get(
                    "name",
                    "U.S. EPA PM2.5 AQI",
                )
            ),
            aqi_standard_version=str(
                aqi_standard.get(
                    "version",
                    "May 2026",
                )
            ),
            aqi_interpretation=(
                AQIInterpretationResponse(
                    indicative_hourly=(
                        "AQI-style interpretation "
                        "of each hourly PM2.5 "
                        "prediction. It is not an "
                        "official regulatory daily AQI."
                    ),
                    rolling_24h=(
                        "AQI calculated from an exact "
                        "trailing 24-hour PM2.5 window "
                        "when all required hours exist."
                    ),
                )
            ),
            latest_phase_6_run_id=(
                bundle.phase_6_run_id
            ),
            latest_phase_5_run_id=(
                bundle.source_phase_5_run_id
            ),
            processing_timestamp_utc=(
                bundle.generated_at_utc
            ),
            freshness=freshness_response(
                bundle=bundle,
                settings=self._settings,
            ),
            known_limitations=limitations,
        )

    def build_pipeline_status(
        self,
        bundle: ArtifactBundle,
    ) -> PipelineStatusResponse:
        """Return operational status from saved validation artifacts."""

        validation_checks = (
            bundle.validation_report.get(
                "checks",
                {},
            )
        )

        phase_5_status = str(
            validation_checks.get(
                "source_phase_5_status",
                "UNKNOWN",
            )
        )

        forecast_df = bundle.forecast_df

        return PipelineStatusResponse(
            phase_5_run_id=(
                bundle.source_phase_5_run_id
            ),
            phase_5_status=phase_5_status,
            phase_6_run_id=(
                bundle.phase_6_run_id
            ),
            phase_6_status=str(
                bundle.validation_report.get(
                    "status",
                    "UNKNOWN",
                )
            ),
            generated_at_utc=(
                bundle.generated_at_utc
            ),
            artifact_consistency_passed=True,
            forecast_row_count=len(
                forecast_df
            ),
            prediction_count=len(
                forecast_df
            ),
            active_alert_count=int(
                forecast_df[
                    "alert_is_active"
                ].sum()
            ),
            alert_episode_count=len(
                bundle.alert_episodes
            ),
            freshness=freshness_response(
                bundle=bundle,
                settings=self._settings,
            ),
            limitations=list(
                bundle.validation_report.get(
                    "limitations",
                    [],
                )
            ),
        )