"""Persistence utilities for reproducible live inference runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import Settings, settings


class InferenceRunSaveError(RuntimeError):
    """Raised when inference-run artifacts cannot be saved safely."""


@dataclass(frozen=True)
class SavedInferenceRun:
    """Paths and identity of one persisted inference run."""

    run_id: str
    run_directory: Path
    forecast_parquet_path: Path
    forecast_csv_path: Path
    feature_matrix_path: Path
    pm25_input_path: Path
    weather_input_path: Path
    metadata_path: Path
    validation_report_path: Path
    forecast_plot_path: Path


def _write_json(
    payload: dict[str, Any],
    path: Path,
) -> None:
    """Write a JSON object using a temporary file and atomic replace."""

    temporary_path = path.with_suffix(
        path.suffix + ".tmp"
    )

    try:
        with temporary_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                payload,
                file,
                indent=2,
                ensure_ascii=False,
                default=str,
            )

        temporary_path.replace(path)
    except Exception as exc:
        temporary_path.unlink(
            missing_ok=True
        )

        raise InferenceRunSaveError(
            f"Could not save JSON artifact: {path}"
        ) from exc


def save_inference_run(
    *,
    run_id: str,
    forecast_df: pd.DataFrame,
    feature_matrix_df: pd.DataFrame,
    pm25_input_df: pd.DataFrame,
    weather_input_df: pd.DataFrame,
    run_metadata: dict[str, Any],
    validation_report: dict[str, Any],
    app_settings: Settings = settings,
) -> SavedInferenceRun:
    """
    Save one reproducible inference run.

    Existing run directories are not overwritten.
    """

    cleaned_run_id = run_id.strip()

    if not cleaned_run_id:
        raise InferenceRunSaveError(
            "run_id cannot be empty."
        )

    if "/" in cleaned_run_id or "\\" in cleaned_run_id:
        raise InferenceRunSaveError(
            "run_id cannot contain path separators."
        )

    required_dataframes = {
        "forecast": forecast_df,
        "feature matrix": feature_matrix_df,
        "PM2.5 input": pm25_input_df,
        "weather input": weather_input_df,
    }

    empty_artifacts = [
        artifact_name
        for artifact_name, dataframe
        in required_dataframes.items()
        if dataframe.empty
    ]

    if empty_artifacts:
        raise InferenceRunSaveError(
            "Cannot save empty inference artifacts: "
            f"{empty_artifacts}"
        )

    runs_directory = (
        app_settings.inference_dir
        / "runs"
    )

    runs_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    run_directory = (
        runs_directory
        / cleaned_run_id
    )

    if run_directory.exists():
        raise InferenceRunSaveError(
            "Inference run already exists and will not be "
            f"overwritten: {run_directory}"
        )

    run_directory.mkdir(
        parents=False,
        exist_ok=False,
    )

    forecast_parquet_path = (
        run_directory / "forecast.parquet"
    )

    forecast_csv_path = (
        run_directory / "forecast.csv"
    )

    feature_matrix_path = (
        run_directory / "feature_matrix.parquet"
    )

    pm25_input_path = (
        run_directory / "pm25_input.parquet"
    )

    weather_input_path = (
        run_directory / "weather_input.parquet"
    )

    metadata_path = (
        run_directory / "run_metadata.json"
    )

    validation_report_path = (
        run_directory / "validation_report.json"
    )

    forecast_plot_path = (
        run_directory / "forecast_plot.png"
    )

    try:
        forecast_df.to_parquet(
            forecast_parquet_path,
            index=False,
        )

        forecast_df.to_csv(
            forecast_csv_path,
            index=False,
        )

        feature_matrix_df.to_parquet(
            feature_matrix_path,
            index=False,
        )

        pm25_input_df.to_parquet(
            pm25_input_path,
            index=False,
        )

        weather_input_df.to_parquet(
            weather_input_path,
            index=False,
        )

        _write_json(
            run_metadata,
            metadata_path,
        )

        _write_json(
            validation_report,
            validation_report_path,
        )
    except Exception as exc:
        for artifact_path in run_directory.iterdir():
            artifact_path.unlink(
                missing_ok=True
            )

        run_directory.rmdir()

        if isinstance(
            exc,
            InferenceRunSaveError,
        ):
            raise

        raise InferenceRunSaveError(
            "Could not save inference-run artifacts."
        ) from exc

    return SavedInferenceRun(
        run_id=cleaned_run_id,
        run_directory=run_directory,
        forecast_parquet_path=(
            forecast_parquet_path
        ),
        forecast_csv_path=forecast_csv_path,
        feature_matrix_path=feature_matrix_path,
        pm25_input_path=pm25_input_path,
        weather_input_path=weather_input_path,
        metadata_path=metadata_path,
        validation_report_path=(
            validation_report_path
        ),
        forecast_plot_path=forecast_plot_path,
    )