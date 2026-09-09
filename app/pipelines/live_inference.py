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
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from app.core.config import settings
from app.data.pm25_gap_policy import (
    recover_short_pm25_gaps,
)
from app.data.validation import (
    select_latest_safe_reference_time,
)
from app.data_sources.open_meteo_client import (
    OpenMeteoClient,
)
from app.data_sources.openaq_client import (
    OpenAQClient,
    OpenAQClientError,
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
from app.mlops.config import (
    MLOpsSettings,
)
from app.mlops.contracts import (
    build_feature_group_contracts,
)
from app.mlops.feature_repository import (
    create_feature_repository,
)
from app.observability.logging import (
    configure_structured_logging,
    log_pipeline_completed,
    log_pipeline_failed,
    log_pipeline_started,
)
from app.pipelines.hourly_features import (
    build_recent_canonical_window,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

REPORT_PATH = (
    PROJECT_ROOT / "reports" / "phase_10" / "live_inference_pipeline_report.json"
)


LOGGER = configure_structured_logging(
    service_name="pearls-aqi-live-inference",
)


class LiveInferencePipelineError(RuntimeError):
    """Raised when live inference cannot complete safely."""


def utc_now() -> pd.Timestamp:
    """Return the current timezone-aware UTC timestamp."""

    return pd.Timestamp.now(tz="UTC")


def generate_pipeline_run_id() -> str:
    """Generate one unique and traceable pipeline-run ID."""

    return utc_now().strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]


def _build_feature_repository():
    """
    Create the configured feature repository.

    Used only for PM2.5 fallback reads when OpenAQ
    is temporarily unavailable.
    """

    mlops_settings = MLOpsSettings()

    contracts = build_feature_group_contracts(
        pm25_version=1,
        weather_version=1,
        engineered_version=2,
        pm25_name="pm25_hourly_observations",
        weather_name="weather_hourly_observations",
        engineered_name="pm25_hourly_features",
        model_feature_columns=[],
    )

    return create_feature_repository(
        settings=mlops_settings,
        contracts=contracts,
    ), contracts


def _load_pm25_from_feature_store() -> pd.DataFrame:
    """
    Load the latest available PM2.5 observations
    from the configured feature repository.

    This is used only when live OpenAQ ingestion fails.
    """

    repository, contracts = _build_feature_repository()

    pm25_contract = contracts["pm25"]

    latest_event_time = repository.latest_event_time(
        contract=pm25_contract,
    )

    if latest_event_time is None:
        raise LiveInferencePipelineError(
            "OpenAQ failed and no PM2.5 fallback data exists."
        )

    fallback_start = latest_event_time - pd.Timedelta(hours=72)

    fallback_end = latest_event_time + pd.Timedelta(hours=1)

    dataframe = repository.read_range(
        contract=pm25_contract,
        start_time_utc=fallback_start,
        end_time_exclusive_utc=fallback_end,
    )

    if dataframe.empty:
        raise LiveInferencePipelineError(
            "OpenAQ failed and PM2.5 fallback dataset is empty."
        )

    return dataframe[
        [
            "datetime_utc",
            "pm25_ug_m3",
        ]
    ].copy()


def run_live_inference(
    *,
    pipeline_run_id: str | None = None,
) -> dict[str, Any]:
    """
    Execute one complete live inference run.

    OpenAQ is preferred as the live PM2.5 source.
    If OpenAQ is temporarily unavailable, the latest
    available PM2.5 history from the feature repository
    is used and the run continues with degraded quality.
    """

    started_at = utc_now()

    run_id = (
        pipeline_run_id if pipeline_run_id is not None else generate_pipeline_run_id()
    )

    log_pipeline_started(
        LOGGER,
        pipeline_name="live_inference_pipeline",
        pipeline_run_id=run_id,
    )

    try:
        model_artifacts = load_model_artifacts()

        openaq_client = OpenAQClient(
            app_settings=settings,
        )

        weather_client = OpenMeteoClient(
            app_settings=settings,
        )

        pm25_source_status = "LIVE"

        try:
            recent_pm25_df = openaq_client.fetch_recent_hourly_pm25()

        except OpenAQClientError as error:
            LOGGER.warning(
                "OpenAQ PM2.5 fetch failed. Using feature repository fallback.",
                extra={
                    "error": str(error),
                },
            )

            recent_pm25_df = _load_pm25_from_feature_store()

            pm25_source_status = "STALE"

        weather_df = weather_client.fetch_hourly_weather()

        pm25_recovery = recover_short_pm25_gaps(
            recent_pm25_df,
        )

        recovered_pm25_df = pm25_recovery.dataframe

        reference_selection = select_latest_safe_reference_time(
            recovered_pm25_df,
            weather_df,
        )

        if not reference_selection.is_ready:
            raise LiveInferencePipelineError(
                "Live feature inputs are not ready. "
                f"Status={reference_selection.status}. "
                f"Message={reference_selection.message}"
            )

        reference_time = reference_selection.selected_reference_time

        if reference_time is None:
            raise LiveInferencePipelineError(
                "Reference selection returned no timestamp."
            )

        canonical_df = build_recent_canonical_window(
            pm25_df=recovered_pm25_df,
            weather_df=weather_df,
        )

        reference_features = build_reference_feature_table(
            canonical_hourly_df=canonical_df,
        )

        target_weather_features = build_target_weather_feature_table(
            canonical_hourly_df=weather_df,
        )

        feature_table = build_feature_rows(
            reference_feature_df=reference_features,
            target_weather_feature_df=target_weather_features,
            reference_times=[reference_time],
            forecast_horizons=list(
                range(
                    1,
                    settings.forecast_horizon_hours + 1,
                )
            ),
            model_feature_columns=model_artifacts.feature_columns,
        )
        validate_feature_matrix(
            feature_table,
            model_artifacts,
        )

        predictions = generate_hybrid_predictions(
            feature_table,
            model_artifacts,
        )

        completed_at = utc_now()

        predictions["pipeline_run_id"] = run_id

        predictions["prediction_generated_at_utc"] = completed_at.isoformat()

        predictions["reference_time"] = reference_time.isoformat()

        predictions["target_time"] = pd.to_datetime(
            predictions["reference_time"],
            utc=True,
        ) + pd.to_timedelta(
            predictions["forecast_horizon_hours"],
            unit="h",
        )

        predictions["location_name"] = settings.location_name

        predictions["sensor_id"] = settings.openaq_sensor_id

        predictions["selected_strategy"] = "hybrid"

        saved_run = save_inference_run(
            run_id=run_id,
            forecast_df=predictions,
            feature_matrix_df=feature_table,
            pm25_input_df=recovered_pm25_df,
            weather_input_df=weather_df,
            run_metadata={
                "pipeline_run_id": run_id,
                "pm25_source_status": pm25_source_status,
                "reference_time": reference_time.isoformat(),
                "latest_pm25_time": recovered_pm25_df["datetime_utc"].max().isoformat(),
            },
            validation_report={
                "status": "PASSED",
                "reference_selection_status": reference_selection.status,
                "reference_selection_message": reference_selection.message,
                "reference_time": reference_time.isoformat(),
                "prediction_rows": len(predictions),
            },
        )

        result = {
            "pipeline_run_id": run_id,
            "status": "LIVE_INFERENCE_COMPLETED",
            "validation_status": "PASSED",
            "started_at_utc": started_at.isoformat(),
            "completed_at_utc": completed_at.isoformat(),
            "duration_seconds": (completed_at - started_at).total_seconds(),
            "pm25_source_status": pm25_source_status,
            "reference_time": reference_time.isoformat(),
            "latest_pm25_time": recovered_pm25_df["datetime_utc"].max().isoformat(),
            "prediction_rows": len(predictions),
            "forecast_rows": len(predictions),
            "run_directory": str(saved_run.run_directory),
            "predictions": predictions.to_dict(orient="records"),
        }

        log_pipeline_completed(
            LOGGER,
            pipeline_name="live_inference_pipeline",
            pipeline_run_id=run_id,
            duration_seconds=(utc_now() - started_at).total_seconds(),
        )

        return result

    except Exception as error:
        log_pipeline_failed(
            LOGGER,
            pipeline_name="live_inference_pipeline",
            pipeline_run_id=run_id,
            error=error,
            error_code="LIVE_INFERENCE_FAILED",
        )

        raise


def build_live_inference_report(
    *,
    inference_result: dict[str, Any],
) -> dict[str, Any]:
    """
    Build the persisted Phase 10 live inference report.
    """

    return {
        "phase": "5",
        "subphase": "5-A",
        "pipeline_name": "live_inference_pipeline",
        "status": inference_result.get(
            "status",
            "UNKNOWN",
        ),
        "generated_at_utc": utc_now().isoformat(),
        "pipeline_run_id": inference_result.get(
            "pipeline_run_id",
        ),
        "pm25_source_status": inference_result.get(
            "pm25_source_status",
        ),
        "reference_time": inference_result.get(
            "reference_time",
        ),
        "latest_pm25_time": inference_result.get(
            "latest_pm25_time",
        ),
        "prediction_rows": inference_result.get(
            "prediction_rows",
        ),
    }


def save_live_inference_report(
    report: dict[str, Any],
) -> None:
    """
    Save the live inference report locally.
    """

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


def parse_arguments() -> argparse.Namespace:
    """
    Parse CLI arguments.
    """

    parser = argparse.ArgumentParser(
        description=("Run Pearls AQI live inference pipeline.")
    )

    parser.add_argument(
        "--pipeline-run-id",
        required=False,
        default=None,
        help="Optional external pipeline run ID.",
    )

    return parser.parse_args()


def main() -> None:
    """
    CLI entrypoint.
    """

    arguments = parse_arguments()

    started = time.time()

    try:
        result = run_live_inference(
            pipeline_run_id=(arguments.pipeline_run_id),
        )

        report = build_live_inference_report(
            inference_result=result,
        )

        save_live_inference_report(
            report,
        )

        print(
            json.dumps(
                report,
                indent=2,
                default=str,
            )
        )

    except Exception as error:
        failure_report = {
            "phase": "5",
            "subphase": "5-A",
            "pipeline_name": ("live_inference_pipeline"),
            "status": ("LIVE_INFERENCE_FAILED"),
            "failed_at_utc": (utc_now().isoformat()),
            "error_type": type(error).__name__,
            "error_message": str(error),
            "duration_seconds": (time.time() - started),
        }

        save_live_inference_report(
            failure_report,
        )

        print(
            json.dumps(
                failure_report,
                indent=2,
                default=str,
            )
        )

        raise


if __name__ == "__main__":
    main()
