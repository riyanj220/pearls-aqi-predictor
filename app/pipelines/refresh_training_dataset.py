"""Build fresh retraining datasets from production feature datasets.

The pipeline reads:

- validated PM2.5 observations;
- validated historical weather observations;
- reusable reference-time engineered features.

It then recreates the approved Phase 2 direct multi-horizon training
dataset without depending on the static Phase 2 Parquet files.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.core.config import PROJECT_ROOT
from app.mlops.config import (
    MLOpsSettings,
    get_mlops_settings,
)
from app.mlops.contracts import (
    FeatureGroupContract,
    build_feature_group_contracts,
)
from app.pipelines.historical_backfill import (
    load_feature_columns,
)

from app.mlops.feature_repository import (
    FeatureRepository,
    create_feature_repository,
)


REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "training_dataset_refresh_report.json"
)

DEFAULT_OUTPUT_ROOT = (
    PROJECT_ROOT
    / "data"
    / "training"
    / "runtime"
)

FORECAST_HORIZONS = tuple(range(1, 73))
MAX_FORECAST_HORIZON_HOURS = 72

TARGET_COLUMN = "target_pm25_ug_m3"

WEATHER_CONTRACT_TO_MODEL_COLUMNS = {
    "temperature_2m_c": "temperature_2m",
    "relative_humidity_2m_pct": (
        "relative_humidity_2m"
    ),
    "dew_point_2m_c": "dew_point_2m",
    "surface_pressure_hpa": "surface_pressure",
    "precipitation_mm": "precipitation",
    "rain_mm": "rain",
    "cloud_cover_pct": "cloud_cover",
    "wind_speed_10m_kmh": "wind_speed_10m",
    "wind_direction_10m_deg": (
        "wind_direction_10m"
    ),
    "wind_gusts_10m_kmh": "wind_gusts_10m",
}

WEATHER_COLUMNS = tuple(
    WEATHER_CONTRACT_TO_MODEL_COLUMNS.values()
)


class TrainingDatasetRefreshError(
    RuntimeError
):
    """Raised when runtime training data cannot be built."""


def generate_run_id() -> str:
    """Generate one immutable training-refresh run ID."""

    return (
        datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ"
        )
        + "_training_refresh_"
        + uuid.uuid4().hex[:8]
    )


def normalize_utc_hour(
    values: pd.Series,
) -> pd.Series:
    """Normalize timestamp values to UTC hourly precision."""

    return pd.to_datetime(
        values,
        utc=True,
        errors="raise",
    ).dt.floor("h")

def build_contracts(
    settings: MLOpsSettings,
) -> tuple[
    dict[str, FeatureGroupContract],
    list[str],
]:
    """Build configured feature-group and model contracts."""

    model_feature_path = (
        PROJECT_ROOT
        / "models"
        / "model_feature_columns.json"
    )

    if not model_feature_path.exists():
        raise FileNotFoundError(
            "Model feature contract does not exist: "
            f"{model_feature_path}"
        )

    model_feature_columns = load_feature_columns(
        model_feature_path
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
            settings
            .hopsworks_pm25_feature_group_name
        ),
        weather_name=(
            settings
            .hopsworks_weather_feature_group_name
        ),
        engineered_name=(
            settings
            .hopsworks_engineered_feature_group_name
        ),
        model_feature_columns=(
            model_feature_columns
        ),
    )

    return contracts, model_feature_columns


def read_feature_dataset(
    *,
    repository: FeatureRepository,
    contract: FeatureGroupContract,
) -> pd.DataFrame:
    """Read and normalize one complete feature dataset."""

    try:
        dataframe = (
            repository.read_dataset(
                contract=contract
            )
        )
    except Exception as error:
        raise TrainingDatasetRefreshError(
            "Could not read feature dataset "
            f"{contract.name}."
        ) from error

    if dataframe.empty:
        raise TrainingDatasetRefreshError(
            f"Feature dataset is empty: "
            f"{contract.name}"
        )

    missing_columns = sorted(
        set(
            contract.feature_names
        ).difference(
            dataframe.columns
        )
    )

    if missing_columns:
        raise TrainingDatasetRefreshError(
            f"{contract.name} is missing "
            f"columns: {missing_columns}"
        )

    result = dataframe[
        contract.feature_names
    ].copy()

    result[
        contract.event_time
    ] = normalize_utc_hour(
        result[
            contract.event_time
        ]
    )

    logical_key = list(
        dict.fromkeys(
            [
                *contract.primary_key,
                contract.event_time,
            ]
        )
    )

    return (
        result
        .sort_values(
            contract.event_time
        )
        .drop_duplicates(
            subset=logical_key,
            keep="last",
        )
        .reset_index(
            drop=True
        )
    )


def read_feature_sources(
    *,
    repository: FeatureRepository,
    contracts: dict[
        str,
        FeatureGroupContract,
    ],
) -> dict[str, pd.DataFrame]:
    """Read the latest three production feature datasets."""

    return {
        name: read_feature_dataset(
            repository=repository,
            contract=contracts[
                name
            ],
        )
        for name in (
            "pm25",
            "weather",
            "engineered",
        )
    }


def prepare_pm25_lookup(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """Prepare the unique PM2.5 target lookup."""

    result = dataframe[
        [
            "datetime_utc",
            "pm25_ug_m3",
        ]
    ].copy()

    result[
        "datetime_utc"
    ] = normalize_utc_hour(
        result["datetime_utc"]
    )

    result["pm25_ug_m3"] = pd.to_numeric(
        result["pm25_ug_m3"],
        errors="coerce",
    )

    result = (
        result.sort_values("datetime_utc")
        .drop_duplicates(
            subset=["datetime_utc"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    return result


def prepare_weather_lookup(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """Rename weather contract columns to the model schema."""

    required_columns = {
        "datetime_utc",
        *WEATHER_CONTRACT_TO_MODEL_COLUMNS,
    }

    missing_columns = sorted(
        required_columns.difference(
            dataframe.columns
        )
    )

    if missing_columns:
        raise TrainingDatasetRefreshError(
            "Weather group is missing required values: "
            f"{missing_columns}"
        )

    result = dataframe[
        [
            "datetime_utc",
            *WEATHER_CONTRACT_TO_MODEL_COLUMNS,
        ]
    ].copy()

    result = result.rename(
        columns=(
            WEATHER_CONTRACT_TO_MODEL_COLUMNS
        )
    )

    result[
        "datetime_utc"
    ] = normalize_utc_hour(
        result["datetime_utc"]
    )

    for column in WEATHER_COLUMNS:
        result[column] = pd.to_numeric(
            result[column],
            errors="coerce",
        )

    result = (
        result.sort_values("datetime_utc")
        .drop_duplicates(
            subset=["datetime_utc"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    return result


def prepare_reference_features(
    *,
    dataframe: pd.DataFrame,
    contract: FeatureGroupContract,
) -> pd.DataFrame:
    """Prepare reusable reference-time model features."""

    excluded_columns = {
        "location_key",
        "feature_pipeline_version",
        "pipeline_run_id",
    }

    selected_columns = [
        column
        for column in contract.feature_names
        if column not in excluded_columns
    ]

    result = dataframe[
        selected_columns
    ].copy()

    result[
        "reference_time"
    ] = normalize_utc_hour(
        result["reference_time"]
    )

    result = (
        result.sort_values("reference_time")
        .drop_duplicates(
            subset=["reference_time"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    return result


def add_target_time_features(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """Add the approved target-time and wind features."""

    result = dataframe.copy()

    target_time = pd.to_datetime(
        result["target_time"],
        utc=True,
        errors="raise",
    )

    result["target_hour"] = (
        target_time.dt.hour
    )

    result["target_day_of_week"] = (
        target_time.dt.dayofweek
    )

    result["target_month"] = (
        target_time.dt.month
    )

    result["target_hour_sin"] = np.sin(
        2 * np.pi
        * result["target_hour"]
        / 24
    )

    result["target_hour_cos"] = np.cos(
        2 * np.pi
        * result["target_hour"]
        / 24
    )

    result[
        "target_day_of_week_sin"
    ] = np.sin(
        2 * np.pi
        * result["target_day_of_week"]
        / 7
    )

    result[
        "target_day_of_week_cos"
    ] = np.cos(
        2 * np.pi
        * result["target_day_of_week"]
        / 7
    )

    result["target_month_sin"] = np.sin(
        2 * np.pi
        * (
            result["target_month"]
            - 1
        )
        / 12
    )

    result["target_month_cos"] = np.cos(
        2 * np.pi
        * (
            result["target_month"]
            - 1
        )
        / 12
    )

    wind_radians = np.deg2rad(
        result[
            "target_wind_direction_10m"
        ]
    )

    result[
        "target_wind_direction_10m_sin"
    ] = np.sin(
        wind_radians
    )

    result[
        "target_wind_direction_10m_cos"
    ] = np.cos(
        wind_radians
    )

    return result


def build_training_candidates(
    *,
    reference_features: pd.DataFrame,
    pm25_lookup: pd.DataFrame,
    weather_lookup: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Expand references and attach target labels and weather."""

    latest_target_hour = min(
        pm25_lookup["datetime_utc"].max(),
        weather_lookup["datetime_utc"].max(),
    )

    latest_eligible_reference = (
        latest_target_hour
        - pd.Timedelta(
            hours=MAX_FORECAST_HORIZON_HOURS
        )
    )

    eligible_references = (
        reference_features.loc[
            reference_features[
                "reference_time"
            ].le(
                latest_eligible_reference
            )
        ]
        .copy()
        .reset_index(drop=True)
    )

    if eligible_references.empty:
        raise TrainingDatasetRefreshError(
            "No reference rows have complete "
            "72-hour target coverage."
        )

    horizon_df = pd.DataFrame(
        {
            "forecast_horizon_hours": (
                FORECAST_HORIZONS
            )
        }
    )

    expanded = eligible_references.merge(
        horizon_df,
        how="cross",
    )

    expanded["target_time"] = (
        expanded["reference_time"]
        + pd.to_timedelta(
            expanded[
                "forecast_horizon_hours"
            ],
            unit="h",
        )
    )

    pm25_targets = pm25_lookup.rename(
        columns={
            "datetime_utc": "target_time",
            "pm25_ug_m3": TARGET_COLUMN,
        }
    )

    weather_targets = weather_lookup.rename(
        columns={
            "datetime_utc": "target_time",
            **{
                column: f"target_{column}"
                for column in WEATHER_COLUMNS
            },
        }
    )

    candidates = expanded.merge(
        pm25_targets,
        on="target_time",
        how="left",
        validate="many_to_one",
    )

    candidates = candidates.merge(
        weather_targets,
        on="target_time",
        how="left",
        validate="many_to_one",
    )

    candidates = add_target_time_features(
        candidates
    )

    return (
        candidates,
        latest_eligible_reference,
    )


def select_complete_training_rows(
    *,
    candidates: pd.DataFrame,
    model_feature_columns: list[str],
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Select leakage-safe rows with complete features and labels."""

    required_columns = {
        "reference_time",
        "target_time",
        "forecast_horizon_hours",
        TARGET_COLUMN,
        *model_feature_columns,
    }

    missing_columns = sorted(
        required_columns.difference(
            candidates.columns
        )
    )

    if missing_columns:
        raise TrainingDatasetRefreshError(
            "Generated training candidates are missing: "
            f"{missing_columns}"
        )

    missing_features = candidates[
        model_feature_columns
    ].isna().any(axis=1)

    missing_target = candidates[
        TARGET_COLUMN
    ].isna()

    invalid_reasons = {
        "missing_feature_rows": int(
            missing_features.sum()
        ),
        "missing_target_rows": int(
            missing_target.sum()
        ),
    }

    valid = candidates.loc[
        ~(
            missing_features
            | missing_target
        ),
        [
            "reference_time",
            "target_time",
            *model_feature_columns,
            TARGET_COLUMN,
        ],
    ].copy()

    valid = (
        valid.sort_values(
            [
                "reference_time",
                "forecast_horizon_hours",
            ]
        )
        .drop_duplicates(
            subset=[
                "reference_time",
                "forecast_horizon_hours",
            ],
            keep="last",
        )
        .reset_index(drop=True)
    )

    # Production retraining uses only reference timestamps whose entire
    # 72-hour label set is complete.
    horizon_counts = valid.groupby(
        "reference_time"
    )[
        "forecast_horizon_hours"
    ].nunique()

    fully_labeled_references = set(
        horizon_counts.loc[
            horizon_counts.eq(72)
        ].index
    )

    valid = (
        valid.loc[
            valid[
                "reference_time"
            ].isin(
                fully_labeled_references
            )
        ]
        .copy()
        .reset_index(drop=True)
    )

    if valid.empty:
        raise TrainingDatasetRefreshError(
            "No fully labeled 72-hour reference "
            "timestamps remain."
        )

    if TARGET_COLUMN in model_feature_columns:
        raise TrainingDatasetRefreshError(
            "Target leakage detected in the feature contract."
        )

    if not (
        valid["target_time"]
        > valid["reference_time"]
    ).all():
        raise TrainingDatasetRefreshError(
            "A target timestamp is not later than "
            "its reference timestamp."
        )

    if valid[
        model_feature_columns
    ].isna().any().any():
        raise TrainingDatasetRefreshError(
            "Selected training features contain missing values."
        )

    if valid[TARGET_COLUMN].isna().any():
        raise TrainingDatasetRefreshError(
            "Selected training targets contain missing values."
        )

    if valid.duplicated(
        subset=[
            "reference_time",
            "forecast_horizon_hours",
        ]
    ).any():
        raise TrainingDatasetRefreshError(
            "Duplicate reference/horizon keys remain."
        )

    if set(
        valid[
            "forecast_horizon_hours"
        ].unique()
    ) != set(FORECAST_HORIZONS):
        raise TrainingDatasetRefreshError(
            "Training data does not contain horizons 1 through 72."
        )

    invalid_reasons[
        "partial_reference_rows_removed"
    ] = int(
        len(
            candidates.loc[
                ~(
                    missing_features
                    | missing_target
                )
            ]
        )
        - len(valid)
    )

    return valid, invalid_reasons


def create_chronological_splits(
    dataframe: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Create 70/15/15 chronological splits with 72-hour purges."""

    reference_times = (
        dataframe["reference_time"]
        .drop_duplicates()
        .sort_values()
        .reset_index(drop=True)
    )

    if len(reference_times) < 30:
        raise TrainingDatasetRefreshError(
            "Too few reference hours exist for "
            "chronological retraining splits."
        )

    reference_count = len(
        reference_times
    )

    train_count = int(
        reference_count * 0.70
    )

    validation_count = int(
        reference_count * 0.15
    )

    train_times = set(
        reference_times.iloc[
            :train_count
        ]
    )

    validation_times = set(
        reference_times.iloc[
            train_count:
            train_count
            + validation_count
        ]
    )

    test_times = set(
        reference_times.iloc[
            train_count
            + validation_count:
        ]
    )

    train = dataframe.loc[
        dataframe[
            "reference_time"
        ].isin(train_times)
    ].copy()

    validation = dataframe.loc[
        dataframe[
            "reference_time"
        ].isin(validation_times)
    ].copy()

    test = dataframe.loc[
        dataframe[
            "reference_time"
        ].isin(test_times)
    ].copy()

    if (
        train.empty
        or validation.empty
        or test.empty
    ):
        raise TrainingDatasetRefreshError(
            "A chronological split is empty."
        )

    validation_start = validation[
        "reference_time"
    ].min()

    test_start = test[
        "reference_time"
    ].min()

    valid_train_references = set(
        train.groupby(
            "reference_time"
        )[
            "target_time"
        ]
        .max()
        .loc[
            lambda values: (
                values
                < validation_start
            )
        ]
        .index
    )

    valid_validation_references = set(
        validation.groupby(
            "reference_time"
        )[
            "target_time"
        ]
        .max()
        .loc[
            lambda values: (
                values
                < test_start
            )
        ]
        .index
    )

    train = (
        train.loc[
            train[
                "reference_time"
            ].isin(
                valid_train_references
            )
        ]
        .copy()
        .reset_index(drop=True)
    )

    validation = (
        validation.loc[
            validation[
                "reference_time"
            ].isin(
                valid_validation_references
            )
        ]
        .copy()
        .reset_index(drop=True)
    )

    test = test.reset_index(
        drop=True
    )

    if (
        train.empty
        or validation.empty
        or test.empty
    ):
        raise TrainingDatasetRefreshError(
            "A split became empty after the "
            "72-hour purge."
        )

    if not (
        train["target_time"].max()
        < validation[
            "reference_time"
        ].min()
    ):
        raise TrainingDatasetRefreshError(
            "Training targets overlap validation references."
        )

    if not (
        validation[
            "target_time"
        ].max()
        < test[
            "reference_time"
        ].min()
    ):
        raise TrainingDatasetRefreshError(
            "Validation targets overlap test references."
        )

    return {
        "train": train,
        "validation": validation,
        "test": test,
    }


def resolve_output_root(
    configured: Path | None,
) -> Path:
    """Resolve the runtime output root."""

    if configured is not None:
        path = configured
    else:
        environment_value = os.getenv(
            "RUNTIME_TRAINING_OUTPUT_DIR"
        )

        path = (
            Path(environment_value)
            if environment_value
            else DEFAULT_OUTPUT_ROOT
        )

    if not path.is_absolute():
        path = PROJECT_ROOT / path

    return path.resolve()


def save_runtime_datasets(
    *,
    run_id: str,
    full_dataframe: pd.DataFrame,
    splits: dict[str, pd.DataFrame],
    output_root: Path,
    metadata: dict[str, Any],
) -> Path:
    """Atomically save one immutable runtime dataset package."""

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    run_directory = (
        output_root
        / run_id
    )

    temporary_directory = (
        output_root
        / f".{run_id}.tmp"
    )

    if run_directory.exists():
        raise TrainingDatasetRefreshError(
            f"Runtime dataset already exists: {run_directory}"
        )

    if temporary_directory.exists():
        shutil.rmtree(
            temporary_directory
        )

    temporary_directory.mkdir(
        parents=True,
        exist_ok=False,
    )

    try:
        full_dataframe.to_parquet(
            temporary_directory
            / "feature_dataset_full.parquet",
            index=False,
        )

        splits["train"].to_parquet(
            temporary_directory
            / "train_dataset.parquet",
            index=False,
        )

        splits["validation"].to_parquet(
            temporary_directory
            / "validation_dataset.parquet",
            index=False,
        )

        splits["test"].to_parquet(
            temporary_directory
            / "test_dataset.parquet",
            index=False,
        )

        (
            temporary_directory
            / "dataset_metadata.json"
        ).write_text(
            json.dumps(
                metadata,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        temporary_directory.replace(
            run_directory
        )

    except Exception:
        shutil.rmtree(
            temporary_directory,
            ignore_errors=True,
        )
        raise

    return run_directory


def describe_split(
    dataframe: pd.DataFrame,
) -> dict[str, Any]:
    """Return one JSON-safe split summary."""

    return {
        "rows": int(
            len(dataframe)
        ),
        "reference_count": int(
            dataframe[
                "reference_time"
            ].nunique()
        ),
        "reference_start": (
            dataframe[
                "reference_time"
            ].min().isoformat()
        ),
        "reference_end": (
            dataframe[
                "reference_time"
            ].max().isoformat()
        ),
        "target_start": (
            dataframe[
                "target_time"
            ].min().isoformat()
        ),
        "target_end": (
            dataframe[
                "target_time"
            ].max().isoformat()
        ),
    }


def run_training_dataset_refresh(
    *,
    settings: MLOpsSettings,
    output_root: Path,
) -> dict[str, Any]:
    """Run one fresh production training-data refresh."""

    started_at = datetime.now(
        timezone.utc
    )

    run_id = generate_run_id()

    contracts, model_feature_columns = (
        build_contracts(settings)
    )

    repository = create_feature_repository(
        settings=settings,
        contracts=contracts,
    )

    sources = read_feature_sources(
        repository=repository,
        contracts=contracts,
    )

    pm25_lookup = prepare_pm25_lookup(
        sources["pm25"]
    )

    weather_lookup = (
        prepare_weather_lookup(
            sources["weather"]
        )
    )

    reference_features = (
        prepare_reference_features(
            dataframe=sources[
                "engineered"
            ],
            contract=contracts[
                "engineered"
            ],
        )
    )

    (
        candidates,
        latest_eligible_reference,
    ) = build_training_candidates(
        reference_features=reference_features,
        pm25_lookup=pm25_lookup,
        weather_lookup=weather_lookup,
    )

    (
        valid_dataset,
        invalid_reasons,
    ) = select_complete_training_rows(
        candidates=candidates,
        model_feature_columns=(
            model_feature_columns
        ),
    )

    splits = create_chronological_splits(
        valid_dataset
    )

    full_dataset = (
        pd.concat(
            [
                splits["train"],
                splits["validation"],
                splits["test"],
            ],
            ignore_index=True,
        )
        .sort_values(
            [
                "reference_time",
                "forecast_horizon_hours",
            ]
        )
        .reset_index(drop=True)
    )

    metadata = {
        "run_id": run_id,
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "source": repository.source_label,
        "feature_repository_backend": (
            repository.backend_name
        ),
        "feature_count": len(
            model_feature_columns
        ),
        "target_column": TARGET_COLUMN,
        "forecast_horizon_min": 1,
        "forecast_horizon_max": 72,
        "latest_target_hour": (
            min(
                pm25_lookup[
                    "datetime_utc"
                ].max(),
                weather_lookup[
                    "datetime_utc"
                ].max(),
            ).isoformat()
        ),
        "latest_eligible_reference": (
            latest_eligible_reference
            .isoformat()
        ),
        "latest_fully_labeled_reference": (
            full_dataset[
                "reference_time"
            ].max().isoformat()
        ),
        "invalid_reasons": invalid_reasons,
        "splits": {
            name: describe_split(
                dataframe
            )
            for name, dataframe
            in splits.items()
        },
        "leakage_checks": {
            "target_not_in_features": (
                TARGET_COLUMN
                not in model_feature_columns
            ),
            "target_after_reference": True,
            "train_target_before_validation": True,
            "validation_target_before_test": True,
            "full_72_horizons_per_reference": True,
        },
    }

    run_directory = save_runtime_datasets(
        run_id=run_id,
        full_dataframe=full_dataset,
        splits=splits,
        output_root=output_root,
        metadata=metadata,
    )

    completed_at = datetime.now(
        timezone.utc
    )

    return {
        "phase": "10K",
        "subphase": "10K-C1",
        "pipeline_name": (
            "training_dataset_refresh"
        ),
        "pipeline_run_id": run_id,
        "status": (
            "TRAINING_DATASET_REFRESH_COMPLETED"
        ),
        "source": repository.source_label,
        "feature_repository_backend": (
            repository.backend_name
        ),
        "started_at_utc": (
            started_at.isoformat()
        ),
        "completed_at_utc": (
            completed_at.isoformat()
        ),
        "duration_seconds": (
            completed_at
            - started_at
        ).total_seconds(),
        "source_rows": {
            "pm25": int(
                len(pm25_lookup)
            ),
            "weather": int(
                len(weather_lookup)
            ),
            "engineered": int(
                len(reference_features)
            ),
        },
        "candidate_rows": int(
            len(candidates)
        ),
        "final_rows": int(
            len(full_dataset)
        ),
        "fully_labeled_reference_count": int(
            full_dataset[
                "reference_time"
            ].nunique()
        ),
        "latest_eligible_reference": (
            latest_eligible_reference
            .isoformat()
        ),
        "latest_fully_labeled_reference": (
            full_dataset[
                "reference_time"
            ].max().isoformat()
        ),
        "feature_count": len(
            model_feature_columns
        ),
        "invalid_reasons": (
            invalid_reasons
        ),
        "splits": {
            name: describe_split(
                dataframe
            )
            for name, dataframe
            in splits.items()
        },
        "run_directory": str(
            run_directory
        ),
        "production_model_changed": False,
        "candidate_model_created": False,
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Save the latest runtime refresh report atomically."""

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = REPORT_PATH.with_suffix(
        ".json.tmp"
    )

    temporary_path.write_text(
        json.dumps(
            report,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    temporary_path.replace(
        REPORT_PATH
    )

    return REPORT_PATH


def main() -> int:
    """CLI entry point."""

    parser = argparse.ArgumentParser(
        description=(
            "Build fresh leakage-safe PM2.5 "
            "retraining datasets from the configured "
            "feature repository."
        )
    )

    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help=(
            "Optional root directory for immutable "
            "runtime training-data packages."
        ),
    )

    arguments = parser.parse_args()

    try:
        settings = get_mlops_settings()

        report = run_training_dataset_refresh(
            settings=settings,
            output_root=resolve_output_root(
                arguments.output_root
            ),
        )

        exit_code = 0

    except Exception as error:
        report = {
            "phase": "10K",
            "subphase": "10K-C1",
            "pipeline_name": (
                "training_dataset_refresh"
            ),
            "status": (
                "TRAINING_DATASET_REFRESH_FAILED"
            ),
            "failed_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "error_type": type(error).__name__,
            "error_message": str(error),
            "production_model_changed": False,
            "candidate_model_created": False,
        }

        exit_code = 1

    report_path = save_report(
        report
    )

    print(
        json.dumps(
            report,
            indent=2,
            default=str,
        )
    )

    print(
        "Report saved:",
        report_path,
    )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())