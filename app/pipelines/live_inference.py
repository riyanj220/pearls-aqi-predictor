"""Run the complete live 72-hour PM2.5 inference pipeline.

This module is the non-interactive production entry point for Phase 5.

It orchestrates the reusable components already implemented in:

- app.core.config
- app.data_sources.openaq_client
- app.data_sources.open_meteo_client
- app.data.validation
- app.features.live_feature_builder
- app.inference.predictor
- app.inference.run_artifacts

The runner does not duplicate feature-engineering or model logic.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd

from app.core.config import settings
from app.data.validation import (
    select_latest_safe_reference_time,
)
from app.data_sources.open_meteo_client import (
    OPEN_METEO_HOURLY_VARIABLES,
    OpenMeteoClient,
)
from app.data_sources.openaq_client import (
    OpenAQClient,
)
from app.features.live_feature_builder import (
    build_feature_rows,
    build_reference_feature_table,
    build_target_weather_feature_table,
)
from app.inference.predictor import (
    generate_hybrid_predictions,
    load_model_artifacts,
    validate_feature_matrix,
)
from app.inference.run_artifacts import (
    save_inference_run,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "live_inference_pipeline_report.json"
)


class LiveInferencePipelineError(RuntimeError):
    """Raised when live inference cannot complete safely."""


def utc_now() -> pd.Timestamp:
    """Return the current timezone-aware UTC timestamp."""

    return pd.Timestamp.now(tz="UTC")


def generate_pipeline_run_id() -> str:
    """Generate one unique and traceable pipeline-run ID."""

    return (
        utc_now().strftime("%Y%m%dT%H%M%SZ")
        + "_"
        + uuid4().hex[:8]
    )


def validate_pm25_history(
    *,
    history_df: pd.DataFrame,
    reference_time: pd.Timestamp,
) -> None:
    """Validate the exact 25-hour PM2.5 history contract."""

    required_columns = {
        "datetime_utc",
        "pm25_ug_m3",
    }

    missing_columns = sorted(
        required_columns.difference(
            history_df.columns
        )
    )

    if missing_columns:
        raise LiveInferencePipelineError(
            "PM2.5 history is missing columns: "
            f"{missing_columns}"
        )

    if len(history_df) != 25:
        raise LiveInferencePipelineError(
            "Expected exactly 25 PM2.5 history rows, "
            f"but received {len(history_df)}."
        )

    expected_timeline = pd.date_range(
        start=reference_time - pd.Timedelta(hours=24),
        end=reference_time,
        freq="h",
        tz="UTC",
    )

    actual_timeline = pd.DatetimeIndex(
        history_df["datetime_utc"]
    )

    if not actual_timeline.equals(expected_timeline):
        raise LiveInferencePipelineError(
            "PM2.5 history does not contain the exact "
            "hourly timeline from t-24 through t."
        )

    values = pd.to_numeric(
        history_df["pm25_ug_m3"],
        errors="coerce",
    )

    if values.isna().any():
        raise LiveInferencePipelineError(
            "PM2.5 history contains missing values."
        )

    if not np.isfinite(
        values.to_numpy(dtype=float)
    ).all():
        raise LiveInferencePipelineError(
            "PM2.5 history contains infinite values."
        )

    if not values.gt(0).all():
        raise LiveInferencePipelineError(
            "PM2.5 history contains non-positive values."
        )


def validate_weather_inputs(
    *,
    reference_weather_df: pd.DataFrame,
    target_weather_df: pd.DataFrame,
    reference_time: pd.Timestamp,
) -> None:
    """Validate reference and 72-hour target weather coverage."""

    if len(reference_weather_df) != 1:
        raise LiveInferencePipelineError(
            "Expected exactly one reference-weather row."
        )

    if len(target_weather_df) != 72:
        raise LiveInferencePipelineError(
            "Expected exactly 72 target-weather rows, "
            f"but received {len(target_weather_df)}."
        )

    required_weather_columns = list(
        OPEN_METEO_HOURLY_VARIABLES
    )

    missing_columns = sorted(
        set(required_weather_columns).difference(
            target_weather_df.columns
        )
    )

    if missing_columns:
        raise LiveInferencePipelineError(
            "Weather input is missing columns: "
            f"{missing_columns}"
        )

    expected_target_timeline = pd.date_range(
        start=reference_time + pd.Timedelta(hours=1),
        periods=72,
        freq="h",
        tz="UTC",
    )

    actual_target_timeline = pd.DatetimeIndex(
        target_weather_df["datetime_utc"]
    )

    if not actual_target_timeline.equals(
        expected_target_timeline
    ):
        raise LiveInferencePipelineError(
            "Target weather does not cover the exact "
            "72-hour forecast timeline."
        )

    reference_missing = int(
        reference_weather_df[
            required_weather_columns
        ]
        .isna()
        .sum()
        .sum()
    )

    target_missing = int(
        target_weather_df[
            required_weather_columns
        ]
        .isna()
        .sum()
        .sum()
    )

    if reference_missing or target_missing:
        raise LiveInferencePipelineError(
            "Weather input contains missing values."
        )


def build_live_feature_matrix(
    *,
    pm25_history_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    target_weather_df: pd.DataFrame,
    reference_time: pd.Timestamp,
    model_feature_columns: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build identifiers and the exact ordered model feature matrix."""

    live_reference_input_df = (
        pm25_history_df[
            [
                "datetime_utc",
                "pm25_ug_m3",
            ]
        ]
        .merge(
            weather_df,
            on="datetime_utc",
            how="left",
            validate="one_to_one",
        )
        .sort_values("datetime_utc")
        .reset_index(drop=True)
    )

    reference_feature_df = (
        build_reference_feature_table(
            live_reference_input_df
        )
    )

    selected_reference_feature_df = (
        reference_feature_df.loc[
            reference_feature_df[
                "reference_time"
            ].eq(reference_time)
        ]
        .copy()
        .reset_index(drop=True)
    )

    if len(selected_reference_feature_df) != 1:
        raise LiveInferencePipelineError(
            "Could not construct exactly one reference "
            "feature row."
        )

    target_weather_feature_df = (
        build_target_weather_feature_table(
            target_weather_df
        )
    )

    forecast_horizons = list(range(1, 73))

    model_feature_matrix_df = build_feature_rows(
        reference_feature_df=(
            selected_reference_feature_df
        ),
        target_weather_feature_df=(
            target_weather_feature_df
        ),
        reference_times=[reference_time],
        forecast_horizons=forecast_horizons,
        model_feature_columns=(
            model_feature_columns
        ),
    )

    identifiers_df = pd.DataFrame(
        {
            "reference_time": [reference_time] * 72,
            "target_time": pd.date_range(
                start=(
                    reference_time
                    + pd.Timedelta(hours=1)
                ),
                periods=72,
                freq="h",
                tz="UTC",
            ),
        }
    )

    complete_feature_df = pd.concat(
        [
            identifiers_df.reset_index(drop=True),
            model_feature_matrix_df.reset_index(
                drop=True
            ),
        ],
        axis=1,
    )

    return (
        complete_feature_df,
        model_feature_matrix_df,
    )


def validate_forecast_output(
    forecast_df: pd.DataFrame,
) -> None:
    """Validate the final 72-hour forecast contract."""

    required_columns = {
        "pipeline_run_id",
        "prediction_generated_at_utc",
        "reference_time",
        "target_time",
        "forecast_horizon_hours",
        "predicted_pm25_ug_m3_raw",
        "predicted_pm25_ug_m3",
        "prediction_was_clipped",
        "prediction_source",
        "location_name",
        "sensor_id",
        "selected_strategy",
    }

    missing_columns = sorted(
        required_columns.difference(
            forecast_df.columns
        )
    )

    if missing_columns:
        raise LiveInferencePipelineError(
            "Forecast output is missing columns: "
            f"{missing_columns}"
        )

    if len(forecast_df) != 72:
        raise LiveInferencePipelineError(
            "Forecast must contain exactly 72 rows."
        )

    expected_horizons = list(range(1, 73))

    actual_horizons = (
        forecast_df["forecast_horizon_hours"]
        .astype(int)
        .tolist()
    )

    if actual_horizons != expected_horizons:
        raise LiveInferencePipelineError(
            "Forecast horizons are not exactly 1 through 72."
        )

    if forecast_df["reference_time"].nunique() != 1:
        raise LiveInferencePipelineError(
            "Forecast contains multiple reference timestamps."
        )

    if forecast_df["target_time"].nunique() != 72:
        raise LiveInferencePipelineError(
            "Forecast target timestamps are not unique."
        )

    predictions = pd.to_numeric(
        forecast_df["predicted_pm25_ug_m3"],
        errors="coerce",
    )

    if predictions.isna().any():
        raise LiveInferencePipelineError(
            "Forecast contains missing predictions."
        )

    if not np.isfinite(
        predictions.to_numpy(dtype=float)
    ).all():
        raise LiveInferencePipelineError(
            "Forecast contains infinite predictions."
        )

    if predictions.lt(0).any():
        raise LiveInferencePipelineError(
            "Forecast contains negative operational predictions."
        )


def run_live_inference() -> dict[str, Any]:
    """Run the complete Phase 5 production inference pipeline."""

    started_at = datetime.now(timezone.utc)
    pipeline_run_id = generate_pipeline_run_id()

    model_artifacts = load_model_artifacts(
        settings
    )

    openaq_client = OpenAQClient(
        app_settings=settings
    )

    weather_client = OpenMeteoClient(
        app_settings=settings
    )

    recent_pm25_df = (
        openaq_client.fetch_recent_hourly_pm25()
    )

    live_weather_df = (
        weather_client.fetch_hourly_weather()
    )

    reference_selection = (
        select_latest_safe_reference_time(
            pm25_df=recent_pm25_df,
            weather_df=live_weather_df,
            app_settings=settings,
        )
    )

    if not reference_selection.is_ready:
        raise LiveInferencePipelineError(
            "Live inputs are not ready. "
            f"Status={reference_selection.status}. "
            f"Message={reference_selection.message}"
        )

    reference_time = (
        reference_selection.selected_reference_time
    )

    if reference_time is None:
        raise LiveInferencePipelineError(
            "Reference selection returned no timestamp."
        )

    history_start = (
        reference_time
        - pd.Timedelta(
            hours=settings.minimum_pm25_history_hours
        )
    )

    selected_pm25_history_df = (
        recent_pm25_df.loc[
            recent_pm25_df[
                "datetime_utc"
            ].between(
                history_start,
                reference_time,
            )
        ]
        .copy()
        .sort_values("datetime_utc")
        .reset_index(drop=True)
    )

    selected_reference_weather_df = (
        live_weather_df.loc[
            live_weather_df[
                "datetime_utc"
            ].eq(reference_time)
        ]
        .copy()
        .reset_index(drop=True)
    )

    target_start = (
        reference_time
        + pd.Timedelta(hours=1)
    )

    target_end = (
        reference_time
        + pd.Timedelta(hours=72)
    )

    selected_target_weather_df = (
        live_weather_df.loc[
            live_weather_df[
                "datetime_utc"
            ].between(
                target_start,
                target_end,
            )
        ]
        .copy()
        .sort_values("datetime_utc")
        .reset_index(drop=True)
    )

    validate_pm25_history(
        history_df=selected_pm25_history_df,
        reference_time=reference_time,
    )

    validate_weather_inputs(
        reference_weather_df=(
            selected_reference_weather_df
        ),
        target_weather_df=(
            selected_target_weather_df
        ),
        reference_time=reference_time,
    )

    (
        complete_feature_df,
        model_feature_matrix_df,
    ) = build_live_feature_matrix(
        pm25_history_df=selected_pm25_history_df,
        weather_df=live_weather_df,
        target_weather_df=(
            selected_target_weather_df
        ),
        reference_time=reference_time,
        model_feature_columns=(
            model_artifacts.feature_columns
        ),
    )

    validate_feature_matrix(
        model_feature_matrix_df,
        model_artifacts,
    )

    prediction_result_df = (
        generate_hybrid_predictions(
            feature_matrix=(
                model_feature_matrix_df
            ),
            artifacts=model_artifacts,
        )
    )

    prediction_generated_at_utc = utc_now()

    forecast_df = (
        complete_feature_df[
            [
                "reference_time",
                "target_time",
                "forecast_horizon_hours",
            ]
        ]
        .merge(
            prediction_result_df,
            on="forecast_horizon_hours",
            how="left",
            validate="one_to_one",
        )
    )

    forecast_df.insert(
        0,
        "pipeline_run_id",
        pipeline_run_id,
    )

    forecast_df.insert(
        1,
        "prediction_generated_at_utc",
        prediction_generated_at_utc,
    )

    forecast_df["location_name"] = (
        settings.location_name
    )

    forecast_df["sensor_id"] = (
        settings.openaq_sensor_id
    )

    forecast_df["selected_strategy"] = (
        model_artifacts.selected_strategy
    )

    validate_forecast_output(
        forecast_df
    )

    weather_input_for_run_df = (
        pd.concat(
            [
                selected_reference_weather_df,
                selected_target_weather_df,
            ],
            ignore_index=True,
        )
        .sort_values("datetime_utc")
        .reset_index(drop=True)
    )

    validation_report = {
        "status": "PASSED",
        "pipeline_run_id": pipeline_run_id,
        "validated_at_utc": utc_now(),
        "reference_selection_status": (
            reference_selection.status
        ),
        "checks": {
            "reference_ready": True,
            "pm25_history_rows_expected": 25,
            "pm25_history_rows_actual": len(
                selected_pm25_history_df
            ),
            "reference_weather_rows_expected": 1,
            "reference_weather_rows_actual": len(
                selected_reference_weather_df
            ),
            "target_weather_rows_expected": 72,
            "target_weather_rows_actual": len(
                selected_target_weather_df
            ),
            "feature_rows_expected": 72,
            "feature_rows_actual": len(
                model_feature_matrix_df
            ),
            "feature_columns_expected": len(
                model_artifacts.feature_columns
            ),
            "feature_columns_actual": len(
                model_feature_matrix_df.columns
            ),
            "feature_missing_values": int(
                model_feature_matrix_df
                .isna()
                .sum()
                .sum()
            ),
            "forecast_rows_expected": 72,
            "forecast_rows_actual": len(
                forecast_df
            ),
            "forecast_missing_values": int(
                forecast_df[
                    "predicted_pm25_ug_m3"
                ].isna().sum()
            ),
            "negative_operational_predictions": int(
                forecast_df[
                    "predicted_pm25_ug_m3"
                ].lt(0).sum()
            ),
            "persistence_prediction_rows": int(
                forecast_df[
                    "prediction_source"
                ]
                .eq(
                    "current_pm25_persistence"
                )
                .sum()
            ),
            "model_prediction_rows": int(
                forecast_df[
                    "forecast_horizon_hours"
                ]
                .gt(
                    model_artifacts
                    .persistence_max_horizon
                )
                .sum()
            ),
        },
    }

    run_metadata = {
        "pipeline_run_id": pipeline_run_id,
        "project_name": settings.project_name,
        "forecast_description": (
            settings.forecast_description
        ),
        "prediction_generated_at_utc": (
            prediction_generated_at_utc
        ),
        "location": {
            "name": settings.location_name,
            "latitude": settings.latitude,
            "longitude": settings.longitude,
            "timezone": settings.timezone,
        },
        "pollution_source": {
            "provider": "OpenAQ",
            "location_id": (
                settings.openaq_location_id
            ),
            "sensor_id": (
                settings.openaq_sensor_id
            ),
            "parameter": settings.pollutant,
            "unit": settings.pollution_unit,
        },
        "weather_source": {
            "provider": "Open-Meteo",
            "variables": list(
                OPEN_METEO_HOURLY_VARIABLES
            ),
        },
        "model": {
            "model_name": (
                model_artifacts.model_name
            ),
            "model_type": (
                model_artifacts.model_type
            ),
            "selected_strategy": (
                model_artifacts.selected_strategy
            ),
            "feature_count": len(
                model_artifacts.feature_columns
            ),
            "persistence_max_horizon": (
                model_artifacts
                .persistence_max_horizon
            ),
            "model_source": (
                model_artifacts.model_source
            ),
            "model_registry_version": (
                model_artifacts
                .model_registry_version
            ),
            "model_checksum_sha256": (
                model_artifacts
                .model_checksum_sha256
            ),
            "model_fallback_used": (
                model_artifacts
                .model_fallback_used
            ),
        },
        "forecast": {
            "reference_time": reference_time,
            "target_start": (
                forecast_df["target_time"].min()
            ),
            "target_end": (
                forecast_df["target_time"].max()
            ),
            "forecast_rows": len(forecast_df),
        },
        "inputs": {
            "pm25_history_start": (
                selected_pm25_history_df[
                    "datetime_utc"
                ].min()
            ),
            "pm25_history_end": (
                selected_pm25_history_df[
                    "datetime_utc"
                ].max()
            ),
            "pm25_history_rows": len(
                selected_pm25_history_df
            ),
            "weather_rows": len(
                weather_input_for_run_df
            ),
            "latest_pm25_age_hours": (
                reference_selection
                .latest_pm25_age_hours
            ),
        },
    }

    saved_run = save_inference_run(
        run_id=pipeline_run_id,
        forecast_df=forecast_df,
        feature_matrix_df=complete_feature_df,
        pm25_input_df=selected_pm25_history_df,
        weather_input_df=(
            weather_input_for_run_df
        ),
        run_metadata=run_metadata,
        validation_report=validation_report,
        app_settings=settings,
    )

    completed_at = datetime.now(timezone.utc)

    return {
        "phase": "5",
        "pipeline_name": "live_inference",
        "pipeline_run_id": pipeline_run_id,
        "status": "LIVE_INFERENCE_COMPLETED",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": completed_at.isoformat(),
        "duration_seconds": (
            completed_at - started_at
        ).total_seconds(),
        "reference_time": (
            reference_time.isoformat()
        ),
        "forecast_start": (
            forecast_df[
                "target_time"
            ].min().isoformat()
        ),
        "forecast_end": (
            forecast_df[
                "target_time"
            ].max().isoformat()
        ),
        "forecast_rows": len(forecast_df),
        "feature_count": len(
            model_artifacts.feature_columns
        ),
        "model_name": (
            model_artifacts.model_name
        ),
        "model_source": (
            model_artifacts.model_source
        ),
        "model_registry_version": (
            model_artifacts.model_registry_version
        ),
        "model_fallback_used": (
            model_artifacts.model_fallback_used
        ),
        "run_directory": str(
            saved_run.run_directory
        ),
        "validation_status": (
            validation_report["status"]
        ),
    }


def save_pipeline_report(
    report: dict[str, Any],
) -> Path:
    """Save the latest Phase 5 operational report."""

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    return REPORT_PATH


def main() -> int:
    """CLI entry point."""

    parser = argparse.ArgumentParser(
        description=(
            "Run the live 72-hour PM2.5 "
            "inference pipeline."
        )
    )

    parser.parse_args()

    try:
        report = run_live_inference()
        exit_code = 0

    except Exception as error:
        report = {
            "phase": "5",
            "pipeline_name": "live_inference",
            "pipeline_run_id": (
                generate_pipeline_run_id()
            ),
            "status": "LIVE_INFERENCE_FAILED",
            "failed_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "error_type": type(error).__name__,
            "error_message": str(error),
        }

        exit_code = 1

    report_path = save_pipeline_report(
        report
    )

    print(
        json.dumps(
            report,
            indent=2,
            default=str,
        )
    )

    print("Report saved:", report_path)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())