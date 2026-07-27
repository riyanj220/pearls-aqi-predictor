"""Persistence utilities for Phase 6 AQI and alert artifacts."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import PROJECT_ROOT


class AQIRunSaveError(RuntimeError):
    """Raised when AQI run artifacts cannot be saved safely."""


@dataclass(frozen=True)
class SavedAQIRun:
    """Paths belonging to one saved Phase 6 run."""

    run_id: str
    run_directory: Path
    latest_directory: Path
    forecast_path: Path
    alert_episodes_path: Path
    summary_path: Path
    metadata_path: Path
    validation_report_path: Path
    plot_path: Path


def _write_json(
    payload: Any,
    path: Path,
) -> None:
    """Write JSON using a temporary file and atomic replacement."""

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

        raise AQIRunSaveError(
            f"Could not save JSON artifact: {path}"
        ) from exc


def _refresh_latest_directory(
    *,
    source_directory: Path,
    latest_directory: Path,
) -> None:
    """Replace latest outputs with files from the completed run."""

    latest_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    for existing_path in latest_directory.iterdir():
        if existing_path.name == ".gitkeep":
            continue

        if existing_path.is_file():
            existing_path.unlink()
        elif existing_path.is_dir():
            shutil.rmtree(existing_path)

    for source_path in source_directory.iterdir():
        if source_path.is_file():
            shutil.copy2(
                source_path,
                latest_directory / source_path.name,
            )


def save_aqi_run(
    *,
    run_id: str,
    forecast_df: pd.DataFrame,
    alert_episodes_df: pd.DataFrame,
    forecast_summary: dict[str, Any],
    metadata: dict[str, Any],
    validation_report: dict[str, Any],
    output_root: Path | None = None,
) -> SavedAQIRun:
    """
    Save one immutable Phase 6 run and update latest outputs.

    Existing run directories are never overwritten.
    """

    cleaned_run_id = run_id.strip()

    if not cleaned_run_id:
        raise AQIRunSaveError(
            "run_id cannot be empty."
        )

    if "/" in cleaned_run_id or "\\" in cleaned_run_id:
        raise AQIRunSaveError(
            "run_id cannot contain path separators."
        )

    if forecast_df.empty:
        raise AQIRunSaveError(
            "AQI forecast cannot be empty."
        )

    aqi_root = (
        output_root
        if output_root is not None
        else PROJECT_ROOT / "aqi"
    )

    runs_directory = aqi_root / "runs"
    latest_directory = aqi_root / "latest"

    runs_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    latest_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    run_directory = (
        runs_directory / cleaned_run_id
    )

    if run_directory.exists():
        raise AQIRunSaveError(
            "AQI run already exists and will not be overwritten: "
            f"{run_directory}"
        )

    run_directory.mkdir(
        parents=False,
        exist_ok=False,
    )

    forecast_path = (
        run_directory
        / "live_pm25_aqi_forecast.parquet"
    )

    alert_episodes_path = (
        run_directory
        / "alert_episodes.json"
    )

    summary_path = (
        run_directory
        / "aqi_forecast_summary.json"
    )

    metadata_path = (
        run_directory
        / "aqi_metadata.json"
    )

    validation_report_path = (
        run_directory
        / "phase_6_validation_report.json"
    )

    plot_path = (
        run_directory
        / "aqi_forecast_plot.png"
    )

    try:
        forecast_df.to_parquet(
            forecast_path,
            index=False,
        )

        _write_json(
            alert_episodes_df.to_dict(
                orient="records"
            ),
            alert_episodes_path,
        )

        _write_json(
            forecast_summary,
            summary_path,
        )

        _write_json(
            metadata,
            metadata_path,
        )

        _write_json(
            validation_report,
            validation_report_path,
        )

    except Exception as exc:
        shutil.rmtree(
            run_directory,
            ignore_errors=True,
        )

        if isinstance(exc, AQIRunSaveError):
            raise

        raise AQIRunSaveError(
            "Could not save Phase 6 AQI artifacts."
        ) from exc

    return SavedAQIRun(
        run_id=cleaned_run_id,
        run_directory=run_directory,
        latest_directory=latest_directory,
        forecast_path=forecast_path,
        alert_episodes_path=alert_episodes_path,
        summary_path=summary_path,
        metadata_path=metadata_path,
        validation_report_path=(
            validation_report_path
        ),
        plot_path=plot_path,
    )


def publish_latest_aqi_run(
    saved_run: SavedAQIRun,
) -> None:
    """Publish a completed and validated run as the latest output."""

    _refresh_latest_directory(
        source_directory=(
            saved_run.run_directory
        ),
        latest_directory=(
            saved_run.latest_directory
        ),
    )