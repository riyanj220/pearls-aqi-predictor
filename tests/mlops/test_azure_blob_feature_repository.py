from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.artifacts.repository import (
    LocalArtifactRepository,
)
from app.mlops.azure_blob_feature_repository import (
    AzureBlobFeatureRepository,
)
from app.mlops.config import MLOpsSettings
from app.mlops.contracts import (
    FeatureDefinition,
    FeatureGroupContract,
)


def build_contract() -> FeatureGroupContract:
    return FeatureGroupContract(
        name="test_hourly_features",
        version=1,
        description="Test dataset.",
        primary_key=(
            "location_key",
        ),
        event_time="datetime_utc",
        online_enabled=False,
        features=(
            FeatureDefinition(
                name="location_key",
                offline_type="string",
                description="Location.",
            ),
            FeatureDefinition(
                name="datetime_utc",
                offline_type="timestamp",
                description="Event time.",
            ),
            FeatureDefinition(
                name="value",
                offline_type="double",
                description="Value.",
            ),
        ),
    )


def build_repository(
    tmp_path: Path,
) -> tuple[
    AzureBlobFeatureRepository,
    FeatureGroupContract,
]:
    contract = build_contract()

    settings = MLOpsSettings(
        feature_store_backend=(
            "azure_blob"
        ),
        azure_storage_account=(
            "testaccount"
        ),
        azure_storage_container=(
            "testcontainer"
        ),
        azure_feature_store_prefix=(
            "feature-store"
        ),
    )

    transport = (
        LocalArtifactRepository(
            root_directory=tmp_path
        )
    )

    repository = (
        AzureBlobFeatureRepository(
            settings=settings,
            contracts={
                "test": contract,
            },
            repository=transport,
        )
    )

    return repository, contract


def test_empty_repository_returns_empty_frame(
    tmp_path: Path,
) -> None:
    repository, contract = (
        build_repository(
            tmp_path
        )
    )

    dataframe = repository.read_dataset(
        contract=contract
    )

    assert dataframe.empty

    assert list(
        dataframe.columns
    ) == contract.feature_names


def test_upsert_inserts_and_updates_rows(
    tmp_path: Path,
) -> None:
    repository, contract = (
        build_repository(
            tmp_path
        )
    )

    initial = pd.DataFrame(
        {
            "location_key": [
                "karachi",
                "karachi",
            ],
            "datetime_utc": (
                pd.to_datetime(
                    [
                        "2026-08-09T00:00:00Z",
                        "2026-08-09T01:00:00Z",
                    ],
                    utc=True,
                )
            ),
            "value": [
                10.0,
                11.0,
            ],
        }
    )

    repository.upsert(
        contract=contract,
        dataframe=initial,
    )

    update = pd.DataFrame(
        {
            "location_key": [
                "karachi",
                "karachi",
            ],
            "datetime_utc": (
                pd.to_datetime(
                    [
                        "2026-08-09T01:00:00Z",
                        "2026-08-09T02:00:00Z",
                    ],
                    utc=True,
                )
            ),
            "value": [
                99.0,
                12.0,
            ],
        }
    )

    repository.upsert(
        contract=contract,
        dataframe=update,
    )

    result = repository.read_dataset(
        contract=contract
    )

    assert len(result) == 3

    updated_value = (
        result.loc[
            result[
                "datetime_utc"
            ].eq(
                pd.Timestamp(
                    "2026-08-09T01:00:00Z"
                )
            ),
            "value",
        ]
        .iloc[0]
    )

    assert updated_value == 99.0


def test_latest_event_time_uses_metadata(
    tmp_path: Path,
) -> None:
    repository, contract = (
        build_repository(
            tmp_path
        )
    )

    dataframe = pd.DataFrame(
        {
            "location_key": [
                "karachi",
            ],
            "datetime_utc": (
                pd.to_datetime(
                    [
                        "2026-08-09T03:00:00Z",
                    ],
                    utc=True,
                )
            ),
            "value": [
                15.0,
            ],
        }
    )

    repository.upsert(
        contract=contract,
        dataframe=dataframe,
    )

    latest = (
        repository.latest_event_time(
            contract=contract
        )
    )

    assert latest == pd.Timestamp(
        "2026-08-09T03:00:00Z"
    )


def test_read_range_filters_event_time(
    tmp_path: Path,
) -> None:
    repository, contract = (
        build_repository(
            tmp_path
        )
    )

    dataframe = pd.DataFrame(
        {
            "location_key": [
                "karachi",
                "karachi",
                "karachi",
            ],
            "datetime_utc": (
                pd.to_datetime(
                    [
                        "2026-08-09T00:00:00Z",
                        "2026-08-09T01:00:00Z",
                        "2026-08-09T02:00:00Z",
                    ],
                    utc=True,
                )
            ),
            "value": [
                10.0,
                11.0,
                12.0,
            ],
        }
    )

    repository.upsert(
        contract=contract,
        dataframe=dataframe,
    )

    result = repository.read_range(
        contract=contract,
        start_time_utc=pd.Timestamp(
            "2026-08-09T01:00:00Z"
        ),
        end_time_exclusive_utc=(
            pd.Timestamp(
                "2026-08-09T03:00:00Z"
            )
        ),
    )

    assert len(result) == 2


from app.pipelines.incremental_features import (
    synchronize_group,
)

def test_incremental_sync_with_blob_repository(
    tmp_path: Path,
) -> None:
    repository, contract = (
        build_repository(
            tmp_path
        )
    )

    settings = MLOpsSettings(
        feature_store_backend=(
            "azure_blob"
        ),
        azure_storage_account=(
            "testaccount"
        ),
        mlops_dry_run=False,
        incremental_overlap_hours=24,
        incremental_initial_lookback_hours=24,
    )

    dataframe = pd.DataFrame(
        {
            "location_key": [
                "karachi",
                "karachi",
            ],
            "datetime_utc": (
                pd.to_datetime(
                    [
                        "2026-08-09T00:00:00Z",
                        "2026-08-09T01:00:00Z",
                    ],
                    utc=True,
                )
            ),
            "value": [
                10.0,
                11.0,
            ],
        }
    )

    first = synchronize_group(
        dataframe=dataframe,
        repository=repository,
        contract=contract,
        settings=settings,
    )

    assert (
        first["rows_to_insert"]
        == 2
    )

    assert first["rows_written"] == 2

    second = synchronize_group(
        dataframe=dataframe,
        repository=repository,
        contract=contract,
        settings=settings,
    )

    assert (
        second["rows_to_insert"]
        == 0
    )

    assert (
        second["rows_to_update"]
        == 0
    )

    assert (
        second["rows_unchanged"]
        == 2
    )

    assert second["rows_written"] == 0
