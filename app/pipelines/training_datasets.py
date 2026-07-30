"""Hopsworks-backed training-dataset construction and parity."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.mlops.contracts import (
    FeatureGroupContract,
    LOCATION_KEY,
)


class TrainingDatasetError(RuntimeError):
    """Raised when training-data preparation fails."""


@dataclass(frozen=True)
class DatasetParityResult:
    """Result of local-versus-Hopsworks parity checks."""

    passed: bool
    local_rows: int
    generated_rows: int
    local_columns: int
    generated_columns: int
    duplicate_keys: int
    missing_columns: list[str]
    additional_columns: list[str]
    mismatched_columns: list[str]
    maximum_numeric_difference: float

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe parity information."""

        return {
            "passed": self.passed,
            "local_rows": self.local_rows,
            "generated_rows": self.generated_rows,
            "local_columns": self.local_columns,
            "generated_columns": self.generated_columns,
            "duplicate_keys": self.duplicate_keys,
            "missing_columns": self.missing_columns,
            "additional_columns": self.additional_columns,
            "mismatched_columns": self.mismatched_columns,
            "maximum_numeric_difference": (
                self.maximum_numeric_difference
            ),
        }


def normalize_reference_time(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """Normalize reference-time values to UTC hours."""

    result = dataframe.copy()

    result["reference_time"] = pd.to_datetime(
        result["reference_time"],
        utc=True,
        errors="raise",
    ).dt.floor("h")

    return result


def read_hopsworks_reference_features(
    *,
    engineered_feature_group: Any,
    contract: FeatureGroupContract,
) -> pd.DataFrame:
    """Read reusable reference-time features from Hopsworks."""

    try:
        dataframe = engineered_feature_group.read(
            dataframe_type="pandas"
        )
    except Exception as error:
        raise TrainingDatasetError(
            "Could not read engineered features "
            "from Hopsworks."
        ) from error

    if dataframe is None or dataframe.empty:
        raise TrainingDatasetError(
            "The engineered feature group is empty."
        )

    dataframe.columns = [
        str(column).lower()
        for column in dataframe.columns
    ]

    missing_columns = [
        column
        for column in contract.feature_names
        if column not in dataframe.columns
    ]

    if missing_columns:
        raise TrainingDatasetError(
            "Hopsworks engineered features are missing: "
            f"{missing_columns}"
        )

    dataframe = dataframe[
        contract.feature_names
    ].copy()

    dataframe = normalize_reference_time(
        dataframe
    )

    dataframe = (
        dataframe.sort_values(
            "reference_time"
        )
        .drop_duplicates(
            subset=[
                "location_key",
                "reference_time",
            ],
            keep="last",
        )
        .reset_index(drop=True)
    )

    return dataframe


def build_hopsworks_backed_training_dataset(
    *,
    local_training_df: pd.DataFrame,
    reference_features_df: pd.DataFrame,
    engineered_contract: FeatureGroupContract,
) -> pd.DataFrame:
    """Replace local reference features with Hopsworks values."""

    local = normalize_reference_time(
        local_training_df
    )

    reference_features = normalize_reference_time(
        reference_features_df
    )

    reference_feature_columns = [
        column
        for column in engineered_contract.feature_names
        if column not in {
            "location_key",
            "reference_time",
            "feature_pipeline_version",
            "pipeline_run_id",
        }
    ]

    missing_local_columns = [
        column
        for column in reference_feature_columns
        if column not in local.columns
    ]

    if missing_local_columns:
        raise TrainingDatasetError(
            "Approved Phase 2 dataset is missing "
            f"reference features: {missing_local_columns}"
        )

    replacement = reference_features[
        [
            "reference_time",
            *reference_feature_columns,
        ]
    ].copy()

    local_without_reference_features = (
        local.drop(
            columns=reference_feature_columns
        )
    )

    generated = (
        local_without_reference_features.merge(
            replacement,
            on="reference_time",
            how="inner",
            validate="many_to_one",
        )
    )

    generated = generated[
        local.columns
    ].copy()

    generated = generated.sort_values(
        [
            "reference_time",
            "forecast_horizon_hours",
        ]
    ).reset_index(drop=True)

    return generated


def compare_training_datasets(
    *,
    local_df: pd.DataFrame,
    generated_df: pd.DataFrame,
    float_tolerance: float,
) -> DatasetParityResult:
    """Compare generated training data with Phase 2."""

    key_columns = [
        "reference_time",
        "forecast_horizon_hours",
    ]

    local = normalize_reference_time(
        local_df
    ).sort_values(
        key_columns
    ).reset_index(drop=True)

    generated = normalize_reference_time(
        generated_df
    ).sort_values(
        key_columns
    ).reset_index(drop=True)

    missing_columns = [
        column
        for column in local.columns
        if column not in generated.columns
    ]

    additional_columns = [
        column
        for column in generated.columns
        if column not in local.columns
    ]

    duplicate_keys = int(
        generated.duplicated(
            subset=key_columns
        ).sum()
    )

    mismatched_columns: list[str] = []
    maximum_numeric_difference = 0.0

    if (
        len(local) == len(generated)
        and not missing_columns
        and not additional_columns
    ):
        for column in local.columns:
            left = local[column]
            right = generated[column]

            if pd.api.types.is_numeric_dtype(left):
                left_numeric = pd.to_numeric(
                    left,
                    errors="coerce",
                ).to_numpy(dtype="float64")

                right_numeric = pd.to_numeric(
                    right,
                    errors="coerce",
                ).to_numpy(dtype="float64")

                differences = np.abs(
                    left_numeric
                    - right_numeric
                )

                finite_differences = differences[
                    np.isfinite(differences)
                ]

                column_maximum = (
                    float(
                        finite_differences.max()
                    )
                    if finite_differences.size
                    else 0.0
                )

                maximum_numeric_difference = max(
                    maximum_numeric_difference,
                    column_maximum,
                )

                equal = np.allclose(
                    left_numeric,
                    right_numeric,
                    rtol=float_tolerance,
                    atol=float_tolerance,
                    equal_nan=True,
                )

            else:
                equal = left.astype(
                    "string"
                ).fillna(
                    "<NA>"
                ).equals(
                    right.astype(
                        "string"
                    ).fillna("<NA>")
                )

            if not equal:
                mismatched_columns.append(
                    column
                )

    passed = all(
        [
            len(local) == len(generated),
            list(local.columns)
            == list(generated.columns),
            duplicate_keys == 0,
            not missing_columns,
            not additional_columns,
            not mismatched_columns,
        ]
    )

    return DatasetParityResult(
        passed=passed,
        local_rows=len(local),
        generated_rows=len(generated),
        local_columns=len(local.columns),
        generated_columns=len(
            generated.columns
        ),
        duplicate_keys=duplicate_keys,
        missing_columns=missing_columns,
        additional_columns=additional_columns,
        mismatched_columns=mismatched_columns,
        maximum_numeric_difference=(
            maximum_numeric_difference
        ),
    )


def save_versioned_training_snapshot(
    *,
    dataframe: pd.DataFrame,
    output_directory: Path,
    dataset_name: str,
    dataset_version: int,
) -> Path:
    """Save an approved Parquet training snapshot."""

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        output_directory
        / (
            f"{dataset_name}_v"
            f"{dataset_version}.parquet"
        )
    )

    dataframe.to_parquet(
        output_path,
        index=False,
    )

    return output_path