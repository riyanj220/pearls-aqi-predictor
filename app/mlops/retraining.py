"""Controlled candidate retraining and evaluation."""

from __future__ import annotations

import json
import math
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)

from app.mlops.model_registry import (
    calculate_sha256,
)


class RetrainingError(RuntimeError):
    """Raised when controlled retraining cannot complete."""


HORIZON_GROUPS: dict[str, tuple[int, int]] = {
    "1_6": (1, 6),
    "7_12": (7, 12),
    "13_24": (13, 24),
    "25_48": (25, 48),
    "49_72": (49, 72),
}


@dataclass(frozen=True)
class RetrainingEligibility:
    """Decision describing whether retraining may run."""

    eligible: bool
    forced: bool
    latest_reference_time: pd.Timestamp
    production_training_end: pd.Timestamp | None
    new_labeled_hours: int
    minimum_required_hours: int
    reason: str

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe eligibility metadata."""

        return {
            "eligible": self.eligible,
            "forced": self.forced,
            "latest_reference_time": (
                self.latest_reference_time.isoformat()
            ),
            "production_training_end": (
                self.production_training_end.isoformat()
                if self.production_training_end
                is not None
                else None
            ),
            "new_labeled_hours": (
                self.new_labeled_hours
            ),
            "minimum_required_hours": (
                self.minimum_required_hours
            ),
            "reason": self.reason,
        }


def load_json_object(
    path: Path,
) -> dict[str, Any]:
    """Load one JSON object."""

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(payload, dict):
        raise RetrainingError(
            f"{path} must contain a JSON object."
        )

    return payload


def load_feature_columns(
    path: Path,
) -> list[str]:
    """Load the ordered model feature contract."""

    payload = load_json_object(path)

    feature_columns = payload.get(
        "feature_columns"
    )

    if not isinstance(
        feature_columns,
        list,
    ) or not feature_columns:
        raise RetrainingError(
            "The model feature contract does not "
            "contain feature_columns."
        )

    return [
        str(column)
        for column in feature_columns
    ]


def normalize_reference_time(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """Normalize reference timestamps to UTC hours."""

    if "reference_time" not in dataframe.columns:
        raise RetrainingError(
            "Training data is missing reference_time."
        )

    result = dataframe.copy()

    result["reference_time"] = pd.to_datetime(
        result["reference_time"],
        utc=True,
        errors="raise",
    ).dt.floor("h")

    return result


def resolve_production_training_end(
    metadata: dict[str, Any],
) -> pd.Timestamp | None:
    """Resolve the production model's training-end timestamp."""

    candidate_values = [
        metadata.get("training_end"),
        metadata.get("training_end_utc"),
        metadata.get("training_data_end"),
        metadata.get("training_reference_end"),
    ]

    data_ranges = metadata.get(
        "data_ranges"
    )

    if isinstance(data_ranges, dict):
        candidate_values.extend(
            [
                data_ranges.get(
                    "train_reference_end"
                ),
                data_ranges.get(
                    "training_reference_end"
                ),
                data_ranges.get(
                    "reference_end"
                ),
            ]
        )

    training_range = metadata.get(
        "training_data_range"
    )

    if isinstance(training_range, dict):
        candidate_values.extend(
            [
                training_range.get("end"),
                training_range.get("end_utc"),
                training_range.get(
                    "reference_end"
                ),
            ]
        )

    for value in candidate_values:
        if value is None:
            continue

        try:
            timestamp = pd.Timestamp(value)

            if timestamp.tzinfo is None:
                timestamp = timestamp.tz_localize(
                    "UTC"
                )
            else:
                timestamp = timestamp.tz_convert(
                    "UTC"
                )

            return timestamp.floor("h")

        except (TypeError, ValueError):
            continue

    return None


def evaluate_retraining_eligibility(
    *,
    training_df: pd.DataFrame,
    production_metadata: dict[str, Any],
    minimum_new_labeled_hours: int,
    force: bool,
) -> RetrainingEligibility:
    """Determine whether candidate training should run."""

    normalized = normalize_reference_time(
        training_df
    )

    latest_reference_time = normalized[
        "reference_time"
    ].max()

    production_training_end = (
        resolve_production_training_end(
            production_metadata
        )
    )

    if force:
        return RetrainingEligibility(
            eligible=True,
            forced=True,
            latest_reference_time=(
                latest_reference_time
            ),
            production_training_end=(
                production_training_end
            ),
            new_labeled_hours=0,
            minimum_required_hours=(
                minimum_new_labeled_hours
            ),
            reason=(
                "Retraining was explicitly forced."
            ),
        )

    if production_training_end is None:
        return RetrainingEligibility(
            eligible=False,
            forced=False,
            latest_reference_time=(
                latest_reference_time
            ),
            production_training_end=None,
            new_labeled_hours=0,
            minimum_required_hours=(
                minimum_new_labeled_hours
            ),
            reason=(
                "Production metadata does not contain "
                "a usable training-end timestamp."
            ),
        )

    new_reference_times = normalized.loc[
        normalized["reference_time"]
        > production_training_end,
        "reference_time",
    ].nunique()

    eligible = (
        int(new_reference_times)
        >= minimum_new_labeled_hours
    )

    return RetrainingEligibility(
        eligible=eligible,
        forced=False,
        latest_reference_time=(
            latest_reference_time
        ),
        production_training_end=(
            production_training_end
        ),
        new_labeled_hours=int(
            new_reference_times
        ),
        minimum_required_hours=(
            minimum_new_labeled_hours
        ),
        reason=(
            "Enough new labeled reference hours exist."
            if eligible
            else (
                "Not enough new labeled reference "
                "hours are available."
            )
        ),
    )


def validate_training_frame(
    *,
    dataframe: pd.DataFrame,
    feature_columns: list[str],
    target_column: str,
) -> pd.DataFrame:
    """Validate one chronological training split."""

    required_columns = {
        *feature_columns,
        target_column,
        "reference_time",
        "forecast_horizon_hours",
    }

    missing_columns = sorted(
        required_columns.difference(
            dataframe.columns
        )
    )

    if missing_columns:
        raise RetrainingError(
            "Training split is missing columns: "
            f"{missing_columns}"
        )

    result = normalize_reference_time(
        dataframe
    )

    duplicate_count = int(
        result.duplicated(
            subset=[
                "reference_time",
                "forecast_horizon_hours",
            ]
        ).sum()
    )

    if duplicate_count:
        raise RetrainingError(
            "Training split contains duplicate "
            f"reference/horizon keys: {duplicate_count}"
        )

    missing_feature_values = int(
        result[feature_columns]
        .isna()
        .sum()
        .sum()
    )

    if missing_feature_values:
        raise RetrainingError(
            "Training split contains missing feature "
            f"values: {missing_feature_values}"
        )

    if result[target_column].isna().any():
        raise RetrainingError(
            "Training split contains missing targets."
        )

    return result


def train_candidate_model(
    *,
    production_model: Any,
    train_df: pd.DataFrame,
    validation_df: pd.DataFrame,
    feature_columns: list[str],
    target_column: str,
    persistence_max_horizon: int,
) -> Any:
    """Train one controlled challenger configuration."""

    learned_train_rows = train_df.loc[
        train_df[
            "forecast_horizon_hours"
        ].gt(persistence_max_horizon)
    ].copy()

    learned_validation_rows = (
        validation_df.loc[
            validation_df[
                "forecast_horizon_hours"
            ].gt(persistence_max_horizon)
        ].copy()
    )

    if learned_train_rows.empty:
        raise RetrainingError(
            "No learned-model training horizons are available."
        )

    if learned_validation_rows.empty:
        raise RetrainingError(
            "No learned-model validation horizons are available."
        )

    try:
        candidate_model = clone(
            production_model
        )
    except Exception as error:
        raise RetrainingError(
            "The approved estimator could not be cloned."
        ) from error

    candidate_model.fit(
        learned_train_rows[
            feature_columns
        ],
        learned_train_rows[
            target_column
        ],
        eval_set=[
            (
                learned_validation_rows[
                    feature_columns
                ],
                learned_validation_rows[
                    target_column
                ],
            )
        ],
        verbose=False,
    )

    return candidate_model

def generate_hybrid_predictions(
    *,
    dataframe: pd.DataFrame,
    model: Any,
    feature_columns: list[str],
    persistence_max_horizon: int,
) -> np.ndarray:
    """Generate hybrid persistence and model predictions."""

    horizons = pd.to_numeric(
        dataframe[
            "forecast_horizon_hours"
        ],
        errors="raise",
    )

    predictions = np.empty(
        len(dataframe),
        dtype="float64",
    )

    persistence_mask = horizons.le(
        persistence_max_horizon
    ).to_numpy()

    model_mask = ~persistence_mask

    predictions[persistence_mask] = (
        dataframe.loc[
            persistence_mask,
            "pm25_current",
        ]
        .astype(float)
        .to_numpy()
    )

    if model_mask.any():
        predictions[model_mask] = (
            model.predict(
                dataframe.loc[
                    model_mask,
                    feature_columns,
                ]
            )
        )

    return np.clip(
        predictions,
        a_min=0.0,
        a_max=None,
    )


def calculate_metrics(
    actual: np.ndarray,
    predicted: np.ndarray,
) -> dict[str, float]:
    """Calculate standard regression metrics."""

    return {
        "mae": float(
            mean_absolute_error(
                actual,
                predicted,
            )
        ),
        "rmse": float(
            math.sqrt(
                mean_squared_error(
                    actual,
                    predicted,
                )
            )
        ),
        "r2": float(
            r2_score(
                actual,
                predicted,
            )
        ),
    }


def evaluate_candidate(
    *,
    dataframe: pd.DataFrame,
    model: Any,
    feature_columns: list[str],
    target_column: str,
    persistence_max_horizon: int,
) -> dict[str, Any]:
    """Evaluate one candidate on a chronological split."""

    predictions = generate_hybrid_predictions(
        dataframe=dataframe,
        model=model,
        feature_columns=feature_columns,
        persistence_max_horizon=(
            persistence_max_horizon
        ),
    )

    actual = (
        dataframe[target_column]
        .astype(float)
        .to_numpy()
    )

    overall_metrics = calculate_metrics(
        actual,
        predictions,
    )

    horizon_metrics: dict[
        str,
        dict[str, Any],
    ] = {}

    for group_name, (
        minimum_horizon,
        maximum_horizon,
    ) in HORIZON_GROUPS.items():
        mask = (
            dataframe[
                "forecast_horizon_hours"
            ]
            .between(
                minimum_horizon,
                maximum_horizon,
            )
            .to_numpy()
        )

        if not mask.any():
            horizon_metrics[group_name] = {
                "sample_count": 0,
                "metrics": None,
            }
            continue

        horizon_metrics[group_name] = {
            "sample_count": int(
                mask.sum()
            ),
            "metrics": calculate_metrics(
                actual[mask],
                predictions[mask],
            ),
        }

    severe_mask = actual >= 55.5

    severe_metrics = (
        calculate_metrics(
            actual[severe_mask],
            predictions[severe_mask],
        )
        if severe_mask.any()
        else None
    )

    return {
        "row_count": int(
            len(dataframe)
        ),
        "overall": overall_metrics,
        "horizon_groups": horizon_metrics,
        "severe_pm25": {
            "threshold_ug_m3": 55.5,
            "sample_count": int(
                severe_mask.sum()
            ),
            "metrics": severe_metrics,
        },
    }


def save_candidate_package(
    *,
    candidate_model: Any,
    output_root: Path,
    candidate_name: str,
    feature_contract_path: Path,
    production_metadata_path: Path,
    validation_metrics: dict[str, Any],
    test_metrics: dict[str, Any],
    training_reference_start: pd.Timestamp,
    training_reference_end: pd.Timestamp,
    persistence_max_horizon: int,
) -> tuple[Path, str]:
    """Save one immutable local challenger package."""

    candidate_id = (
        datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ"
        )
        + "_"
        + uuid.uuid4().hex[:8]
    )

    candidate_directory = (
        output_root
        / f"{candidate_name}_{candidate_id}"
    )

    candidate_directory.mkdir(
        parents=True,
        exist_ok=False,
    )

    model_path = (
        candidate_directory
        / "best_model.joblib"
    )

    joblib.dump(
        candidate_model,
        model_path,
    )

    shutil.copy2(
        feature_contract_path,
        candidate_directory
        / "model_feature_columns.json",
    )

    production_metadata = load_json_object(
        production_metadata_path
    )

    candidate_metadata = {
        "candidate_id": candidate_id,
        "lifecycle_status": "CANDIDATE",
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "model_type": (
            type(candidate_model).__name__
        ),
        "selected_strategy": (
            production_metadata.get(
                "selected_strategy"
            )
        ),
        "routing": {
            "persistence_max_horizon": (
                persistence_max_horizon
            )
        },
        "training_reference_start": (
            training_reference_start.isoformat()
        ),
        "training_reference_end": (
            training_reference_end.isoformat()
        ),
        "validation_metrics": (
            validation_metrics
        ),
        "test_metrics": test_metrics,
    }

    (
        candidate_directory
        / "candidate_metadata.json"
    ).write_text(
        json.dumps(
            candidate_metadata,
            indent=2,
        ),
        encoding="utf-8",
    )

    checksum = calculate_sha256(
        model_path
    )

    (
        candidate_directory
        / "checksum.sha256"
    ).write_text(
        checksum + "\n",
        encoding="utf-8",
    )

    return candidate_directory, checksum