"""Compare and optionally register the latest challenger."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from app.mlops.champion_challenger import (
    evaluate_promotion_gates,
)
from app.mlops.client import (
    connect_to_hopsworks,
)
from app.mlops.config import (
    get_mlops_settings,
)
from app.mlops.model_registry import (
    register_candidate_model,
)
from app.mlops.retraining import (
    evaluate_candidate,
    load_feature_columns,
    load_json_object,
    validate_training_frame,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def find_latest_candidate(
    candidate_root: Path,
) -> Path:
    """Return the newest complete candidate directory."""

    candidates = sorted(
        (
            path
            for path in candidate_root.iterdir()
            if path.is_dir()
            and (
                path / "best_model.joblib"
            ).exists()
            and (
                path / "candidate_metadata.json"
            ).exists()
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not candidates:
        raise FileNotFoundError(
            "No complete candidate package exists."
        )

    return candidates[0]


def run_champion_challenger(
    *,
    register_approved: bool,
    candidate_directory: Path | None = None,
) -> dict[str, Any]:
    """Compare champion and latest challenger."""

    settings = get_mlops_settings()

    candidate_root = (
        PROJECT_ROOT
        / settings.candidate_output_directory
    )

    if candidate_directory is None:
        candidate_directory = (
            find_latest_candidate(
                candidate_root
            )
        )

    else:
        candidate_directory = (
            candidate_directory
            .expanduser()
        )

        if not candidate_directory.is_absolute():
            candidate_directory = (
                PROJECT_ROOT
                / candidate_directory
            )

        candidate_directory = (
            candidate_directory.resolve()
        )

        required_candidate_files = [
            candidate_directory
            / "best_model.joblib",
            candidate_directory
            / "candidate_metadata.json",
        ]

        missing_candidate_files = [
            str(path)
            for path in required_candidate_files
            if not path.exists()
        ]

        if missing_candidate_files:
            raise FileNotFoundError(
                "Candidate package is incomplete: "
                f"{missing_candidate_files}"
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

    test_path = (
        PROJECT_ROOT
        / "data"
        / "training"
        / "test_dataset.parquet"
    )

    feature_columns = load_feature_columns(
        feature_contract_path
    )

    production_metadata = load_json_object(
        production_metadata_path
    )

    target_column = str(
        production_metadata.get(
            "target_column",
            "target_pm25_ug_m3",
        )
    )

    persistence_max_horizon = int(
        production_metadata[
            "routing"
        ][
            "persistence_max_horizon"
        ]
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

    candidate_model = joblib.load(
        candidate_directory
        / "best_model.joblib"
    )

    champion_metrics = evaluate_candidate(
        dataframe=test_df,
        model=production_model,
        feature_columns=feature_columns,
        target_column=target_column,
        persistence_max_horizon=(
            persistence_max_horizon
        ),
    )

    challenger_metrics = evaluate_candidate(
        dataframe=test_df,
        model=candidate_model,
        feature_columns=feature_columns,
        target_column=target_column,
        persistence_max_horizon=(
            persistence_max_horizon
        ),
    )

    decision = evaluate_promotion_gates(
        champion_test_metrics=(
            champion_metrics
        ),
        candidate_test_metrics=(
            challenger_metrics
        ),
        maximum_mae_regression_pct=(
            settings
            .candidate_max_overall_mae_regression_pct
        ),
        maximum_rmse_regression_pct=(
            settings
            .candidate_max_overall_rmse_regression_pct
        ),
        maximum_horizon_mae_regression_pct=(
            settings
            .candidate_max_horizon_mae_regression_pct
        ),
        minimum_severe_samples=(
            settings
            .candidate_minimum_severe_samples
        ),
    )

    registered_model = None

    if register_approved:
        if not decision.approved:
            raise RuntimeError(
                "Candidate failed promotion gates and "
                "cannot be registered as approved."
            )

        resources = connect_to_hopsworks(
            settings
        )

        registered_model = register_candidate_model(
            resources=resources,
            settings=settings,
            candidate_directory=(
                candidate_directory
            ),
            metrics={
                "test_mae": float(
                    challenger_metrics[
                        "overall"
                    ]["mae"]
                ),
                "test_rmse": float(
                    challenger_metrics[
                        "overall"
                    ]["rmse"]
                ),
                "test_r2": float(
                    challenger_metrics[
                        "overall"
                    ]["r2"]
                ),
            },
        )

    status = (
        "CHALLENGER_REGISTERED"
        if registered_model is not None
        else (
            "CHALLENGER_APPROVED"
            if decision.approved
            else "CHALLENGER_REJECTED"
        )
    )

    return {
        "phase": "9J",
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "status": status,
        "candidate_directory": (
            candidate_directory.relative_to(
                PROJECT_ROOT
            ).as_posix()
        ),
        "champion": {
            "registry_name": (
                settings.hopsworks_model_name
            ),
            "production_version": (
                settings
                .hopsworks_production_model_version
            ),
            "metrics": champion_metrics,
        },
        "challenger": {
            "metrics": challenger_metrics,
            "registered": (
                registered_model is not None
            ),
            "registered_model": (
                registered_model.to_dict()
                if registered_model is not None
                else None
            ),
        },
        "decision": decision.to_dict(),
        "production_changed": False,
        "rollback_version": (
            settings.hopsworks_production_model_version
        ),
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Save champion–challenger report."""

    report_path = (
        PROJECT_ROOT
        / "reports"
        / "phase_9"
        / "champion_challenger_report.json"
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
            "Evaluate and optionally register "
            "the latest challenger."
        )
    )

    parser.add_argument(
        "--register-approved",
        action="store_true",
        help=(
            "Register the challenger only when all "
            "promotion gates pass."
        ),
    )

    arguments = parser.parse_args()

    try:
        report = run_champion_challenger(
            register_approved=(
                arguments.register_approved
            ),
            candidate_directory=None,
        )

        exit_code = 0

    except Exception as error:
        report = {
            "phase": "9J",
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": (
                "CHAMPION_CHALLENGER_FAILED"
            ),
            "error_type": type(error).__name__,
            "error_message": str(error),
            "production_changed": False,
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