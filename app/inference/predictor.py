"""Saved model and inference-contract loading utilities."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from app.core.config import Settings, settings

from app.inference.model_source import (
    ModelArtifactPaths,
    resolve_model_artifact_paths,
)
from app.mlops.config import (
    get_mlops_settings,
)

class ArtifactContractError(RuntimeError):
    """Raised when saved model artifacts are missing or inconsistent."""


@dataclass(frozen=True)
class ModelArtifacts:
    """Validated artifacts required for live model inference."""

    model: Any
    feature_columns: list[str]
    target_column: str
    identifier_columns: list[str]
    selected_strategy: str
    model_name: str
    model_type: str
    persistence_max_horizon: int
    model_metadata: dict[str, Any]

    model_source: str
    model_registry_name: str | None
    model_registry_version: int | None
    model_checksum_sha256: str
    model_fallback_used: bool
    model_fallback_reason: str | None


def _load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from disk."""

    if not path.exists():
        raise ArtifactContractError(
            f"Required JSON artifact was not found: {path}"
        )

    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except json.JSONDecodeError as exc:
        raise ArtifactContractError(
            f"Artifact contains invalid JSON: {path}"
        ) from exc

    if not isinstance(payload, dict):
        raise ArtifactContractError(
            f"Expected a JSON object in artifact: {path}"
        )

    return payload


def _validate_shared_contract_paths(
    app_settings: Settings,
) -> None:
   """No additional external reports are required at runtime."""


def load_model_artifacts_from_paths(
    paths: ModelArtifactPaths,
    app_settings: Settings = settings,
) -> ModelArtifacts:
    """
    Load and validate a model from resolved artifact paths.

    Existing feature-contract and Phase 4 validation behavior
    remains unchanged.
    """

    model_feature_contract = _load_json(
        paths.feature_columns_path
    )

    model_metadata = _load_json(
        paths.model_metadata_path
    )

    try:
        model = joblib.load(
            paths.model_path
        )
    except Exception as exc:
        raise ArtifactContractError(
            "The resolved model could not be loaded from: "
            f"{paths.model_path}"
        ) from exc

    feature_columns = model_feature_contract.get(
        "feature_columns"
    )

    target_column = model_feature_contract.get(
        "target_column"
    )

    identifier_columns = model_feature_contract.get(
        "identifier_columns"
    )

    if not isinstance(feature_columns, list) or not feature_columns:
        raise ArtifactContractError(
            "The model feature contract does not contain "
            "a valid ordered feature list."
        )

    if not isinstance(target_column, str):
        raise ArtifactContractError(
            "The model target column is missing or invalid."
        )

    if not isinstance(identifier_columns, list):
        raise ArtifactContractError(
            "The identifier-column contract is missing or invalid."
        )

    forbidden_columns = {
        target_column,
        *identifier_columns,
    }

    forbidden_features = sorted(
        forbidden_columns.intersection(feature_columns)
    )

    if forbidden_features:
        raise ArtifactContractError(
            "Target or identifier columns were found in the "
            f"model feature list: {forbidden_features}"
        )

    if "forecast_horizon_hours" not in feature_columns:
        raise ArtifactContractError(
            "forecast_horizon_hours is missing from the "
            "model feature contract."
        )

    model_feature_count = getattr(
        model,
        "n_features_in_",
        None,
    )

    if model_feature_count != len(feature_columns):
        raise ArtifactContractError(
            "Saved model feature count does not match the "
            "feature contract. "
            f"Model={model_feature_count}, "
            f"contract={len(feature_columns)}."
        )

    selected_strategy = model_metadata.get(
        "selected_strategy"
    )

    model_name = model_metadata.get("model_name")

    routing = model_metadata.get("routing", {})

    persistence_max_horizon = routing.get(
        "persistence_max_horizon"
    )

    if not isinstance(selected_strategy, str):
        raise ArtifactContractError(
            "Selected strategy is missing from model metadata."
        )

    if not isinstance(model_name, str):
        raise ArtifactContractError(
            "Model name is missing from model metadata."
        )

    if persistence_max_horizon != (
        app_settings.persistence_max_horizon
    ):
        raise ArtifactContractError(
            "Saved hybrid threshold does not match application "
            "configuration. "
            f"Metadata={persistence_max_horizon}, "
            f"configuration="
            f"{app_settings.persistence_max_horizon}."
        )

    return ModelArtifacts(
        model=model,
        feature_columns=feature_columns,
        target_column=target_column,
        identifier_columns=identifier_columns,
        selected_strategy=selected_strategy,
        model_name=model_name,
        model_type=type(model).__name__,
        persistence_max_horizon=int(
            persistence_max_horizon
        ),
        model_metadata=model_metadata,
        model_source=paths.source,
        model_registry_name=(
            paths.model_name
            if paths.source.startswith(
                "HOPSWORKS"
            )
            else None
        ),
        model_registry_version=(
            paths.model_version
        ),
        model_checksum_sha256=(
            paths.checksum_sha256
        ),
        model_fallback_used=(
            paths.fallback_used
        ),
        model_fallback_reason=(
            paths.fallback_reason
        ),
    )


def load_model_artifacts(
    app_settings: Settings = settings,
) -> ModelArtifacts:
    """
    Resolve and load the configured production model.

    The selected source may be local, Hopsworks Registry,
    or an approved fallback.
    """

    mlops_settings = get_mlops_settings()

    try:
        resolved_paths = (
            resolve_model_artifact_paths(
                settings=mlops_settings
            )
        )
    except Exception as exc:
        raise ArtifactContractError(
            "No validated production-model source "
            "could be resolved."
        ) from exc

    return load_model_artifacts_from_paths(
        paths=resolved_paths,
        app_settings=app_settings,
    )

def validate_feature_matrix(
    feature_matrix: pd.DataFrame,
    artifacts: ModelArtifacts,
) -> None:
    """
    Validate an inference feature matrix against the saved contract.

    Prediction is not performed by this function.
    """

    actual_columns = feature_matrix.columns.tolist()
    expected_columns = artifacts.feature_columns

    if actual_columns != expected_columns:
        missing_columns = [
            column
            for column in expected_columns
            if column not in actual_columns
        ]

        unexpected_columns = [
            column
            for column in actual_columns
            if column not in expected_columns
        ]

        raise ArtifactContractError(
            "Feature matrix schema does not match the saved "
            "model contract. "
            f"Missing={missing_columns}, "
            f"unexpected={unexpected_columns}, "
            "or feature order differs."
        )

    missing_value_count = int(
        feature_matrix.isna().sum().sum()
    )

    if missing_value_count > 0:
        raise ArtifactContractError(
            "Feature matrix contains missing values: "
            f"{missing_value_count}"
        )


def generate_hybrid_predictions(
    feature_matrix: pd.DataFrame,
    artifacts: ModelArtifacts,
) -> pd.DataFrame:
    """
    Generate 72-hour PM2.5 predictions using the saved hybrid strategy.

    Horizons 1 through the configured persistence threshold use
    `pm25_current`.

    Remaining horizons use the saved XGBoost estimator.

    Negative raw predictions are preserved for auditing and clipped to
    zero only in the operational prediction column.
    """

    validate_feature_matrix(
        feature_matrix,
        artifacts,
    )

    required_columns = {
        "forecast_horizon_hours",
        "pm25_current",
    }

    missing_columns = sorted(
        required_columns.difference(
            feature_matrix.columns
        )
    )

    if missing_columns:
        raise ArtifactContractError(
            "Hybrid prediction inputs are missing required columns: "
            f"{missing_columns}"
        )

    prediction_input_df = feature_matrix.copy()

    horizons = pd.to_numeric(
        prediction_input_df[
            "forecast_horizon_hours"
        ],
        errors="coerce",
    )

    if horizons.isna().any():
        raise ArtifactContractError(
            "Forecast horizons contain invalid values."
        )

    if horizons.duplicated().any():
        raise ArtifactContractError(
            "Forecast horizons contain duplicates."
        )

    expected_horizons = list(
        range(
            1,
            int(horizons.max()) + 1,
        )
    )

    if horizons.astype(int).tolist() != expected_horizons:
        raise ArtifactContractError(
            "Forecast horizons must be continuous and ordered "
            f"from 1 through {int(horizons.max())}."
        )

    persistence_mask = horizons.le(
        artifacts.persistence_max_horizon
    )

    model_mask = ~persistence_mask

    raw_predictions = pd.Series(
        index=prediction_input_df.index,
        dtype="float64",
    )

    prediction_sources = pd.Series(
        index=prediction_input_df.index,
        dtype="string",
    )

    raw_predictions.loc[persistence_mask] = (
        prediction_input_df.loc[
            persistence_mask,
            "pm25_current",
        ].astype(float)
    )

    prediction_sources.loc[persistence_mask] = (
        "current_pm25_persistence"
    )

    if model_mask.any():
        xgboost_predictions = artifacts.model.predict(
            prediction_input_df.loc[
                model_mask,
                artifacts.feature_columns,
            ]
        )

        raw_predictions.loc[model_mask] = (
            xgboost_predictions
        )

        prediction_sources.loc[model_mask] = (
            artifacts.model_name
        )

    if raw_predictions.isna().any():
        missing_prediction_count = int(
            raw_predictions.isna().sum()
        )

        raise ArtifactContractError(
            "Hybrid prediction generation produced missing values: "
            f"{missing_prediction_count}"
        )

    prediction_df = pd.DataFrame(
        {
            "forecast_horizon_hours": (
                horizons.astype(int)
            ),
            "predicted_pm25_ug_m3_raw": (
                raw_predictions.astype(float)
            ),
            "prediction_source": prediction_sources,
        }
    )

    prediction_df["prediction_was_clipped"] = (
        prediction_df[
            "predicted_pm25_ug_m3_raw"
        ].lt(0)
    )

    prediction_df["predicted_pm25_ug_m3"] = (
        prediction_df[
            "predicted_pm25_ug_m3_raw"
        ].clip(lower=0)
    )

    return prediction_df[
        [
            "forecast_horizon_hours",
            "predicted_pm25_ug_m3_raw",
            "predicted_pm25_ug_m3",
            "prediction_was_clipped",
            "prediction_source",
        ]
    ]