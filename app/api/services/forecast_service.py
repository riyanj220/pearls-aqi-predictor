"""Forecast response mapping and filtering."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.api.config import APISettings
from app.api.errors import APIServiceError
from app.api.schemas.common import (
    AQICategory,
    AlertLevel,
    LocationResponse,
)
from app.api.schemas.forecast import (
    CompleteForecastResponse,
    ForecastSummaryResponse,
    HourlyFiltersResponse,
    HourlyForecastRecord,
    HourlyForecastResponse,
)
from app.api.services.artifact_repository import (
    ArtifactBundle,
    json_safe_value,
)
from app.api.services.readiness_service import (
    freshness_response,
)

DISCLAIMER = (
    "This forecast is a model-generated PM2.5-based AQI "
    "estimate for the Zafar Memon DHA reference location "
    "and is not an official government AQI report."
)


class ForecastService:
    """Map Phase 6 artifacts to stable public responses."""

    def __init__(
        self,
        *,
        settings: APISettings,
    ) -> None:
        self._settings = settings

    def build_hourly_record(
        self,
        row: pd.Series,
    ) -> HourlyForecastRecord:
        """Map one internal forecast row."""

        rolling_complete = bool(
            row[
                "rolling_24h_pm25_is_complete"
            ]
        )

        def optional_float(
            field: str,
        ) -> float | None:
            value = json_safe_value(
                row[field]
            )

            return (
                float(value)
                if value is not None
                else None
            )

        def optional_int(
            field: str,
        ) -> int | None:
            value = json_safe_value(
                row[field]
            )

            return (
                int(value)
                if value is not None
                else None
            )

        def optional_string(
            field: str,
        ) -> str | None:
            value = json_safe_value(
                row[field]
            )

            return (
                str(value)
                if value is not None
                else None
            )

        return HourlyForecastRecord(
            target_time_utc=row["target_time"],
            forecast_horizon_hours=int(
                row["forecast_horizon_hours"]
            ),
            predicted_pm25_ug_m3=float(
                row["predicted_pm25_ug_m3"]
            ),
            indicative_hourly_pm25_aqi=int(
                row[
                    "indicative_hourly_pm25_aqi"
                ]
            ),
            indicative_hourly_aqi_category=str(
                row[
                    "indicative_hourly_aqi_category"
                ]
            ),
            indicative_hourly_aqi_color_hex=str(
                row[
                    "indicative_hourly_aqi_color_hex"
                ]
            ),
            rolling_24h_pm25_ug_m3=(
                optional_float(
                    "rolling_24h_pm25_ug_m3"
                )
                if rolling_complete
                else None
            ),
            rolling_24h_pm25_aqi=(
                optional_int(
                    "rolling_24h_pm25_aqi"
                )
                if rolling_complete
                else None
            ),
            rolling_24h_aqi_category=(
                optional_string(
                    "rolling_24h_aqi_category"
                )
                if rolling_complete
                else None
            ),
            rolling_24h_aqi_color_hex=(
                optional_string(
                    "rolling_24h_aqi_color_hex"
                )
                if rolling_complete
                else None
            ),
            rolling_24h_pm25_is_complete=(
                rolling_complete
            ),
            rolling_24h_missing_hours=int(
                row[
                    "rolling_24h_missing_hours"
                ]
            ),
            rolling_observed_hour_count=int(
                row[
                    "rolling_observed_hour_count"
                ]
            ),
            rolling_predicted_hour_count=int(
                row[
                    "rolling_predicted_hour_count"
                ]
            ),
            alert_level=str(
                row["alert_level"]
            ),
            alert_basis=str(
                row["alert_basis"]
            ),
            alert_trigger_aqi=int(
                row["alert_trigger_aqi"]
            ),
            alert_trigger_category=str(
                row["alert_trigger_category"]
            ),
            alert_is_active=bool(
                row["alert_is_active"]
            ),
            sensitive_groups_alert=bool(
                row["sensitive_groups_alert"]
            ),
            general_population_alert=bool(
                row["general_population_alert"]
            ),
            hazardous_alert=bool(
                row["hazardous_alert"]
            ),
            health_message=str(
                row["health_message"]
            ),
            recommended_action=str(
                row["recommended_action"]
            ),
        )

    def build_summary(
        self,
        bundle: ArtifactBundle,
    ) -> ForecastSummaryResponse:
        """Build a public summary using saved and forecast data."""

        forecast_df = bundle.forecast_df

        peak_pm25_index = (
            forecast_df[
                "predicted_pm25_ug_m3"
            ].astype(float).idxmax()
        )

        peak_pm25_row = forecast_df.loc[
            peak_pm25_index
        ]

        complete_rolling_df = (
            forecast_df.loc[
                forecast_df[
                    "rolling_24h_pm25_is_complete"
                ].astype(bool)
            ]
        )

        if complete_rolling_df.empty:
            maximum_rolling_aqi = None
        else:
            maximum_rolling_aqi = int(
                complete_rolling_df[
                    "rolling_24h_pm25_aqi"
                ].max()
            )

        worst_row = forecast_df.loc[
            forecast_df[
                "alert_trigger_aqi"
            ].astype(float).idxmax()
        ]

        summary = bundle.summary

        return ForecastSummaryResponse(
            phase_6_run_id=(
                bundle.phase_6_run_id
            ),
            source_phase_5_run_id=(
                bundle.source_phase_5_run_id
            ),
            generated_at_utc=(
                bundle.generated_at_utc
            ),
            reference_time_utc=(
                forecast_df[
                    "reference_time"
                ].iloc[0]
            ),
            forecast_start_utc=(
                forecast_df[
                    "target_time"
                ].min()
            ),
            forecast_end_utc=(
                forecast_df[
                    "target_time"
                ].max()
            ),
            forecast_rows=len(forecast_df),
            minimum_predicted_pm25_ug_m3=float(
                summary.get(
                    "minimum_predicted_pm25",
                    forecast_df[
                        "predicted_pm25_ug_m3"
                    ].min(),
                )
            ),
            maximum_predicted_pm25_ug_m3=float(
                summary.get(
                    "maximum_predicted_pm25",
                    forecast_df[
                        "predicted_pm25_ug_m3"
                    ].max(),
                )
            ),
            average_predicted_pm25_ug_m3=float(
                forecast_df[
                    "predicted_pm25_ug_m3"
                ].mean()
            ),
            peak_pm25_time_utc=(
                peak_pm25_row["target_time"]
            ),
            minimum_indicative_hourly_aqi=int(
                summary.get(
                    "minimum_indicative_hourly_aqi",
                    forecast_df[
                        "indicative_hourly_pm25_aqi"
                    ].min(),
                )
            ),
            maximum_indicative_hourly_aqi=int(
                summary.get(
                    "maximum_indicative_hourly_aqi",
                    forecast_df[
                        "indicative_hourly_pm25_aqi"
                    ].max(),
                )
            ),
            maximum_rolling_24h_aqi=(
                maximum_rolling_aqi
            ),
            worst_aqi_category=str(
                worst_row[
                    "alert_trigger_category"
                ]
            ),
            active_alert_hours=int(
                forecast_df[
                    "alert_is_active"
                ].sum()
            ),
            alert_episode_count=len(
                bundle.alert_episodes
            ),
            hazardous_condition=bool(
                forecast_df[
                    "hazardous_alert"
                ].any()
            ),
        )

    def filter_hourly(
        self,
        *,
        bundle: ArtifactBundle,
        minimum_horizon: int | None,
        maximum_horizon: int | None,
        category: AQICategory | None,
        alert_level: AlertLevel | None,
        alerts_only: bool,
    ) -> HourlyForecastResponse:
        """Apply supported filters and return public records."""

        if (
            minimum_horizon is not None
            and maximum_horizon is not None
            and minimum_horizon
            > maximum_horizon
        ):
            raise APIServiceError(
                status_code=400,
                code="INVALID_QUERY_PARAMETER",
                message=(
                    "minimum_horizon cannot be greater "
                    "than maximum_horizon."
                ),
            )

        filtered_df = bundle.forecast_df.copy()

        if minimum_horizon is not None:
            filtered_df = filtered_df.loc[
                filtered_df[
                    "forecast_horizon_hours"
                ]
                >= minimum_horizon
            ]

        if maximum_horizon is not None:
            filtered_df = filtered_df.loc[
                filtered_df[
                    "forecast_horizon_hours"
                ]
                <= maximum_horizon
            ]

        if category is not None:
            filtered_df = filtered_df.loc[
                filtered_df[
                    "alert_trigger_category"
                ]
                == category.value
            ]

        if alert_level is not None:
            filtered_df = filtered_df.loc[
                filtered_df[
                    "alert_level"
                ]
                == alert_level.value
            ]

        if alerts_only:
            filtered_df = filtered_df.loc[
                filtered_df[
                    "alert_is_active"
                ].astype(bool)
            ]

        records = [
            self.build_hourly_record(row)
            for _, row
            in filtered_df.iterrows()
        ]

        filters = HourlyFiltersResponse(
            minimum_horizon=minimum_horizon,
            maximum_horizon=maximum_horizon,
            category=category,
            alert_level=alert_level,
            alerts_only=alerts_only,
        )

        return HourlyForecastResponse(
            pipeline_run_id=(
                bundle.phase_6_run_id
            ),
            generated_at_utc=(
                bundle.generated_at_utc
            ),
            freshness=freshness_response(
                bundle=bundle,
                settings=self._settings,
            ),
            applied_filters=filters,
            result_count=len(records),
            records=records,
        )

    def build_complete_forecast(
        self,
        bundle: ArtifactBundle,
    ) -> CompleteForecastResponse:
        """Build the dashboard-oriented full response."""

        forecast_df = bundle.forecast_df

        records = [
            self.build_hourly_record(row)
            for _, row
            in forecast_df.iterrows()
        ]

        project_metadata = (
            bundle.metadata.get(
                "project",
                {},
            )
        )

        limitations = list(
            bundle.validation_report.get(
                "limitations",
                [],
            )
        )

        return CompleteForecastResponse(
            project_name=(
                "Pearls AQI Predictor"
            ),
            description=(
                self._settings
                .application_description
            ),
            location=LocationResponse(
                name=str(
                    project_metadata.get(
                        "location",
                        forecast_df[
                            "location_name"
                        ].iloc[0],
                    )
                ),
                latitude=24.814741,
                longitude=67.067062,
            ),
            pipeline_run_id=(
                bundle.phase_6_run_id
            ),
            source_phase_5_run_id=(
                bundle.source_phase_5_run_id
            ),
            generated_at_utc=(
                bundle.generated_at_utc
            ),
            reference_time_utc=(
                forecast_df[
                    "reference_time"
                ].iloc[0]
            ),
            forecast_start_utc=(
                forecast_df[
                    "target_time"
                ].min()
            ),
            forecast_end_utc=(
                forecast_df[
                    "target_time"
                ].max()
            ),
            freshness=freshness_response(
                bundle=bundle,
                settings=self._settings,
            ),
            summary=self.build_summary(
                bundle
            ),
            active_alert_count=int(
                forecast_df[
                    "alert_is_active"
                ].sum()
            ),
            hourly_forecast=records,
            limitations=limitations,
            disclaimer=DISCLAIMER,
        )