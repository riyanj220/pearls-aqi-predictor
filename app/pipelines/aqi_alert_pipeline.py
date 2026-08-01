"""Run AQI enrichment and hazardous-condition alert generation.

This is the non-interactive production entry point for Phase 6.

It consumes one successful immutable Phase 5 inference run, enriches the
forecast with AQI values and alerts, saves an immutable AQI run, and publishes
the latest AQI artifacts only after validation succeeds.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.alerts.aqi_alerts import (
    add_aqi_alerts,
    build_alert_episodes,
)
from app.aqi.config import (
    AQI_STANDARD_NAME,
    AQI_STANDARD_VERSION,
    PM25_AQI_BREAKPOINTS,
)
from app.aqi.forecast_enrichment import (
    enrich_forecast_with_aqi,
)
from app.aqi.run_artifacts import (
    publish_latest_aqi_run,
    save_aqi_run,
)

import time

from app.observability import error_codes
from app.observability.logging import (
    configure_structured_logging,
    log_pipeline_completed,
    log_pipeline_failed,
    log_pipeline_started,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

INFERENCE_RUNS_DIRECTORY = (
    PROJECT_ROOT
    / "inference"
    / "runs"
)

REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "aqi_alert_pipeline_report.json"
)

LOGGER = configure_structured_logging(
    service_name="pearls-aqi-aqi-alerts",
)

class AQIAlertPipelineError(RuntimeError):
    """Raised when AQI processing cannot complete safely."""


REQUIRED_PHASE_5_FILENAMES = {
    "forecast": "forecast.parquet",
    "pm25_input": "pm25_input.parquet",
    "metadata": "run_metadata.json",
    "validation": "validation_report.json",
}


def read_json_object(
    path: Path,
) -> dict[str, Any]:
    """Read one JSON object."""

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ) as error:
        raise AQIAlertPipelineError(
            f"Could not read valid JSON: {path}"
        ) from error

    if not isinstance(payload, dict):
        raise AQIAlertPipelineError(
            f"Expected a JSON object: {path}"
        )

    return payload


def resolve_inference_run(
    requested_run_id: str | None = None,
) -> tuple[
    Path,
    dict[str, Any],
    dict[str, Any],
]:
    """Resolve one complete successful Phase 5 run."""

    if not INFERENCE_RUNS_DIRECTORY.exists():
        raise AQIAlertPipelineError(
            "Inference runs directory does not exist: "
            f"{INFERENCE_RUNS_DIRECTORY}"
        )

    if requested_run_id:
        run_directories = [
            INFERENCE_RUNS_DIRECTORY
            / requested_run_id
        ]
    else:
        run_directories = sorted(
            [
                path
                for path
                in INFERENCE_RUNS_DIRECTORY.iterdir()
                if path.is_dir()
            ],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

    for run_directory in run_directories:
        if not run_directory.exists():
            continue

        required_paths = {
            name: run_directory / filename
            for name, filename
            in REQUIRED_PHASE_5_FILENAMES.items()
        }

        if not all(
            path.exists()
            for path in required_paths.values()
        ):
            continue

        try:
            validation_report = read_json_object(
                required_paths["validation"]
            )

            metadata = read_json_object(
                required_paths["metadata"]
            )
        except AQIAlertPipelineError:
            continue

        if validation_report.get("status") != "PASSED":
            continue

        return (
            run_directory,
            validation_report,
            metadata,
        )

    if requested_run_id:
        raise AQIAlertPipelineError(
            "The requested inference run is missing, "
            "incomplete, or unsuccessful: "
            f"{requested_run_id}"
        )

    raise AQIAlertPipelineError(
        "No complete successful Phase 5 "
        "inference run was found."
    )


def validate_phase_5_forecast(
    *,
    forecast_df: pd.DataFrame,
    pm25_history_df: pd.DataFrame,
    phase_5_validation_report: dict[str, Any],
    phase_5_metadata: dict[str, Any],
) -> tuple[str, pd.Timestamp]:
    """Validate the Phase 5 source contract."""

    required_forecast_columns = {
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
        required_forecast_columns.difference(
            forecast_df.columns
        )
    )

    if missing_columns:
        raise AQIAlertPipelineError(
            "Phase 5 forecast is missing columns: "
            f"{missing_columns}"
        )

    forecast_df["reference_time"] = (
        pd.to_datetime(
            forecast_df["reference_time"],
            utc=True,
            errors="raise",
        )
    )

    forecast_df["target_time"] = (
        pd.to_datetime(
            forecast_df["target_time"],
            utc=True,
            errors="raise",
        )
    )

    forecast_df.sort_values(
        "forecast_horizon_hours",
        inplace=True,
    )

    forecast_df.reset_index(
        drop=True,
        inplace=True,
    )

    if (
        phase_5_validation_report.get("status")
        != "PASSED"
    ):
        raise AQIAlertPipelineError(
            "The source Phase 5 run did not pass validation."
        )

    if len(forecast_df) != 72:
        raise AQIAlertPipelineError(
            "The source forecast must contain 72 rows."
        )

    expected_horizons = list(range(1, 73))

    actual_horizons = (
        forecast_df["forecast_horizon_hours"]
        .astype(int)
        .tolist()
    )

    if actual_horizons != expected_horizons:
        raise AQIAlertPipelineError(
            "Forecast horizons are not exactly 1 through 72."
        )

    if forecast_df["reference_time"].nunique() != 1:
        raise AQIAlertPipelineError(
            "The forecast contains multiple reference times."
        )

    if forecast_df["target_time"].nunique() != 72:
        raise AQIAlertPipelineError(
            "The forecast target times are not unique."
        )

    reference_time = pd.Timestamp(
        forecast_df["reference_time"].iloc[0]
    )

    expected_timeline = pd.date_range(
        start=reference_time + pd.Timedelta(hours=1),
        periods=72,
        freq="h",
        tz="UTC",
    )

    if not pd.DatetimeIndex(
        forecast_df["target_time"]
    ).equals(expected_timeline):
        raise AQIAlertPipelineError(
            "Forecast target timestamps do not form "
            "an exact 72-hour timeline."
        )

    operational_predictions = pd.to_numeric(
        forecast_df["predicted_pm25_ug_m3"],
        errors="coerce",
    )

    if operational_predictions.isna().any():
        raise AQIAlertPipelineError(
            "Forecast contains missing PM2.5 predictions."
        )

    if not np.isfinite(
        operational_predictions.to_numpy(dtype=float)
    ).all():
        raise AQIAlertPipelineError(
            "Forecast contains infinite PM2.5 predictions."
        )

    if operational_predictions.lt(0).any():
        raise AQIAlertPipelineError(
            "Forecast contains negative PM2.5 predictions."
        )

    if forecast_df["pipeline_run_id"].nunique() != 1:
        raise AQIAlertPipelineError(
            "Forecast contains multiple pipeline run IDs."
        )

    source_run_id = str(
        forecast_df["pipeline_run_id"].iloc[0]
    )

    metadata_run_id = str(
        phase_5_metadata.get(
            "pipeline_run_id"
        )
    )

    if source_run_id != metadata_run_id:
        raise AQIAlertPipelineError(
            "Forecast and metadata pipeline run IDs differ."
        )

    required_history_columns = {
        "datetime_utc",
        "pm25_ug_m3",
    }

    missing_history_columns = sorted(
        required_history_columns.difference(
            pm25_history_df.columns
        )
    )

    if missing_history_columns:
        raise AQIAlertPipelineError(
            "PM2.5 history is missing columns: "
            f"{missing_history_columns}"
        )

    pm25_history_df["datetime_utc"] = (
        pd.to_datetime(
            pm25_history_df["datetime_utc"],
            utc=True,
            errors="raise",
        )
    )

    pm25_history_df.sort_values(
        "datetime_utc",
        inplace=True,
    )

    pm25_history_df.reset_index(
        drop=True,
        inplace=True,
    )

    if len(pm25_history_df) < 24:
        raise AQIAlertPipelineError(
            "At least 24 observed PM2.5 hours are required."
        )

    if (
        pm25_history_df["datetime_utc"].max()
        != reference_time
    ):
        raise AQIAlertPipelineError(
            "Observed PM2.5 history does not end "
            "at the forecast reference time."
        )

    expected_history_timeline = pd.date_range(
        start=pm25_history_df[
            "datetime_utc"
        ].min(),
        end=pm25_history_df[
            "datetime_utc"
        ].max(),
        freq="h",
        tz="UTC",
    )

    if not pd.DatetimeIndex(
        pm25_history_df["datetime_utc"]
    ).equals(expected_history_timeline):
        raise AQIAlertPipelineError(
            "Observed PM2.5 history contains missing hours."
        )

    history_values = pd.to_numeric(
        pm25_history_df["pm25_ug_m3"],
        errors="coerce",
    )

    if history_values.isna().any():
        raise AQIAlertPipelineError(
            "Observed PM2.5 history contains missing values."
        )

    if not history_values.gt(0).all():
        raise AQIAlertPipelineError(
            "Observed PM2.5 history contains "
            "non-positive values."
        )

    return source_run_id, reference_time


def validate_aqi_output(
    *,
    alerted_forecast_df: pd.DataFrame,
) -> dict[str, Any]:
    """Validate the complete Phase 6 output."""

    checks = {
        "forecast_rows_expected": 72,
        "forecast_rows_actual": len(
            alerted_forecast_df
        ),
        "unique_target_times": int(
            alerted_forecast_df[
                "target_time"
            ].nunique()
        ),
        "indicative_aqi_missing_values": int(
            alerted_forecast_df[
                "indicative_hourly_pm25_aqi"
            ].isna().sum()
        ),
        "rolling_aqi_missing_values": int(
            alerted_forecast_df[
                "rolling_24h_pm25_aqi"
            ].isna().sum()
        ),
        "complete_rolling_windows": int(
            alerted_forecast_df[
                "rolling_24h_pm25_is_complete"
            ].sum()
        ),
        "incomplete_rolling_windows": int(
            (
                ~alerted_forecast_df[
                    "rolling_24h_pm25_is_complete"
                ]
            ).sum()
        ),
        "missing_alert_levels": int(
            alerted_forecast_df[
                "alert_level"
            ].isna().sum()
        ),
        "missing_health_messages": int(
            alerted_forecast_df[
                "health_message"
            ].isna().sum()
        ),
        "missing_recommended_actions": int(
            alerted_forecast_df[
                "recommended_action"
            ].isna().sum()
        ),
        "negative_operational_pm25": int(
            alerted_forecast_df[
                "predicted_pm25_ug_m3"
            ].lt(0).sum()
        ),
    }

    approved = all(
        [
            checks["forecast_rows_actual"] == 72,
            checks["unique_target_times"] == 72,
            checks[
                "indicative_aqi_missing_values"
            ] == 0,
            checks[
                "rolling_aqi_missing_values"
            ] == 0,
            checks[
                "complete_rolling_windows"
            ] == 72,
            checks[
                "incomplete_rolling_windows"
            ] == 0,
            checks["missing_alert_levels"] == 0,
            checks["missing_health_messages"] == 0,
            checks[
                "missing_recommended_actions"
            ] == 0,
            checks[
                "negative_operational_pm25"
            ] == 0,
        ]
    )

    if not approved:
        raise AQIAlertPipelineError(
            "AQI and alert output failed validation: "
            f"{checks}"
        )

    return checks


def run_aqi_alert_pipeline(
    *,
    source_run_id: str | None = None,
) -> dict[str, Any]:
    """Run the complete Phase 6 AQI and alert pipeline."""

    started_at = datetime.now(timezone.utc)

    started_monotonic = time.monotonic()
    temporary_run_id = (
        source_run_id
        or "latest-successful-inference"
    )

    log_pipeline_started(
        LOGGER,
        pipeline_name="aqi_alert_pipeline",
        pipeline_run_id=temporary_run_id,
    )

    (
        phase_5_run_directory,
        phase_5_validation_report,
        phase_5_metadata,
    ) = resolve_inference_run(
        requested_run_id=source_run_id
    )

    forecast_df = pd.read_parquet(
        phase_5_run_directory
        / "forecast.parquet"
    )

    pm25_history_df = pd.read_parquet(
        phase_5_run_directory
        / "pm25_input.parquet"
    )

    (
        resolved_source_run_id,
        reference_time,
    ) = validate_phase_5_forecast(
        forecast_df=forecast_df,
        pm25_history_df=pm25_history_df,
        phase_5_validation_report=(
            phase_5_validation_report
        ),
        phase_5_metadata=phase_5_metadata,
    )

    enriched_forecast_df = (
        enrich_forecast_with_aqi(
            forecast_df=forecast_df,
            observed_pm25_df=pm25_history_df,
        )
    )

    alerted_forecast_df = add_aqi_alerts(
        enriched_forecast_df
    )

    alert_episodes_df = build_alert_episodes(
        alerted_forecast_df
    )

    validation_checks = validate_aqi_output(
        alerted_forecast_df=(
            alerted_forecast_df
        )
    )

    generated_at_utc = pd.Timestamp.now(
        tz="UTC"
    )

    phase_6_run_id = (
        generated_at_utc.strftime(
            "%Y%m%dT%H%M%SZ"
        )
        + "_aqi_"
        + resolved_source_run_id[-8:]
    )

    maximum_alert_row = (
        alerted_forecast_df.loc[
            alerted_forecast_df[
                "alert_rank"
            ].idxmax()
        ]
    )

    maximum_rolling_aqi_row = (
        alerted_forecast_df.loc[
            alerted_forecast_df[
                "rolling_24h_pm25_aqi"
            ]
            .astype(float)
            .idxmax()
        ]
    )

    forecast_summary = {
        "phase_6_run_id": phase_6_run_id,
        "source_phase_5_run_id": (
            resolved_source_run_id
        ),
        "generated_at_utc": generated_at_utc,
        "status": "COMPLETED",
        "forecast_rows": len(
            alerted_forecast_df
        ),
        "reference_time": reference_time,
        "forecast_start": (
            alerted_forecast_df[
                "target_time"
            ].min()
        ),
        "forecast_end": (
            alerted_forecast_df[
                "target_time"
            ].max()
        ),
        "minimum_predicted_pm25": float(
            alerted_forecast_df[
                "predicted_pm25_ug_m3"
            ].min()
        ),
        "maximum_predicted_pm25": float(
            alerted_forecast_df[
                "predicted_pm25_ug_m3"
            ].max()
        ),
        "maximum_indicative_hourly_aqi": int(
            alerted_forecast_df[
                "indicative_hourly_pm25_aqi"
            ].max()
        ),
        "maximum_rolling_24h_aqi": int(
            maximum_rolling_aqi_row[
                "rolling_24h_pm25_aqi"
            ]
        ),
        "maximum_rolling_24h_category": str(
            maximum_rolling_aqi_row[
                "rolling_24h_aqi_category"
            ]
        ),
        "maximum_alert_level": str(
            maximum_alert_row["alert_level"]
        ),
        "maximum_alert_rank": int(
            maximum_alert_row["alert_rank"]
        ),
        "active_alert_rows": int(
            alerted_forecast_df[
                "alert_is_active"
            ].sum()
        ),
        "alert_episode_count": len(
            alert_episodes_df
        ),
        "hourly_fallback_rows": int(
            alerted_forecast_df[
                "alert_used_hourly_fallback"
            ].sum()
        ),
    }

    metadata = {
        "phase_6_run_id": phase_6_run_id,
        "source_phase_5_run_id": (
            resolved_source_run_id
        ),
        "generated_at_utc": generated_at_utc,
        "project": {
            "name": phase_5_metadata.get(
                "project_name"
            ),
            "location": str(
                alerted_forecast_df[
                    "location_name"
                ].iloc[0]
            ),
            "sensor_id": int(
                alerted_forecast_df[
                    "sensor_id"
                ].iloc[0]
            ),
        },
        "aqi_standard": {
            "name": AQI_STANDARD_NAME,
            "version": AQI_STANDARD_VERSION,
            "pollutant": "PM2.5",
            "unit": "µg/m³",
            "official_averaging_period": (
                "24-hour"
            ),
            "concentration_processing": (
                "Truncated to one decimal place"
            ),
            "hourly_interpretation": (
                "Indicative only"
            ),
        },
        "alert_policy": {
            "preferred_basis": (
                "rolling_24h_pm25_aqi"
            ),
            "fallback_basis": (
                "indicative_hourly_pm25_aqi"
            ),
            "active_from_category": (
                "Unhealthy for Sensitive Groups"
            ),
        },
        "breakpoints": [
            {
                "concentration_low": (
                    breakpoint
                    .concentration_low
                ),
                "concentration_high": (
                    breakpoint
                    .concentration_high
                ),
                "aqi_low": (
                    breakpoint.aqi_low
                ),
                "aqi_high": (
                    breakpoint.aqi_high
                ),
                "category": (
                    breakpoint.category
                ),
                "color_name": (
                    breakpoint.color_name
                ),
                "color_hex": (
                    breakpoint.color_hex
                ),
            }
            for breakpoint
            in PM25_AQI_BREAKPOINTS
        ],
    }

    validation_report = {
        "status": "AQI_ALERT_PIPELINE_APPROVED",
        "phase_6_run_id": phase_6_run_id,
        "source_phase_5_run_id": (
            resolved_source_run_id
        ),
        "validated_at_utc": (
            pd.Timestamp.now(tz="UTC")
        ),
        "checks": validation_checks,
        "limitations": [
            (
                "Indicative hourly AQI is not an "
                "official regulatory daily AQI."
            ),
            (
                "Rolling 24-hour AQI combines observed "
                "and forecast PM2.5 values."
            ),
            (
                "Alert accuracy depends on the underlying "
                "PM2.5 forecast accuracy."
            ),
        ],
    }

    saved_run = save_aqi_run(
        run_id=phase_6_run_id,
        forecast_df=alerted_forecast_df,
        alert_episodes_df=alert_episodes_df,
        forecast_summary=forecast_summary,
        metadata=metadata,
        validation_report=validation_report,
    )

    # Publish only after every validation and save step succeeds.
    publish_latest_aqi_run(
        saved_run
    )

    completed_at = datetime.now(timezone.utc)

    log_pipeline_completed(
        LOGGER,
        pipeline_name="aqi_alert_pipeline",
        pipeline_run_id=phase_6_run_id,
        duration_seconds=(
            time.monotonic()
            - started_monotonic
        ),
        row_count=len(
            alerted_forecast_df
        ),
    )

    return {
        "phase": "6",
        "pipeline_name": "aqi_alert_pipeline",
        "phase_6_run_id": phase_6_run_id,
        "source_phase_5_run_id": (
            resolved_source_run_id
        ),
        "status": "AQI_ALERT_PIPELINE_COMPLETED",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": completed_at.isoformat(),
        "duration_seconds": (
            completed_at - started_at
        ).total_seconds(),
        "forecast_rows": len(
            alerted_forecast_df
        ),
        "active_alert_rows": int(
            alerted_forecast_df[
                "alert_is_active"
            ].sum()
        ),
        "alert_episode_count": len(
            alert_episodes_df
        ),
        "maximum_alert_level": str(
            maximum_alert_row["alert_level"]
        ),
        "run_directory": str(
            saved_run.run_directory
        ),
        "latest_directory": str(
            saved_run.latest_directory
        ),
        "validation_status": (
            validation_report["status"]
        ),
    }


def save_pipeline_report(
    report: dict[str, Any],
) -> Path:
    """Save the latest Phase 6 operational report."""

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
            "Run PM2.5 AQI enrichment and "
            "hazardous-condition alert generation."
        )
    )

    parser.add_argument(
        "--source-run-id",
        default=None,
        help=(
            "Optional exact Phase 5 pipeline run ID. "
            "When omitted, the newest successful run "
            "is selected."
        ),
    )

    arguments = parser.parse_args()

    try:
        report = run_aqi_alert_pipeline(
            source_run_id=(
                arguments.source_run_id
            )
        )

        exit_code = 0

    except Exception as error:

        log_pipeline_failed(
            LOGGER,
            pipeline_name="aqi_alert_pipeline",
            pipeline_run_id=(
                arguments.source_run_id
                or "unresolved"
            ),
            error_code=(
                error_codes.AQI_PIPELINE_FAILED
            ),
            error=error,
        )

        report = {
            "phase": "6",
            "pipeline_name": (
                "aqi_alert_pipeline"
            ),
            "status": (
                "AQI_ALERT_PIPELINE_FAILED"
            ),
            "failed_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "source_run_id": (
                arguments.source_run_id
            ),
            "error_type": (
                type(error).__name__
            ),
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