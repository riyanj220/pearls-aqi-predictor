"""Readiness and freshness response construction."""

from __future__ import annotations

from datetime import datetime, timezone

from app.api.config import APISettings
from app.api.schemas.common import (
    FreshnessResponse,
    FreshnessStatus,
    ReadinessStatus,
)
from app.api.schemas.health import (
    ReadinessResponse,
)
from app.api.services.artifact_repository import (
    ArtifactBundle,
    ArtifactRepository,
    ArtifactRepositoryError,
)


class ReadinessService:
    """Evaluate whether forecast data can be served."""

    def __init__(
        self,
        *,
        settings: APISettings,
        repository: ArtifactRepository,
    ) -> None:
        self._settings = settings
        self._repository = repository

    def evaluate(self) -> ReadinessResponse:
        """Build readiness without raising artifact errors."""

        checked_at_utc = datetime.now(
            timezone.utc
        )

        try:
            bundle = (
                self._repository.load_latest()
            )

        except ArtifactRepositoryError:
            return ReadinessResponse(
                status=(
                    ReadinessStatus.INVALID_ARTIFACTS
                ),
                service=(
                    self._settings.application_name
                ),
                version=(
                    self._settings.application_version
                ),
                timestamp_utc=checked_at_utc,
                forecast_available=False,
                artifacts_valid=False,
                pipeline_run_id=None,
                forecast_rows=None,
                freshness=None,
                data_quality_status=None,
                source_degraded=False,
                limitations=[],
                message=(
                    "The forecast service is online, "
                    "but no valid forecast is currently "
                    "available."
                ),
            )

        freshness = freshness_response(
            bundle=bundle,
            settings=self._settings,
        )

        limitations = list(
            bundle.validation_report.get(
                "limitations",
                [],
            )
        )

        input_quality = (
            bundle.metadata.get(
                "input_quality",
                {},
            )
        )

        if not isinstance(
            input_quality,
            dict,
        ):
            input_quality = {}

        data_quality_status = str(
            input_quality.get(
                "status",
                "GOOD",
            )
        ).upper()

        source_degraded = (
            data_quality_status
            == "DEGRADED"
        )

        if (
            bundle.freshness.status
            == FreshnessStatus.STALE
        ):
            readiness_status = (
                ReadinessStatus.STALE_FORECAST
            )

            message = (
                "Fresh sensor data is temporarily delayed. "
                "The most recent validated forecast remains "
                "available but is now stale."
            )

        elif source_degraded:
            readiness_status = (
                ReadinessStatus
                .READY_WITH_LIMITATIONS
            )

            message = (
                "The forecast is available. A short gap in "
                "recent PM2.5 observations was estimated to "
                "maintain forecast continuity."
            )

        elif limitations:
            readiness_status = (
                ReadinessStatus
                .READY_WITH_LIMITATIONS
            )

            message = (
                "The latest validated forecast is ready "
                "with documented methodological limitations."
            )

        else:
            readiness_status = (
                ReadinessStatus.READY
            )

            message = (
                "The latest validated forecast is ready."
            )

        return ReadinessResponse(
            status=readiness_status,
            service=self._settings.application_name,
            version=(
                self._settings.application_version
            ),
            timestamp_utc=checked_at_utc,
            forecast_available=True,
            artifacts_valid=True,
            pipeline_run_id=(
                bundle.phase_6_run_id
            ),
            forecast_rows=len(
                bundle.forecast_df
            ),
            freshness=freshness,
            data_quality_status=(
                data_quality_status
            ),
            source_degraded=(
                source_degraded
            ),
            limitations=limitations,
            message=message,
        )


def freshness_response(
    *,
    bundle: ArtifactBundle,
    settings: APISettings,
) -> FreshnessResponse:
    """Map repository freshness into the public schema."""

    freshness = bundle.freshness

    return FreshnessResponse(
        generated_at_utc=(
            freshness.generated_at_utc
        ),
        age_minutes=freshness.age_minutes,
        age_hours=freshness.age_hours,
        status=freshness.status,
        aging_threshold_hours=(
            settings
            .forecast_aging_threshold_hours
        ),
        staleness_threshold_hours=(
            settings
            .forecast_staleness_threshold_hours
        ),
    )