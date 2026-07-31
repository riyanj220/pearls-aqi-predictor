"""Run one controlled model-retraining cycle."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from app.mlops.config import (
    get_mlops_settings,
)
from app.mlops.retraining import (
    RetrainingError,
    evaluate_candidate,
    evaluate_retraining_eligibility,
    load_feature_columns,
    load_json_object,
    save_candidate_package,
    train_candidate_model,
    validate_training_frame,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run_retraining_cycle(
    *,
    force: bool,
) -> dict[str, Any]:
    """Run eligibility, training and candidate evaluation."""

    settings = get_mlops_settings()

    train_path = (
        PROJECT_ROOT
        / "data"
        / "training"
        / "train_dataset.parquet"
    )

    validation_path = (
        PROJECT_ROOT
        / "data"
        / "training"
        / "validation_dataset.parquet"
    )

    test_path = (
        PROJECT_ROOT
        / "data"
        / "training"
        / "test_dataset.parquet"
    )

    full_dataset_path = (
        PROJECT_ROOT
        / settings.phase_2_training_dataset_path
    )

    feature_contract_path = (
        PROJECT_ROOT
        / "models"
        / "model_feature_columns.json"
    )

    production_model_path = (
        PROJECT_ROOT
        / "models"
        / "best_model.joblib"
    )

    production_metadata_path = (
        PROJECT_ROOT
        / "models"
        / "model_metadata.json"
    )

    required_paths = [
        train_path,
        validation_path,
        test_path,
        full_dataset_path,
        feature_contract_path,
        production_model_path,
        production_metadata_path,
    ]

    missing_paths = [
        str(path)
        for path in required_paths
        if not path.exists()
    ]

    if missing_paths:
        raise RetrainingError(
            "Required retraining artifacts are missing: "
            f"{missing_paths}"
        )

    full_df = pd.read_parquet(
        full_dataset_path
    )

    production_metadata = load_json_object(
        production_metadata_path
    )

    eligibility = (
        evaluate_retraining_eligibility(
            training_df=full_df,
            production_metadata=(
                production_metadata
            ),
            minimum_new_labeled_hours=(
                settings
                .minimum_new_labeled_hours
            ),
            force=force,
        )
    )

    if not eligibility.eligible:
        return {
            "phase": "9I",
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": (
                "RETRAINING_SKIPPED_NO_NEW_DATA"
            ),
            "eligibility": (
                eligibility.to_dict()
            ),
            "candidate_created": False,
            "production_model_changed": False,
        }

    feature_columns = load_feature_columns(
        feature_contract_path
    )

    target_column = str(
        production_metadata.get(
            "target_column",
            "target_pm25_ug_m3",
        )
    )

    persistence_max_horizon = int(
        production_metadata.get(
            "routing",
            {},
        ).get(
            "persistence_max_horizon",
            12,
        )
    )

    train_df = validate_training_frame(
        dataframe=pd.read_parquet(
            train_path
        ),
        feature_columns=feature_columns,
        target_column=target_column,
    )

    validation_df = validate_training_frame(
        dataframe=pd.read_parquet(
            validation_path
        ),
        feature_columns=feature_columns,
        target_column=target_column,
    )

    test_df = validate_training_frame(
        dataframe=pd.read_parquet(
            test_path
        ),
        feature_columns=feature_columns,
        target_column=target_column,
    )

    production_model = joblib.load(
        production_model_path
    )

    candidate_model = train_candidate_model(
        production_model=production_model,
        train_df=train_df,
        validation_df=validation_df,
        feature_columns=feature_columns,
        target_column=target_column,
        persistence_max_horizon=(
            persistence_max_horizon
        ),
    )

    validation_metrics = evaluate_candidate(
        dataframe=validation_df,
        model=candidate_model,
        feature_columns=feature_columns,
        target_column=target_column,
        persistence_max_horizon=(
            persistence_max_horizon
        ),
    )

    test_metrics = evaluate_candidate(
        dataframe=test_df,
        model=candidate_model,
        feature_columns=feature_columns,
        target_column=target_column,
        persistence_max_horizon=(
            persistence_max_horizon
        ),
    )

    candidate_directory, checksum = (
        save_candidate_package(
            candidate_model=candidate_model,
            output_root=(
                PROJECT_ROOT
                / settings
                .candidate_output_directory
            ),
            candidate_name=(
                settings.candidate_model_name
            ),
            feature_contract_path=(
                feature_contract_path
            ),
            production_metadata_path=(
                production_metadata_path
            ),
            validation_metrics=(
                validation_metrics
            ),
            test_metrics=test_metrics,
            training_reference_start=(
                train_df[
                    "reference_time"
                ].min()
            ),
            training_reference_end=(
                train_df[
                    "reference_time"
                ].max()
            ),
            persistence_max_horizon=(
                persistence_max_horizon
            ),
        )
    )

    return {
        "phase": "9I",
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "status": "RETRAINING_COMPLETED",
        "eligibility": (
            eligibility.to_dict()
        ),
        "training": {
            "train_rows": int(
                len(train_df)
            ),
            "validation_rows": int(
                len(validation_df)
            ),
            "test_rows": int(
                len(test_df)
            ),
            "feature_count": len(
                feature_columns
            ),
            "target_column": target_column,
            "persistence_max_horizon": (
                persistence_max_horizon
            ),
        },
        "validation_metrics": (
            validation_metrics
        ),
        "test_metrics": test_metrics,
        "candidate": {
            "directory": (
                candidate_directory.relative_to(
                    PROJECT_ROOT
                ).as_posix()
            ),
            "checksum_sha256": checksum,
            "lifecycle_status": "CANDIDATE",
        },
        "candidate_created": True,
        "candidate_registered": False,
        "production_model_changed": False,
        "promotion_deferred_to_phase_9j": True,
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Save the latest retraining-cycle report."""

    report_path = (
        PROJECT_ROOT
        / "reports"
        / "phase_9"
        / "automated_training_report.json"
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
            "Run one controlled PM2.5 "
            "model-retraining cycle."
        )
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Run candidate training even when "
            "eligibility requirements are not met."
        ),
    )

    arguments = parser.parse_args()

    try:
        report = run_retraining_cycle(
            force=arguments.force
        )

        exit_code = 0

    except Exception as error:
        report = {
            "phase": "9I",
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": "RETRAINING_FAILED",
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(error),
            "candidate_created": False,
            "production_model_changed": False,
        }

        exit_code = 1

    report_path = save_report(report)

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