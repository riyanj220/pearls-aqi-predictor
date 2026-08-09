"""Incrementally synchronize validated features with Hopsworks."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.mlops.config import (
    MLOpsSettings,
    get_mlops_settings,
)
from app.mlops.contracts import (
    FeatureGroupContract,
    build_feature_group_contracts,
)
from app.pipelines.historical_backfill import (
    classify_rows,
    load_feature_columns,
    order_for_contract,
    prepare_engineered_rows,
    prepare_pm25_rows,
    prepare_weather_rows,

)

from app.mlops.feature_repository import (
    FeatureRepository,
    FeatureRepositoryError,
    create_feature_repository,
    empty_feature_frame,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class IncrementalFeatureError(RuntimeError):
    """Raised when incremental synchronization cannot complete."""


def normalize_utc_hour(
    value: object,
) -> pd.Timestamp:
    """Normalize a timestamp into one timezone-aware UTC hour."""

    timestamp = pd.Timestamp(value)

    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")

    return timestamp.floor("h")


def get_dataframe_event_range(
    *,
    dataframe: pd.DataFrame,
    event_time_column: str,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return minimum and maximum valid event times."""

    if dataframe.empty:
        raise IncrementalFeatureError(
            f"No rows are available for {event_time_column}."
        )

    event_times = pd.to_datetime(
        dataframe[event_time_column],
        utc=True,
        errors="coerce",
    ).dropna()

    if event_times.empty:
        raise IncrementalFeatureError(
            f"No valid event times exist in {event_time_column}."
        )

    return (
        event_times.min().floor("h"),
        event_times.max().floor("h"),
    )


def get_latest_stored_event_time(
    *,
    repository: FeatureRepository,
    contract: FeatureGroupContract,
) -> pd.Timestamp | None:
    """Return the latest stored event time."""

    try:
        return repository.latest_event_time(
            contract=contract
        )
    except FeatureRepositoryError as error:
        raise IncrementalFeatureError(
            f"Could not inspect stored dataset "
            f"{contract.name}."
        ) from error

def calculate_incremental_start(
    *,
    latest_stored_time: pd.Timestamp | None,
    local_start_time: pd.Timestamp,
    local_end_time: pd.Timestamp,
    overlap_hours: int,
    initial_lookback_hours: int,
) -> pd.Timestamp:
    """Calculate the inclusive synchronization start time."""

    if latest_stored_time is not None:
        start_time = (
            latest_stored_time
            - pd.Timedelta(
                hours=overlap_hours
            )
        )

        return max(
            local_start_time,
            start_time,
        )

    initial_start = (
        local_end_time
        - pd.Timedelta(
            hours=initial_lookback_hours - 1
        )
    )

    return max(
        local_start_time,
        initial_start,
    )


def filter_incremental_rows(
    *,
    dataframe: pd.DataFrame,
    event_time_column: str,
    start_time_utc: pd.Timestamp,
    end_time_utc: pd.Timestamp,
) -> pd.DataFrame:
    """Filter rows using inclusive local boundaries."""

    event_times = pd.to_datetime(
        dataframe[event_time_column],
        utc=True,
        errors="coerce",
    )

    return dataframe.loc[
        event_times.between(
            start_time_utc,
            end_time_utc,
            inclusive="both",
        )
    ].copy()


def synchronize_group(
    *,
    dataframe: pd.DataFrame,
    repository: FeatureRepository,
    contract: FeatureGroupContract,
    settings: MLOpsSettings,
) -> dict[str, Any]:
    """Synchronize one prepared feature-group DataFrame."""

    local_start, local_end = (
        get_dataframe_event_range(
            dataframe=dataframe,
            event_time_column=(
                contract.event_time
            ),
        )
    )

    latest_stored_time = (
        get_latest_stored_event_time(
            repository=repository,
            contract=contract,
        )
    )

    incremental_start = (
        calculate_incremental_start(
            latest_stored_time=(
                latest_stored_time
            ),
            local_start_time=local_start,
            local_end_time=local_end,
            overlap_hours=(
                settings
                .incremental_overlap_hours
            ),
            initial_lookback_hours=(
                settings
                .incremental_initial_lookback_hours
            ),
        )
    )

    candidate = filter_incremental_rows(
        dataframe=dataframe,
        event_time_column=(
            contract.event_time
        ),
        start_time_utc=incremental_start,
        end_time_utc=local_end,
    )

    candidate = order_for_contract(
        candidate,
        contract,
    )

    end_exclusive = (
        local_end
        + pd.Timedelta(hours=1)
    )

    try:
        existing = repository.read_range(
            contract=contract,
            start_time_utc=incremental_start,
            end_time_exclusive_utc=end_exclusive,
        )

    except FeatureRepositoryError:
        # Preserve the previous synchronization behavior:
        # an unavailable overlap read is treated as no
        # existing rows for classification.
        existing = empty_feature_frame(
            contract
        )

    classification = classify_rows(
        candidate=candidate,
        existing=existing,
        contract=contract,
    )

    if (
        not settings.mlops_dry_run
        and not classification.writable.empty
    ):
        repository.upsert(
            contract=contract,
            dataframe=classification.writable,
        )

    return {
        "feature_group_name": contract.name,
        "version": contract.version,
        "event_time_column": (
            contract.event_time
        ),
        "latest_stored_event_time_before_run": (
            latest_stored_time.isoformat()
            if latest_stored_time is not None
            else None
        ),
        "local_available_start": (
            local_start.isoformat()
        ),
        "local_available_end": (
            local_end.isoformat()
        ),
        "incremental_start": (
            incremental_start.isoformat()
        ),
        "incremental_end": (
            local_end.isoformat()
        ),
        "overlap_hours": (
            settings.incremental_overlap_hours
        ),
        "candidate_rows": int(
            len(candidate)
        ),
        "existing_rows_in_window": int(
            len(existing)
        ),
        "rows_to_insert": (
            classification.inserted
        ),
        "rows_to_update": (
            classification.updated
        ),
        "rows_unchanged": (
            classification.unchanged
        ),
        "rows_written": (
            0
            if settings.mlops_dry_run
            else int(
                len(
                    classification.writable
                )
            )
        ),
        "duplicate_keys": int(
            candidate.duplicated(
                subset=list(
                    dict.fromkeys(
                        [
                            *contract.primary_key,
                            contract.event_time,
                        ]
                    )
                )
            ).sum()
        ),
    }


def run_incremental_feature_pipeline(
    *,
    settings: MLOpsSettings,
) -> dict[str, Any]:
    """Synchronize PM2.5, weather and engineered features."""

    started_at = datetime.now(
        timezone.utc
    )

    pipeline_run_id = (
        "incremental_features_"
        + uuid.uuid4().hex
    )

    canonical_path = (
        PROJECT_ROOT
        / settings.phase_1_canonical_dataset_path
    )

    training_path = (
        PROJECT_ROOT
        / settings.phase_2_training_dataset_path
    )

    feature_columns_path = (
        PROJECT_ROOT
        / "models"
        / "model_feature_columns.json"
    )

    required_paths = [
        canonical_path,
        training_path,
        feature_columns_path,
    ]

    missing_paths = [
        str(path)
        for path in required_paths
        if not path.exists()
    ]

    if missing_paths:
        raise FileNotFoundError(
            "Required incremental artifacts "
            f"are missing: {missing_paths}"
        )

    canonical_df = pd.read_parquet(
        canonical_path
    )

    training_df = pd.read_parquet(
        training_path
    )

    model_feature_columns = (
        load_feature_columns(
            feature_columns_path
        )
    )

    contracts = build_feature_group_contracts(
        pm25_version=(
            settings
            .hopsworks_pm25_feature_group_version
        ),
        weather_version=(
            settings
            .hopsworks_weather_feature_group_version
        ),
        engineered_version=(
            settings
            .hopsworks_engineered_feature_group_version
        ),
        pm25_name=(
            settings.hopsworks_pm25_feature_group_name
        ),
        weather_name=(
            settings.hopsworks_weather_feature_group_name
        ),
        engineered_name=(
            settings
            .hopsworks_engineered_feature_group_name
        ),
        model_feature_columns=(
            model_feature_columns
        ),
    )

    prepared_at = pd.Timestamp.now(
        tz="UTC"
    )

    prepared_rows = {
        "pm25": prepare_pm25_rows(
            canonical_df=canonical_df,
            retrieved_at_utc=prepared_at,
            pipeline_run_id=pipeline_run_id,
            source_data_version=(
                settings.source_data_version
            ),
        ),
        "weather": prepare_weather_rows(
            canonical_df=canonical_df,
            retrieved_at_utc=prepared_at,
            pipeline_run_id=pipeline_run_id,
            source_data_version=(
                settings.source_data_version
            ),
        ),
        "engineered": prepare_engineered_rows(
            training_df=training_df,
            contract=contracts["engineered"],
            pipeline_run_id=pipeline_run_id,
            feature_pipeline_version=(
                settings.feature_pipeline_version
            ),
        ),
    }

    repository = create_feature_repository(
        settings=settings,
        contracts=contracts,
    )

    group_reports: dict[str, Any] = {}

    for group_name in (
        "pm25",
        "weather",
        "engineered",
    ):
        group_reports[group_name] = (
           synchronize_group(
                dataframe=prepared_rows[
                    group_name
                ],
                repository=repository,
                contract=contracts[
                    group_name
                ],
                settings=settings,
            )
        )

    completed_at = datetime.now(
        timezone.utc
    )

    total_rows_written = sum(
        group_report["rows_written"]
        for group_report
        in group_reports.values()
    )

    return {
        "phase": "9H",
        "pipeline_run_id": pipeline_run_id,
        "pipeline_name": (
            "incremental_feature_sync"
        ),
        "status": (
            "INCREMENTAL_SYNC_DRY_RUN_SUCCESS"
            if settings.mlops_dry_run
            else "INCREMENTAL_SYNC_SUCCESS"
        ),
        "started_at_utc": (
            started_at.isoformat()
        ),
        "completed_at_utc": (
            completed_at.isoformat()
        ),
        "dry_run": settings.mlops_dry_run,
        "remote_writes_performed": (
            not settings.mlops_dry_run
            and total_rows_written > 0
        ),
        "canonical_dataset_path": (
            canonical_path.relative_to(
                PROJECT_ROOT
            ).as_posix()
        ),
        "training_dataset_path": (
            training_path.relative_to(
                PROJECT_ROOT
            ).as_posix()
        ),
        "total_rows_written": (
            total_rows_written
        ),
        "groups": group_reports,
        "feature_repository_backend": (
            repository.backend_name
        ),
    }


def save_incremental_report(
    report: dict[str, Any],
) -> Path:
    """Save the latest incremental synchronization report."""

    report_path = (
        PROJECT_ROOT
        / "reports"
        / "phase_9"
        / "incremental_feature_report.json"
    )

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    return report_path


def main() -> int:
    """CLI entry point."""

    parser = argparse.ArgumentParser(
        description=(
            "Incrementally synchronize validated "
            "features with Hopsworks."
        )
    )

    parser.parse_args()

    try:
        settings = get_mlops_settings()

        report = (
            run_incremental_feature_pipeline(
                settings=settings
            )
        )

        exit_code = 0

    except Exception as error:
        report = {
            "phase": "9H",
            "pipeline_name": (
                "incremental_feature_sync"
            ),
            "status": (
                "INCREMENTAL_SYNC_FAILED"
            ),
            "completed_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(error),
        }

        exit_code = 1

    report_path = save_incremental_report(
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