"""Validated historical migration into Hopsworks."""

from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.mlops.client import (
    connect_to_hopsworks,
)
from app.mlops.config import (
    MLOpsSettings,
    get_mlops_settings,
)
from app.mlops.contracts import (
    FeatureGroupContract,
    LOCATION_KEY,
    OPENAQ_LOCATION_ID,
    OPENAQ_SENSOR_ID,
    build_feature_group_contracts,
)
from app.mlops.feature_groups import (
    create_or_get_feature_groups,
)
from app.mlops.gaps import (
    detect_hourly_gaps,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RowClassification:
    """Rows classified against current feature-store data."""

    inserted: int
    updated: int
    unchanged: int
    writable: pd.DataFrame


def load_feature_columns(
    path: Path,
) -> list[str]:
    """Load an ordered feature-column artifact."""

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if isinstance(payload, list):
        return [
            str(value)
            for value in payload
        ]

    for key in (
        "feature_columns",
        "model_feature_columns",
        "features",
        "columns",
    ):
        values = payload.get(key)

        if isinstance(values, list):
            return [
                str(value)
                for value in values
            ]

    raise ValueError(
        f"No feature-column list found in {path}."
    )


def resolve_column(
    dataframe: pd.DataFrame,
    candidates: list[str],
) -> str:
    """Resolve the first available column alias."""

    for candidate in candidates:
        if candidate in dataframe.columns:
            return candidate

    raise ValueError(
        "None of the expected columns exist: "
        f"{candidates}"
    )


def normalize_timestamp_column(
    dataframe: pd.DataFrame,
    column: str,
) -> pd.DataFrame:
    """Normalize one timestamp column to UTC hourly values."""

    result = dataframe.copy()

    result[column] = pd.to_datetime(
        result[column],
        utc=True,
        errors="coerce",
    ).dt.floor("h")

    if result[column].isna().any():
        raise ValueError(
            f"{column} contains invalid timestamps."
        )

    return result


def prepare_pm25_rows(
    *,
    canonical_df: pd.DataFrame,
    retrieved_at_utc: pd.Timestamp,
    pipeline_run_id: str,
    source_data_version: str,
) -> pd.DataFrame:
    """Prepare validated PM2.5 observation rows."""

    timestamp_column = resolve_column(
        canonical_df,
        [
            "datetime_utc",
            "timestamp_utc",
            "date_utc",
            "datetime",
        ],
    )

    pm25_column = resolve_column(
        canonical_df,
        [
            "pm25_ug_m3",
            "pm25",
            "value",
        ],
    )

    result = canonical_df[
        [
            timestamp_column,
            pm25_column,
        ]
    ].copy()

    result = result.rename(
        columns={
            timestamp_column: "datetime_utc",
            pm25_column: "pm25_ug_m3",
        }
    )

    result = normalize_timestamp_column(
        result,
        "datetime_utc",
    )

    result["pm25_ug_m3"] = pd.to_numeric(
        result["pm25_ug_m3"],
        errors="coerce",
    )

    result.loc[
        result["pm25_ug_m3"] <= 0,
        "pm25_ug_m3",
    ] = pd.NA

    result["location_key"] = LOCATION_KEY
    result["location_id"] = OPENAQ_LOCATION_ID
    result["sensor_id"] = OPENAQ_SENSOR_ID

    result["pm25_is_missing"] = (
        result["pm25_ug_m3"].isna()
    )

    result["pm25_quality_status"] = (
        result["pm25_is_missing"].map(
            {
                True: "MISSING",
                False: "VALID",
            }
        )
    )

    result["source"] = "OpenAQ"
    result["retrieved_at_utc"] = retrieved_at_utc
    result["pipeline_run_id"] = pipeline_run_id
    result["source_data_version"] = (
        source_data_version
    )

    return result


WEATHER_ALIASES: dict[str, list[str]] = {
    "temperature_2m_c": [
        "temperature_2m_c",
        "temperature_2m",
    ],
    "relative_humidity_2m_pct": [
        "relative_humidity_2m_pct",
        "relative_humidity_2m",
    ],
    "dew_point_2m_c": [
        "dew_point_2m_c",
        "dew_point_2m",
    ],
    "surface_pressure_hpa": [
        "surface_pressure_hpa",
        "surface_pressure",
    ],
    "precipitation_mm": [
        "precipitation_mm",
        "precipitation",
    ],
    "rain_mm": [
        "rain_mm",
        "rain",
    ],
    "cloud_cover_pct": [
        "cloud_cover_pct",
        "cloud_cover",
    ],
    "wind_speed_10m_kmh": [
        "wind_speed_10m_kmh",
        "wind_speed_10m",
    ],
    "wind_direction_10m_deg": [
        "wind_direction_10m_deg",
        "wind_direction_10m",
    ],
    "wind_gusts_10m_kmh": [
        "wind_gusts_10m_kmh",
        "wind_gusts_10m",
    ],
}


def prepare_weather_rows(
    *,
    canonical_df: pd.DataFrame,
    retrieved_at_utc: pd.Timestamp,
    pipeline_run_id: str,
    source_data_version: str,
) -> pd.DataFrame:
    """Prepare validated historical weather rows."""

    timestamp_column = resolve_column(
        canonical_df,
        [
            "datetime_utc",
            "timestamp_utc",
            "date_utc",
            "datetime",
        ],
    )

    selected_columns = {
        "datetime_utc": timestamp_column,
    }

    for target_name, aliases in WEATHER_ALIASES.items():
        selected_columns[target_name] = (
            resolve_column(
                canonical_df,
                aliases,
            )
        )

    result = canonical_df[
        list(selected_columns.values())
    ].copy()

    result = result.rename(
        columns={
            source: target
            for target, source
            in selected_columns.items()
        }
    )

    result = normalize_timestamp_column(
        result,
        "datetime_utc",
    )

    for weather_column in WEATHER_ALIASES:
        result[weather_column] = pd.to_numeric(
            result[weather_column],
            errors="coerce",
        )

    result["location_key"] = LOCATION_KEY
    result["source"] = "Open-Meteo"
    result["retrieved_at_utc"] = retrieved_at_utc
    result["pipeline_run_id"] = pipeline_run_id
    result["source_data_version"] = (
        source_data_version
    )

    return result


def prepare_engineered_rows(
    *,
    training_df: pd.DataFrame,
    contract: FeatureGroupContract,
    pipeline_run_id: str,
    feature_pipeline_version: str,
) -> pd.DataFrame:
    """Extract one reusable feature row per reference hour."""

    reference_column = resolve_column(
        training_df,
        [
            "reference_time",
            "reference_time_utc",
        ],
    )

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

    missing_features = [
        column
        for column in required_feature_columns
        if column not in training_df.columns
    ]

    if missing_features:
        raise ValueError(
            "Training dataset is missing engineered "
            f"features: {missing_features}"
        )

    result = training_df[
        [
            reference_column,
            *required_feature_columns,
        ]
    ].copy()

    result = result.rename(
        columns={
            reference_column: "reference_time",
        }
    )

    result = normalize_timestamp_column(
        result,
        "reference_time",
    )

    result = (
        result.sort_values("reference_time")
        .drop_duplicates(
            subset=["reference_time"],
            keep="first",
        )
        .reset_index(drop=True)
    )

    result["location_key"] = LOCATION_KEY
    result["feature_pipeline_version"] = (
        feature_pipeline_version
    )
    result["pipeline_run_id"] = pipeline_run_id

    return result


def filter_backfill_range(
    *,
    dataframe: pd.DataFrame,
    timestamp_column: str,
    start_time_utc: pd.Timestamp,
    end_time_utc: pd.Timestamp,
) -> pd.DataFrame:
    """Filter rows using inclusive hourly boundaries."""

    return dataframe.loc[
        dataframe[timestamp_column].between(
            start_time_utc,
            end_time_utc,
            inclusive="both",
        )
    ].copy()


def coerce_to_contract_types(
    dataframe: pd.DataFrame,
    contract: FeatureGroupContract,
) -> pd.DataFrame:
    """Coerce DataFrame columns to the explicit feature-group schema."""

    result = dataframe.copy()

    for feature in contract.features:
        column = feature.name

        if column not in result.columns:
            continue

        if feature.offline_type == "double":
            result[column] = pd.to_numeric(
                result[column],
                errors="coerce",
            ).astype("float64")

        elif feature.offline_type == "bigint":
            numeric_values = pd.to_numeric(
                result[column],
                errors="raise",
            )

            if numeric_values.isna().any():
                raise ValueError(
                    f"{contract.name}.{column} contains "
                    "null values but requires bigint."
                )

            result[column] = numeric_values.astype(
                "int64"
            )

        elif feature.offline_type == "boolean":
            result[column] = result[column].astype(
                "bool"
            )

        elif feature.offline_type == "string":
            result[column] = result[column].astype(
                "string"
            )

        elif feature.offline_type == "timestamp":
            result[column] = pd.to_datetime(
                result[column],
                utc=True,
                errors="raise",
            )

        else:
            raise ValueError(
                f"Unsupported offline type "
                f"{feature.offline_type!r} for "
                f"{contract.name}.{column}."
            )

    return result


def order_for_contract(
    dataframe: pd.DataFrame,
    contract: FeatureGroupContract,
) -> pd.DataFrame:
    """Apply exact schema types and feature-group column order."""

    result = coerce_to_contract_types(
        dataframe,
        contract,
    )

    result = result[
        contract.feature_names
    ].copy()

    contract.validate_dataframe(
        result
    )

    return result


def empty_existing_frame(
    contract: FeatureGroupContract,
) -> pd.DataFrame:
    """Create an empty frame matching a contract."""

    return pd.DataFrame(
        columns=contract.feature_names
    )


def read_existing_rows(
    *,
    feature_group: Any | None,
    contract: FeatureGroupContract,
    start_time_utc: pd.Timestamp,
    end_time_exclusive_utc: pd.Timestamp,
) -> pd.DataFrame:
    """Read existing feature-store rows for the period."""

    if feature_group is None:
        return empty_existing_frame(
            contract
        )

    try:
        existing = feature_group.read(
            dataframe_type="pandas",
            start_time=start_time_utc.to_pydatetime(),
            end_time=(
                end_time_exclusive_utc.to_pydatetime()
            ),
        )
    except Exception:
        return empty_existing_frame(
            contract
        )

    if existing is None or existing.empty:
        return empty_existing_frame(
            contract
        )

    existing.columns = [
        str(column).lower()
        for column in existing.columns
    ]

    return existing


def values_equal(
    left: object,
    right: object,
) -> bool:
    """Compare values while treating paired nulls as equal."""

    if pd.isna(left) and pd.isna(right):
        return True

    if isinstance(left, float) or isinstance(
        right,
        float,
    ):
        try:
            return bool(
                abs(float(left) - float(right))
                <= 1e-9
            )
        except (TypeError, ValueError):
            pass

    return left == right

def normalize_logical_keys(
    dataframe: pd.DataFrame,
    contract: FeatureGroupContract,
) -> pd.DataFrame:
    """Normalize logical-key columns before row comparison."""

    result = dataframe.copy()

    for column in contract.primary_key:
        if column in result.columns:
            if column.endswith("_id"):
                result[column] = pd.to_numeric(
                    result[column],
                    errors="raise",
                ).astype("int64")
            else:
                result[column] = (
                    result[column]
                    .astype("string")
                    .str.strip()
                )

    result[contract.event_time] = pd.to_datetime(
        result[contract.event_time],
        utc=True,
        errors="raise",
    ).dt.floor("h")

    return result

def classify_rows(
    *,
    candidate: pd.DataFrame,
    existing: pd.DataFrame,
    contract: FeatureGroupContract,
) -> RowClassification:
    """Classify candidate rows as inserted, updated, or unchanged."""

    candidate = normalize_logical_keys(
        candidate,
        contract,
    )

    existing = normalize_logical_keys(
        existing,
        contract,
    )

    logical_key = list(
        dict.fromkeys(
            [
                *contract.primary_key,
                contract.event_time,
            ]
        )
    )

    if existing.empty:
        return RowClassification(
            inserted=len(candidate),
            updated=0,
            unchanged=0,
            writable=candidate.copy(),
        )

    existing_indexed = existing.set_index(
        logical_key,
        drop=False,
    )

    inserted_rows: list[int] = []
    updated_rows: list[int] = []
    unchanged_count = 0

    comparable_columns = [
        column
        for column in contract.feature_names
        if column not in logical_key
        and column not in {
            "pipeline_run_id",
            "retrieved_at_utc",
        }
    ]

    for row_index, row in candidate.iterrows():
        key_values = tuple(
            row[column]
            for column in logical_key
        )

        lookup_key: object = (
            key_values[0]
            if len(key_values) == 1
            else key_values
        )

        if lookup_key not in existing_indexed.index:
            inserted_rows.append(row_index)
            continue

        existing_row = existing_indexed.loc[
            lookup_key
        ]

        if isinstance(
            existing_row,
            pd.DataFrame,
        ):
            existing_row = existing_row.iloc[0]

        changed = any(
            not values_equal(
                row[column],
                existing_row.get(column),
            )
            for column in comparable_columns
        )

        if changed:
            updated_rows.append(row_index)
        else:
            unchanged_count += 1

    writable_indices = [
        *inserted_rows,
        *updated_rows,
    ]

    return RowClassification(
        inserted=len(inserted_rows),
        updated=len(updated_rows),
        unchanged=unchanged_count,
        writable=candidate.loc[
            writable_indices
        ].copy(),
    )


def upsert_rows(
    *,
    feature_group: Any,
    dataframe: pd.DataFrame,
) -> None:
    """Upsert prepared rows and wait for completion."""

    if dataframe.empty:
        return

    feature_group.insert(
        dataframe,
        operation="upsert",
        wait=True,
    )


def parse_utc_hour(
    value: str,
) -> pd.Timestamp:
    """Parse one CLI timestamp as a UTC hour."""

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


def run_historical_backfill(
    *,
    start_time_utc: pd.Timestamp,
    end_time_utc: pd.Timestamp,
    settings: MLOpsSettings,
) -> dict[str, Any]:
    """Run dry-run or real historical feature migration."""

    if start_time_utc > end_time_utc:
        raise ValueError(
            "Start time must not be after end time."
        )

    run_id = (
        "historical_backfill_"
        + uuid.uuid4().hex
    )

    started_at = datetime.now(
        timezone.utc
    )

    canonical_path = (
        PROJECT_ROOT
        / settings.phase_1_canonical_dataset_path
    )

    training_path = (
        PROJECT_ROOT
        / settings.phase_2_training_dataset_path
    )

    model_columns_path = (
        PROJECT_ROOT
        / "models"
        / "model_feature_columns.json"
    )

    for required_path in (
        canonical_path,
        training_path,
        model_columns_path,
    ):
        if not required_path.exists():
            raise FileNotFoundError(
                f"Required artifact not found: {required_path}"
            )

    canonical_df = pd.read_parquet(
        canonical_path
    )

    training_df = pd.read_parquet(
        training_path
    )

    model_feature_columns = (
        load_feature_columns(
            model_columns_path
        )
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
            settings.hopsworks_engineered_feature_group_name
        ),
        model_feature_columns=(
            model_feature_columns
        ),
    )

    retrieved_at = pd.Timestamp.now(
        tz="UTC"
    )

    pm25_rows = prepare_pm25_rows(
        canonical_df=canonical_df,
        retrieved_at_utc=retrieved_at,
        pipeline_run_id=run_id,
        source_data_version=(
            settings.source_data_version
        ),
    )

    weather_rows = prepare_weather_rows(
        canonical_df=canonical_df,
        retrieved_at_utc=retrieved_at,
        pipeline_run_id=run_id,
        source_data_version=(
            settings.source_data_version
        ),
    )

    engineered_rows = prepare_engineered_rows(
        training_df=training_df,
        contract=contracts["engineered"],
        pipeline_run_id=run_id,
        feature_pipeline_version=(
            settings.feature_pipeline_version
        ),
    )

    pm25_rows = filter_backfill_range(
        dataframe=pm25_rows,
        timestamp_column="datetime_utc",
        start_time_utc=start_time_utc,
        end_time_utc=end_time_utc,
    )

    weather_rows = filter_backfill_range(
        dataframe=weather_rows,
        timestamp_column="datetime_utc",
        start_time_utc=start_time_utc,
        end_time_utc=end_time_utc,
    )

    engineered_rows = filter_backfill_range(
        dataframe=engineered_rows,
        timestamp_column="reference_time",
        start_time_utc=start_time_utc,
        end_time_utc=end_time_utc,
    )

    prepared = {
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

    resources = connect_to_hopsworks(
        settings
    )

    resolved = create_or_get_feature_groups(
        resources=resources,
        settings=settings,
        contracts=contracts,
    )

    handles = {
        "pm25": resolved.pm25,
        "weather": resolved.weather,
        "engineered": resolved.engineered,
    }

    end_exclusive = (
        end_time_utc
        + pd.Timedelta(hours=1)
    )

    group_reports: dict[str, Any] = {}

    for group_name, dataframe in prepared.items():
        contract = contracts[group_name]
        feature_group = handles[group_name]

        existing = read_existing_rows(
            feature_group=feature_group,
            contract=contract,
            start_time_utc=start_time_utc,
            end_time_exclusive_utc=end_exclusive,
        )

        classification = classify_rows(
            candidate=dataframe,
            existing=existing,
            contract=contract,
        )

        gap_timestamp_column = (
            contract.event_time
        )

        source_gaps = detect_hourly_gaps(
            timestamps=dataframe[
                gap_timestamp_column
            ],
            start_time_utc=start_time_utc,
            end_time_utc=end_time_utc,
        )

        if (
            not settings.mlops_dry_run
            and feature_group is not None
        ):
            upsert_rows(
                feature_group=feature_group,
                dataframe=(
                    classification.writable
                ),
            )

        group_reports[group_name] = {
            "feature_group_name": contract.name,
            "version": contract.version,
            "candidate_rows": int(
                len(dataframe)
            ),
            "existing_rows_in_range": int(
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
                dataframe.duplicated(
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
            "missing_interval_count": len(
                source_gaps
            ),
            "missing_intervals": [
                interval.to_dict()
                for interval in source_gaps
            ],
        }

    completed_at = datetime.now(
        timezone.utc
    )

    return {
        "phase": "9D",
        "pipeline_run_id": run_id,
        "pipeline_name": (
            "historical_feature_backfill"
        ),
        "status": (
            "BACKFILL_DRY_RUN_SUCCESS"
            if settings.mlops_dry_run
            else "BACKFILL_SUCCESS"
        ),
        "started_at_utc": (
            started_at.isoformat()
        ),
        "completed_at_utc": (
            completed_at.isoformat()
        ),
        "start_time_utc": (
            start_time_utc.isoformat()
        ),
        "end_time_utc": (
            end_time_utc.isoformat()
        ),
        "dry_run": settings.mlops_dry_run,
        "remote_writes_performed": (
            not settings.mlops_dry_run
        ),
        "canonical_dataset_path": str(
            canonical_path.relative_to(
                PROJECT_ROOT
            )
        ),
        "training_dataset_path": str(
            training_path.relative_to(
                PROJECT_ROOT
            )
        ),
        "feature_group_versions": {
            "pm25": (
                settings.hopsworks_pm25_feature_group_version
            ),
            "weather": (
                settings.hopsworks_weather_feature_group_version
            ),
            "engineered": (
                settings.hopsworks_engineered_feature_group_version
            ),
        },
        "groups": group_reports,
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Persist the structured backfill report."""

    report_directory = (
        PROJECT_ROOT
        / "reports"
        / "phase_9"
    )

    report_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    filename = (
        "historical_backfill_dry_run_report.json"
        if report["dry_run"]
        else "historical_backfill_report.json"
    )

    report_path = (
        report_directory
        / filename
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
            "Migrate validated historical features "
            "into Hopsworks."
        )
    )

    parser.add_argument(
        "--start",
        required=True,
        help="Inclusive UTC start timestamp.",
    )

    parser.add_argument(
        "--end",
        required=True,
        help="Inclusive UTC end timestamp.",
    )

    arguments = parser.parse_args()

    settings = get_mlops_settings()

    try:
        report = run_historical_backfill(
            start_time_utc=parse_utc_hour(
                arguments.start
            ),
            end_time_utc=parse_utc_hour(
                arguments.end
            ),
            settings=settings,
        )

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

        return 0

    except Exception as error:
        failure_report = {
            "phase": "9D",
            "pipeline_name": (
                "historical_feature_backfill"
            ),
            "status": "BACKFILL_FAILED",
            "completed_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "error_type": type(error).__name__,
            "error_message": str(error),
        }

        report_path = save_report(
            {
                **failure_report,
                "dry_run": (
                    get_mlops_settings()
                    .mlops_dry_run
                ),
            }
        )

        print(
            json.dumps(
                failure_report,
                indent=2,
            )
        )

        print(
            "Failure report saved:",
            report_path,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())