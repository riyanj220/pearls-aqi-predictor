"""Migrate production feature datasets from Hopsworks to Azure Blob.

Phase 10P-D performs a one-time production feature migration while keeping
Hopsworks as the active production backend.

The migration:

1. reads the complete configured Hopsworks feature datasets;
2. validates them against the existing feature contracts;
3. writes them through AzureBlobFeatureRepository;
4. reads the Blob copies back;
5. compares row counts, keys, ranges, schemas, and deterministic content;
6. writes a structured migration report.

Production configuration is not changed by this operation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import PROJECT_ROOT
from app.mlops.azure_blob_feature_repository import (
    AzureBlobFeatureRepository,
)
from app.mlops.config import (
    FeatureStoreBackend,
    MLOpsSettings,
    get_mlops_settings,
)
from app.mlops.contracts import (
    FeatureGroupContract,
    build_feature_group_contracts,
)
from app.mlops.feature_repository import (
    FeatureRepository,
)
from app.mlops.hopsworks_feature_repository import (
    HopsworksFeatureRepository,
)
from app.pipelines.historical_backfill import (
    load_feature_columns,
    order_for_contract,
)


REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "hopsworks_to_blob_feature_migration_report.json"
)


class FeatureMigrationError(
    RuntimeError
):
    """Raised when feature migration or parity validation fails."""


def build_contracts(
    *,
    settings: MLOpsSettings,
) -> dict[str, FeatureGroupContract]:
    """Build the current production feature contracts."""

    feature_columns_path = (
        PROJECT_ROOT
        / "models"
        / "model_feature_columns.json"
    )

    if not feature_columns_path.exists():
        raise FileNotFoundError(
            "Model feature contract does not exist: "
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


def normalize_source_dataframe(
    *,
    dataframe: pd.DataFrame,
    contract: FeatureGroupContract,
) -> pd.DataFrame:
    """Normalize one repository dataset using the canonical contract."""

    if dataframe.empty:
        raise FeatureMigrationError(
            f"Source dataset is empty: {contract.name}"
        )

    dataframe = dataframe.copy()

    dataframe.columns = [
        str(column).lower()
        for column in dataframe.columns
    ]

    missing_columns = sorted(
        set(
            contract.feature_names
        ).difference(
            dataframe.columns
        )
    )

    if missing_columns:
        raise FeatureMigrationError(
            f"{contract.name} is missing contract columns: "
            f"{missing_columns}"
        )

    dataframe = dataframe[
        contract.feature_names
    ].copy()

    dataframe = order_for_contract(
        dataframe,
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

    dataframe = (
        dataframe
        .sort_values(
            logical_key
        )
        .drop_duplicates(
            subset=logical_key,
            keep="last",
        )
        .reset_index(
            drop=True
        )
    )

    contract.validate_dataframe(
        dataframe
    )

    return dataframe


def logical_key_columns(
    contract: FeatureGroupContract,
) -> list[str]:
    """Return deterministic logical key columns."""

    return list(
        dict.fromkeys(
            [
                *contract.primary_key,
                contract.event_time,
            ]
        )
    )


def duplicate_key_count(
    *,
    dataframe: pd.DataFrame,
    contract: FeatureGroupContract,
) -> int:
    """Count duplicate logical rows."""

    return int(
        dataframe.duplicated(
            subset=logical_key_columns(
                contract
            )
        ).sum()
    )


def event_time_range(
    *,
    dataframe: pd.DataFrame,
    contract: FeatureGroupContract,
) -> dict[str, str]:
    """Return normalized event-time range."""

    event_times = pd.to_datetime(
        dataframe[
            contract.event_time
        ],
        utc=True,
        errors="raise",
    )

    return {
        "minimum": (
            event_times
            .min()
            .isoformat()
        ),
        "maximum": (
            event_times
            .max()
            .isoformat()
        ),
    }


def dataframe_digest(
    *,
    dataframe: pd.DataFrame,
    contract: FeatureGroupContract,
) -> str:
    """Return a deterministic content digest for one logical dataset."""

    logical_keys = (
        logical_key_columns(
            contract
        )
    )

    ordered = (
        dataframe[
            contract.feature_names
        ]
        .sort_values(
            logical_keys
        )
        .reset_index(
            drop=True
        )
        .copy()
    )

    for feature in contract.features:
        column = feature.name

        if feature.offline_type == "timestamp":
            ordered[column] = (
                pd.to_datetime(
                    ordered[column],
                    utc=True,
                    errors="raise",
                )
                .map(
                    lambda value: (
                        value.isoformat()
                    )
                )
            )

        elif feature.offline_type == "double":
            ordered[column] = (
                pd.to_numeric(
                    ordered[column],
                    errors="coerce",
                )
                .round(10)
            )

    payload = ordered.to_json(
        orient="records",
        date_format="iso",
        double_precision=10,
    ).encode(
        "utf-8"
    )

    return hashlib.sha256(
        payload
    ).hexdigest()


def compare_datasets(
    *,
    source: pd.DataFrame,
    target: pd.DataFrame,
    contract: FeatureGroupContract,
) -> dict[str, Any]:
    """Compare source and migrated feature datasets."""

    source_keys = (
        logical_key_columns(
            contract
        )
    )

    source_key_frame = (
        source[
            source_keys
        ]
        .sort_values(
            source_keys
        )
        .reset_index(
            drop=True
        )
    )

    target_key_frame = (
        target[
            source_keys
        ]
        .sort_values(
            source_keys
        )
        .reset_index(
            drop=True
        )
    )

    source_digest = dataframe_digest(
        dataframe=source,
        contract=contract,
    )

    target_digest = dataframe_digest(
        dataframe=target,
        contract=contract,
    )

    checks = {
        "row_count_matches": (
            len(source)
            == len(target)
        ),
        "columns_match": (
            list(source.columns)
            == list(target.columns)
        ),
        "logical_keys_match": (
            source_key_frame.equals(
                target_key_frame
            )
        ),
        "event_time_range_matches": (
            event_time_range(
                dataframe=source,
                contract=contract,
            )
            == event_time_range(
                dataframe=target,
                contract=contract,
            )
        ),
        "source_has_no_duplicate_keys": (
            duplicate_key_count(
                dataframe=source,
                contract=contract,
            )
            == 0
        ),
        "target_has_no_duplicate_keys": (
            duplicate_key_count(
                dataframe=target,
                contract=contract,
            )
            == 0
        ),
        "content_digest_matches": (
            source_digest
            == target_digest
        ),
    }

    return {
        "checks": checks,
        "valid": all(
            checks.values()
        ),
        "source": {
            "rows": int(
                len(source)
            ),
            "columns": list(
                source.columns
            ),
            "duplicate_keys": (
                duplicate_key_count(
                    dataframe=source,
                    contract=contract,
                )
            ),
            "event_time_range": (
                event_time_range(
                    dataframe=source,
                    contract=contract,
                )
            ),
            "content_sha256": (
                source_digest
            ),
        },
        "target": {
            "rows": int(
                len(target)
            ),
            "columns": list(
                target.columns
            ),
            "duplicate_keys": (
                duplicate_key_count(
                    dataframe=target,
                    contract=contract,
                )
            ),
            "event_time_range": (
                event_time_range(
                    dataframe=target,
                    contract=contract,
                )
            ),
            "content_sha256": (
                target_digest
            ),
        },
    }


def build_hopsworks_settings(
    settings: MLOpsSettings,
) -> MLOpsSettings:
    """Create source settings explicitly targeting Hopsworks."""

    payload = settings.model_dump()

    payload[
        "feature_store_backend"
    ] = FeatureStoreBackend.HOPSWORKS

    return MLOpsSettings(
        **payload
    )


def build_blob_settings(
    settings: MLOpsSettings,
) -> MLOpsSettings:
    """Create target settings explicitly targeting Azure Blob."""

    payload = settings.model_dump()

    payload[
        "feature_store_backend"
    ] = FeatureStoreBackend.AZURE_BLOB

    return MLOpsSettings(
        **payload
    )


def migrate_dataset(
    *,
    source_repository: FeatureRepository,
    target_repository: FeatureRepository,
    contract: FeatureGroupContract,
) -> dict[str, Any]:
    """Migrate and validate one complete feature dataset."""

    source_raw = (
        source_repository
        .read_dataset(
            contract=contract
        )
    )

    source = (
        normalize_source_dataframe(
            dataframe=source_raw,
            contract=contract,
        )
    )

    target_repository.upsert(
        contract=contract,
        dataframe=source,
    )

    target_raw = (
        target_repository
        .read_dataset(
            contract=contract
        )
    )

    target = (
        normalize_source_dataframe(
            dataframe=target_raw,
            contract=contract,
        )
    )

    comparison = compare_datasets(
        source=source,
        target=target,
        contract=contract,
    )

    if not comparison["valid"]:
        raise FeatureMigrationError(
            "Feature migration parity failed for "
            f"{contract.name}: "
            f"{comparison['checks']}"
        )

    return {
        "dataset_name": (
            contract.name
        ),
        "dataset_version": (
            contract.version
        ),
        "status": (
            "FEATURE_DATASET_MIGRATED"
        ),
        "comparison": (
            comparison
        ),
    }


def run_migration(
    *,
    settings: MLOpsSettings,
) -> dict[str, Any]:
    """Run one complete Hopsworks-to-Blob feature migration."""

    started_at = datetime.now(
        timezone.utc
    )

    contracts = build_contracts(
        settings=settings
    )

    source_settings = (
        build_hopsworks_settings(
            settings
        )
    )

    target_settings = (
        build_blob_settings(
            settings
        )
    )

    source_repository = (
        HopsworksFeatureRepository(
            settings=source_settings,
            contracts=contracts,
            create_if_missing=False,
        )
    )

    target_repository = (
        AzureBlobFeatureRepository(
            settings=target_settings,
            contracts=contracts,
        )
    )

    dataset_reports: dict[
        str,
        dict[str, Any],
    ] = {}

    for dataset_name in (
        "pm25",
        "weather",
        "engineered",
    ):
        dataset_reports[
            dataset_name
        ] = migrate_dataset(
            source_repository=(
                source_repository
            ),
            target_repository=(
                target_repository
            ),
            contract=contracts[
                dataset_name
            ],
        )

    all_valid = all(
        bool(
            report[
                "comparison"
            ][
                "valid"
            ]
        )
        for report
        in dataset_reports.values()
    )

    if not all_valid:
        raise FeatureMigrationError(
            "One or more migrated feature datasets "
            "failed parity validation."
        )

    completed_at = datetime.now(
        timezone.utc
    )

    return {
        "phase": "10P",
        "subphase": "10P-D",
        "status": (
            "HOPSWORKS_TO_BLOB_FEATURE_MIGRATION_VALIDATED"
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
        "source_backend": (
            source_repository.backend_name
        ),
        "source_label": (
            source_repository.source_label
        ),
        "target_backend": (
            target_repository.backend_name
        ),
        "target_label": (
            target_repository.source_label
        ),
        "azure_storage_account": (
            target_settings
            .azure_storage_account
        ),
        "azure_storage_container": (
            target_settings
            .azure_storage_container
        ),
        "azure_feature_store_prefix": (
            target_settings
            .azure_feature_store_prefix
        ),
        "datasets": (
            dataset_reports
        ),
        "validation": {
            "all_datasets_migrated": (
                len(dataset_reports)
                == 3
            ),
            "all_dataset_parity_checks_passed": (
                all_valid
            ),
            "production_backend_changed": False,
            "hopsworks_source_preserved": True,
        },
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Persist the Phase 10P-D migration report."""

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = (
        REPORT_PATH.with_suffix(
            ".json.tmp"
        )
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
            "Migrate production feature datasets "
            "from Hopsworks to Azure Blob."
        )
    )

    parser.parse_args()

    try:
        settings = (
            get_mlops_settings()
        )

        report = run_migration(
            settings=settings
        )

        exit_code = 0

    except Exception as error:
        report = {
            "phase": "10P",
            "subphase": "10P-D",
            "status": (
                "HOPSWORKS_TO_BLOB_FEATURE_MIGRATION_FAILED"
            ),
            "failed_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(
                error
            ),
            "production_backend_changed": False,
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
    raise SystemExit(
        main()
    )
