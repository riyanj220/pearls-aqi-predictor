"""Synchronize fresh hourly features with Hopsworks.

This is the production entry point for the hourly feature job.

The pipeline:

1. fetches recent PM2.5 observations from OpenAQ;
2. fetches recent weather from Open-Meteo;
3. selects the latest safe reference hour;
4. builds reusable reference-time features;
5. prepares rows using the established feature-group contracts;
6. incrementally synchronizes only new or changed rows.

It does not rebuild the complete historical dataset.
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import settings as app_settings
from app.data.validation import (
    select_latest_safe_reference_time,
)
from app.data_sources.open_meteo_client import (
    OpenMeteoClient,
)
from app.data_sources.openaq_client import (
    OpenAQClient,
)
from app.features.live_feature_builder import (
    build_reference_feature_table,
)
from app.mlops.feature_repository import (
    create_feature_repository,
)
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
    order_for_contract,
    prepare_engineered_rows,
    prepare_pm25_rows,
    prepare_weather_rows,
)
from app.pipelines.incremental_features import (
    synchronize_group,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "hourly_feature_pipeline_report.json"
)


class HourlyFeaturePipelineError(
    RuntimeError
):
    """Raised when hourly feature preparation fails."""


def generate_pipeline_run_id() -> str:
    """Generate one traceable hourly pipeline-run ID."""

    timestamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")

    return (
        f"{timestamp}_hourly_features_"
        f"{uuid.uuid4().hex[:8]}"
    )


def normalize_hourly_timestamps(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """Normalize and sort one hourly source DataFrame."""

    if "datetime_utc" not in dataframe.columns:
        raise HourlyFeaturePipelineError(
            "Source data is missing datetime_utc."
        )

    result = dataframe.copy()

    result["datetime_utc"] = pd.to_datetime(
        result["datetime_utc"],
        utc=True,
        errors="raise",
    ).dt.floor("h")

    result = (
        result.sort_values("datetime_utc")
        .drop_duplicates(
            subset=["datetime_utc"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    return result


def select_observed_source_window(
    *,
    pm25_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    reference_time: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Select source observations up to the safe reference hour.

    Future Open-Meteo rows are forecast rows and must not be stored in the
    historical weather-observation feature group.
    """

    normalized_pm25 = (
        normalize_hourly_timestamps(
            pm25_df
        )
    )

    normalized_weather = (
        normalize_hourly_timestamps(
            weather_df
        )
    )

    observed_pm25 = normalized_pm25.loc[
        normalized_pm25[
            "datetime_utc"
        ].le(reference_time)
    ].copy()

    observed_weather = (
        normalized_weather.loc[
            normalized_weather[
                "datetime_utc"
            ].le(reference_time)
        ].copy()
    )

    if observed_pm25.empty:
        raise HourlyFeaturePipelineError(
            "No observed PM2.5 rows are available."
        )

    if observed_weather.empty:
        raise HourlyFeaturePipelineError(
            "No observed weather rows are available."
        )

    return (
        observed_pm25.reset_index(drop=True),
        observed_weather.reset_index(
            drop=True
        ),
    )


def build_recent_canonical_window(
    *,
    pm25_df: pd.DataFrame,
    weather_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Combine recent PM2.5 and observed weather.

    An outer join preserves valid PM2.5 and weather observations independently
    for their respective feature groups.
    """

    canonical_df = (
        pm25_df.merge(
            weather_df,
            on="datetime_utc",
            how="outer",
            suffixes=(
                "_pm25",
                "_weather",
            ),
        )
        .sort_values("datetime_utc")
        .drop_duplicates(
            subset=["datetime_utc"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    if canonical_df.empty:
        raise HourlyFeaturePipelineError(
            "The recent canonical window is empty."
        )

    return canonical_df


def build_live_engineered_features(
    *,
    pm25_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    reference_time: pd.Timestamp,
    contract: FeatureGroupContract,
) -> pd.DataFrame:
    """
    Build reusable reference-time features from live observed inputs.

    Initial rows that cannot satisfy lag or rolling-window requirements are
    excluded. No PM2.5 values are fabricated or interpolated.
    """

    feature_input_df = (
        pm25_df[
            [
                "datetime_utc",
                "pm25_ug_m3",
            ]
        ]
        .merge(
            weather_df,
            on="datetime_utc",
            how="inner",
            validate="one_to_one",
        )
        .sort_values("datetime_utc")
        .reset_index(drop=True)
    )

    if feature_input_df.empty:
        raise HourlyFeaturePipelineError(
            "PM2.5 and weather have no aligned observed hours."
        )

    engineered_df = (
        build_reference_feature_table(
            feature_input_df
        )
    )

    if engineered_df.empty:
        raise HourlyFeaturePipelineError(
            "Reference feature construction produced no rows."
        )

    if "reference_time" not in engineered_df.columns:
        raise HourlyFeaturePipelineError(
            "Reference feature output is missing reference_time."
        )

    engineered_df[
        "reference_time"
    ] = pd.to_datetime(
        engineered_df["reference_time"],
        utc=True,
        errors="raise",
    ).dt.floor("h")

    engineered_df = engineered_df.loc[
        engineered_df[
            "reference_time"
        ].le(reference_time)
    ].copy()

    required_feature_columns = [
        column
        for column in contract.feature_names
        if column not in {
            "location_key",
            "reference_time",
            "feature_pipeline_version",
            "pipeline_run_id",
        }
    ]

    missing_columns = sorted(
        set(required_feature_columns).difference(
            engineered_df.columns
        )
    )

    if missing_columns:
        raise HourlyFeaturePipelineError(
            "Live feature construction is missing "
            f"contract columns: {missing_columns}"
        )

    incomplete_mask = (
        engineered_df[
            required_feature_columns
        ]
        .isna()
        .any(axis=1)
    )

    complete_engineered_df = (
        engineered_df.loc[
            ~incomplete_mask
        ]
        .sort_values("reference_time")
        .drop_duplicates(
            subset=["reference_time"],
            keep="last",
        )
        .reset_index(drop=True)
    )

     ## temporary
    missing_counts = (
        engineered_df[
            required_feature_columns
        ]
        .isna()
        .sum()
        .sort_values(
            ascending=False
        )
    )

    print(
        "Engineered rows:",
        len(engineered_df),
    )

    print(
        "Reference range:",
        engineered_df[
            "reference_time"
        ].min(),
        "to",
        engineered_df[
            "reference_time"
        ].max(),
    )

    print(
        "Columns with missing values:"
    )

    print(
        missing_counts[
            missing_counts > 0
        ].to_string()
    )

    ## end

    if complete_engineered_df.empty:
        raise HourlyFeaturePipelineError(
            "No complete engineered reference rows are available. "
            "Recent PM2.5 history may contain missing required hours."
        )

    if (
        complete_engineered_df[
            "reference_time"
        ].max()
        != reference_time
    ):
        raise HourlyFeaturePipelineError(
            "The selected safe reference hour did not produce a complete "
            "engineered feature row."
        )

    return complete_engineered_df


def build_contracts(
    *,
    settings: MLOpsSettings,
) -> dict[str, FeatureGroupContract]:
    """Build the configured production feature-group contracts."""

    feature_columns_path = (
        PROJECT_ROOT
        / "models"
        / "model_feature_columns.json"
    )

    if not feature_columns_path.exists():
        raise FileNotFoundError(
            "Model feature contract was not found: "
            f"{feature_columns_path}"
        )

    model_feature_columns = (
        load_feature_columns(
            feature_columns_path
        )
    )

    return build_feature_group_contracts(
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


def prepare_feature_group_rows(
    *,
    canonical_df: pd.DataFrame,
    engineered_df: pd.DataFrame,
    contracts: dict[
        str,
        FeatureGroupContract,
    ],
    pipeline_run_id: str,
    retrieved_at_utc: pd.Timestamp,
    settings: MLOpsSettings,
) -> dict[str, pd.DataFrame]:
    """Prepare exact contract-ordered feature-group rows."""

    pm25_rows = prepare_pm25_rows(
        canonical_df=canonical_df,
        retrieved_at_utc=retrieved_at_utc,
        pipeline_run_id=pipeline_run_id,
        source_data_version=(
            settings.source_data_version
        ),
    )

    weather_rows = prepare_weather_rows(
        canonical_df=canonical_df,
        retrieved_at_utc=retrieved_at_utc,
        pipeline_run_id=pipeline_run_id,
        source_data_version=(
            settings.source_data_version
        ),
    )

    engineered_rows = (
        prepare_engineered_rows(
            training_df=engineered_df,
            contract=contracts[
                "engineered"
            ],
            pipeline_run_id=pipeline_run_id,
            feature_pipeline_version=(
                settings.feature_pipeline_version
            ),
        )
    )

    prepared_rows = {
        "pm25": order_for_contract(
            pm25_rows,
            contracts["pm25"],
        ),
        "weather": order_for_contract(
            weather_rows,
            contracts["weather"],
        ),
        "engineered": order_for_contract(
            engineered_rows,
            contracts["engineered"],
        ),
    }

    return prepared_rows


def run_hourly_feature_pipeline(
    *,
    mlops_settings: MLOpsSettings,
) -> dict[str, Any]:
    """Run one fresh hourly feature synchronization cycle."""

    started_at = datetime.now(
        timezone.utc
    )

    pipeline_run_id = (
        generate_pipeline_run_id()
    )

    contracts = build_contracts(
        settings=mlops_settings
    )

    openaq_client = OpenAQClient(
        app_settings=app_settings
    )

    weather_client = OpenMeteoClient(
        app_settings=app_settings
    )

    recent_pm25_df = (
        openaq_client
        .fetch_recent_hourly_pm25()
    )

    recent_weather_df = (
        weather_client
        .fetch_hourly_weather()
    )

    reference_selection = (
        select_latest_safe_reference_time(
            pm25_df=recent_pm25_df,
            weather_df=recent_weather_df,
            app_settings=app_settings,
        )
    )

    if not reference_selection.is_ready:
        raise HourlyFeaturePipelineError(
            "Live feature inputs are not ready. "
            f"Status={reference_selection.status}. "
            f"Message={reference_selection.message}"
        )

    reference_time = (
        reference_selection
        .selected_reference_time
    )

    if reference_time is None:
        raise HourlyFeaturePipelineError(
            "Reference selection returned no timestamp."
        )

    reference_time = pd.Timestamp(
        reference_time
    )

    if reference_time.tzinfo is None:
        reference_time = (
            reference_time.tz_localize(
                "UTC"
            )
        )
    else:
        reference_time = (
            reference_time.tz_convert(
                "UTC"
            )
        )

    reference_time = (
        reference_time.floor("h")
    )

    (
        observed_pm25_df,
        observed_weather_df,
    ) = select_observed_source_window(
        pm25_df=recent_pm25_df,
        weather_df=recent_weather_df,
        reference_time=reference_time,
    )

    canonical_df = (
        build_recent_canonical_window(
            pm25_df=observed_pm25_df,
            weather_df=observed_weather_df,
        )
    )

    engineered_df = (
        build_live_engineered_features(
            pm25_df=observed_pm25_df,
            weather_df=observed_weather_df,
            reference_time=reference_time,
            contract=contracts[
                "engineered"
            ],
        )
    )

    retrieved_at_utc = pd.Timestamp.now(
        tz="UTC"
    )

    prepared_rows = (
        prepare_feature_group_rows(
            canonical_df=canonical_df,
            engineered_df=engineered_df,
            contracts=contracts,
            pipeline_run_id=pipeline_run_id,
            retrieved_at_utc=(
                retrieved_at_utc
            ),
            settings=mlops_settings,
        )
    )

    repository = create_feature_repository(
        settings=mlops_settings,
        contracts=contracts,
    )

    group_reports: dict[
        str,
        dict[str, Any],
    ] = {}

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
                settings=mlops_settings,
            )
        )

    total_rows_to_insert = sum(
        int(
            report["rows_to_insert"]
        )
        for report in group_reports.values()
    )

    total_rows_to_update = sum(
        int(
            report["rows_to_update"]
        )
        for report in group_reports.values()
    )

    total_rows_written = sum(
        int(
            report["rows_written"]
        )
        for report in group_reports.values()
    )

    total_candidate_changes = (
        total_rows_to_insert
        + total_rows_to_update
    )

    if mlops_settings.mlops_dry_run:
        status = (
            "HOURLY_FEATURE_PIPELINE_"
            "DRY_RUN_COMPLETED"
        )
    elif total_candidate_changes == 0:
        status = (
            "HOURLY_FEATURE_PIPELINE_"
            "NO_CHANGES"
        )
    else:
        status = (
            "HOURLY_FEATURE_PIPELINE_"
            "COMPLETED"
        )

    completed_at = datetime.now(
        timezone.utc
    )

    return {
        "phase": "10K",
        "subphase": "10K-A",
        "pipeline_name": (
            "hourly_feature_pipeline"
        ),
        "pipeline_run_id": pipeline_run_id,
        "status": status,
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
        "dry_run": (
            mlops_settings.mlops_dry_run
        ),
        "reference_selection": {
            "status": (
                reference_selection.status
            ),
            "message": (
                reference_selection.message
            ),
            "selected_reference_time": (
                reference_time.isoformat()
            ),
            "latest_pm25_age_hours": (
                reference_selection
                .latest_pm25_age_hours
            ),
        },
        "source_data": {
            "pm25_rows_received": int(
                len(recent_pm25_df)
            ),
            "weather_rows_received": int(
                len(recent_weather_df)
            ),
            "observed_pm25_rows": int(
                len(observed_pm25_df)
            ),
            "observed_weather_rows": int(
                len(observed_weather_df)
            ),
            "canonical_rows": int(
                len(canonical_df)
            ),
            "complete_engineered_rows": int(
                len(engineered_df)
            ),
            "pm25_start": str(
                observed_pm25_df[
                    "datetime_utc"
                ].min()
            ),
            "pm25_end": str(
                observed_pm25_df[
                    "datetime_utc"
                ].max()
            ),
            "weather_start": str(
                observed_weather_df[
                    "datetime_utc"
                ].min()
            ),
            "weather_end": str(
                observed_weather_df[
                    "datetime_utc"
                ].max()
            ),
        },
        "feature_store": {
            "backend": (
                repository.backend_name
            ),
            "source": (
                repository.source_label
            ),
            "remote_writes_performed": (
                not mlops_settings.mlops_dry_run
                and total_rows_written > 0
            ),
            "total_rows_to_insert": (
                total_rows_to_insert
            ),
            "total_rows_to_update": (
                total_rows_to_update
            ),
            "total_rows_written": (
                total_rows_written
            ),
            "groups": group_reports,
        },
        "validation": {
            "safe_reference_selected": True,
            "future_weather_excluded": True,
            "engineered_reference_complete": True,
            "contract_ordering_applied": True,
            "incremental_overlap_applied": True,
            "only_changed_rows_writable": True,
        },
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Save the latest Phase 10K hourly pipeline report."""

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = (
        REPORT_PATH.with_suffix(
            REPORT_PATH.suffix + ".tmp"
        )
    )

    temporary_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
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
            "Fetch fresh live observations and "
            "incrementally synchronize hourly "
            "features with Hopsworks."
        )
    )

    parser.parse_args()

    try:
        mlops_settings = (
            get_mlops_settings()
        )

        report = (
            run_hourly_feature_pipeline(
                mlops_settings=(
                    mlops_settings
                )
            )
        )

        exit_code = 0

    except Exception as error:
        report = {
            "phase": "10K",
            "subphase": "10K-A",
            "pipeline_name": (
                "hourly_feature_pipeline"
            ),
            "status": (
                "HOURLY_FEATURE_PIPELINE_FAILED"
            ),
            "failed_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(error),
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