"""Build and validate the Hopsworks-backed training dataset."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.mlops.client import (
    connect_to_hopsworks,
)
from app.mlops.config import (
    get_mlops_settings,
)
from app.mlops.contracts import (
    build_feature_group_contracts,
)
from app.pipelines.feature_views import (
    create_or_get_reference_feature_view,
)
from app.pipelines.training_datasets import (
    build_hopsworks_backed_training_dataset,
    compare_training_datasets,
    read_hopsworks_reference_features,
    save_versioned_training_snapshot,
)
from app.pipelines.historical_backfill import (
    load_feature_columns,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run_training_dataset_pipeline() -> dict[str, Any]:
    """Create the feature view and validate dataset parity."""

    settings = get_mlops_settings()

    if settings.mlops_dry_run:
        raise ValueError(
            "Phase 9E requires MLOPS_DRY_RUN=false "
            "because Hopsworks data must be read."
        )

    resources = connect_to_hopsworks(
        settings
    )

    feature_store = resources.feature_store

    if feature_store is None:
        raise RuntimeError(
            "Hopsworks Feature Store was not resolved."
        )

    model_feature_columns = load_feature_columns(
        PROJECT_ROOT
        / "models"
        / "model_feature_columns.json"
    )

    contracts = build_feature_group_contracts(
        pm25_version=(
            settings.hopsworks_pm25_feature_group_version
        ),
        weather_version=(
            settings.hopsworks_weather_feature_group_version
        ),
        engineered_version=(
            settings.hopsworks_engineered_feature_group_version
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

    engineered_group = (
        feature_store.get_feature_group(
            name=(
                settings
                .hopsworks_engineered_feature_group_name
            ),
            version=(
                settings.hopsworks_engineered_feature_group_version
            ),
        )
    )

    resolved_view = (
        create_or_get_reference_feature_view(
            resources=resources,
            settings=settings,
            engineered_feature_group=(
                engineered_group
            ),
            engineered_contract=(
                contracts["engineered"]
            ),
        )
    )

    reference_features = (
        read_hopsworks_reference_features(
            engineered_feature_group=(
                engineered_group
            ),
            contract=contracts["engineered"],
        )
    )

    local_training_path = (
        PROJECT_ROOT
        / settings.phase_2_training_dataset_path
    )

    local_training_df = pd.read_parquet(
        local_training_path
    )

    generated_df = (
        build_hopsworks_backed_training_dataset(
            local_training_df=(
                local_training_df
            ),
            reference_features_df=(
                reference_features
            ),
            engineered_contract=(
                contracts["engineered"]
            ),
        )
    )

    local_reference_times = set(
    pd.to_datetime(
        local_training_df[
            "reference_time"
        ],
        utc=True,
    ).dt.floor("h")
    )

    hopsworks_reference_times = set(
        pd.to_datetime(
            reference_features[
                "reference_time"
            ],
            utc=True,
        ).dt.floor("h")
    )

    missing_in_hopsworks = sorted(
        local_reference_times
        - hopsworks_reference_times
    )

    additional_in_hopsworks = sorted(
        hopsworks_reference_times
        - local_reference_times
    )

    print(
        "Local rows:",
        len(local_training_df),
    )

    print(
        "Generated rows:",
        len(generated_df),
    )

    print(
        "Local reference timestamps:",
        len(local_reference_times),
    )

    print(
        "Hopsworks reference timestamps:",
        len(hopsworks_reference_times),
    )

    print(
        "Missing reference timestamps:",
        len(missing_in_hopsworks),
    )

    print(
        "Additional reference timestamps:",
        len(additional_in_hopsworks),
    )

    print(
        "First missing timestamps:",
        missing_in_hopsworks[:10],
    )

    parity = compare_training_datasets(
        local_df=local_training_df,
        generated_df=generated_df,
        float_tolerance=(
            settings
            .training_dataset_float_tolerance
        ),
    )

    if not parity.passed:
        return {
            "phase": "9E",
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": (
                "TRAINING_DATASET_PARITY_FAILED"
            ),
            "feature_view": (
                resolved_view.safe_summary()
            ),
            "training_dataset": {
                "local_row_count": int(
                    len(local_training_df)
                ),
                "generated_row_count": int(
                    len(generated_df)
                ),
                "local_reference_count": int(
                    local_training_df[
                        "reference_time"
                    ].nunique()
                ),
                "generated_reference_count": int(
                    generated_df[
                        "reference_time"
                    ].nunique()
                ),
            },
            "parity": parity.to_dict(),
        }

    snapshot_path = (
        save_versioned_training_snapshot(
            dataframe=generated_df,
            output_directory=(
                PROJECT_ROOT
                / "data"
                / "training"
                / "hopsworks"
            ),
            dataset_name=(
                settings
                .hopsworks_training_dataset_name
            ),
            dataset_version=(
                settings
                .hopsworks_training_dataset_version
            ),
        )
    )

    return {
        "phase": "9E",
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "status": (
            "TRAINING_DATASET_PARITY_PASSED"
        ),
        "feature_view": (
            resolved_view.safe_summary()
        ),
        "training_dataset": {
            "name": (
                settings
                .hopsworks_training_dataset_name
            ),
            "version": (
                settings
                .hopsworks_training_dataset_version
            ),
            "snapshot_path": (
                snapshot_path.relative_to(
                    PROJECT_ROOT
                ).as_posix()
            ),
            "row_count": len(generated_df),
            "column_count": len(
                generated_df.columns
            ),
            "reference_start": str(
                generated_df[
                    "reference_time"
                ].min()
            ),
            "reference_end": str(
                generated_df[
                    "reference_time"
                ].max()
            ),
            "horizon_min": int(
                generated_df[
                    "forecast_horizon_hours"
                ].min()
            ),
            "horizon_max": int(
                generated_df[
                    "forecast_horizon_hours"
                ].max()
            ),
        },
        "parity": parity.to_dict(),
        "historical_weather_limitation": (
            "Observed target-hour historical weather "
            "remains a proxy for forecast weather."
        ),
    }


def main() -> int:
    """Run and save the Phase 9E report."""

    report_directory = (
        PROJECT_ROOT
        / "reports"
        / "phase_9"
    )

    report_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path = (
        report_directory
        / "training_dataset_report.json"
    )

    try:
        report = run_training_dataset_pipeline()

        report_path.write_text(
            json.dumps(
                report,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        print(
            json.dumps(
                report,
                indent=2,
                default=str,
            )
        )

        print("Report saved:", report_path)

        return (
            0
            if report["status"]
            == "TRAINING_DATASET_PARITY_PASSED"
            else 1
        )

    except Exception as error:
        failure_report = {
            "phase": "9E",
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": (
                "TRAINING_DATASET_PARITY_FAILED"
            ),
            "error_type": type(error).__name__,
            "error_message": str(error),
        }

        report_path.write_text(
            json.dumps(
                failure_report,
                indent=2,
            ),
            encoding="utf-8",
        )

        print(
            json.dumps(
                failure_report,
                indent=2,
            )
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())