from __future__ import annotations

import pandas as pd

from app.mlops.config import MLOpsSettings
from app.mlops.contracts import (
    FeatureGroupContract,
    FeatureDefinition,
)
from app.mlops.feature_repository import (
    FeatureRepository,
    empty_feature_frame,
)
from app.pipelines.incremental_features import (
    synchronize_group,
)


class InMemoryFeatureRepository(
    FeatureRepository
):
    def __init__(self) -> None:
        self.data: dict[
            str,
            pd.DataFrame,
        ] = {}

    @property
    def backend_name(self) -> str:
        return "memory"

    @property
    def source_label(self) -> str:
        return "In-memory test repository"

    def read_dataset(
        self,
        *,
        contract: FeatureGroupContract,
    ) -> pd.DataFrame:
        return self.data.get(
            contract.name,
            empty_feature_frame(
                contract
            ),
        ).copy()

    def read_range(
        self,
        *,
        contract: FeatureGroupContract,
        start_time_utc: pd.Timestamp,
        end_time_exclusive_utc: pd.Timestamp,
    ) -> pd.DataFrame:
        dataframe = self.read_dataset(
            contract=contract
        )

        if dataframe.empty:
            return dataframe

        event_times = pd.to_datetime(
            dataframe[
                contract.event_time
            ],
            utc=True,
        )

        return dataframe.loc[
            event_times.ge(
                start_time_utc
            )
            & event_times.lt(
                end_time_exclusive_utc
            )
        ].copy()

    def latest_event_time(
        self,
        *,
        contract: FeatureGroupContract,
    ) -> pd.Timestamp | None:
        dataframe = self.read_dataset(
            contract=contract
        )

        if dataframe.empty:
            return None

        return (
            pd.to_datetime(
                dataframe[
                    contract.event_time
                ],
                utc=True,
            )
            .max()
            .floor("h")
        )

    def upsert(
        self,
        *,
        contract: FeatureGroupContract,
        dataframe: pd.DataFrame,
    ) -> None:
        current = self.read_dataset(
            contract=contract
        )

        if current.empty:
            combined = dataframe.copy()
        else:
            combined = pd.concat(
                [
                    current,
                    dataframe,
                ],
                ignore_index=True,
            )

        logical_key = list(
            dict.fromkeys(
                [
                    *contract.primary_key,
                    contract.event_time,
                ]
            )
        )

        self.data[
            contract.name
        ] = (
            combined
            .sort_values(
                contract.event_time
            )
            .drop_duplicates(
                subset=logical_key,
                keep="last",
            )
            .reset_index(
                drop=True
            )
        )

def build_test_contract() -> FeatureGroupContract:
    return FeatureGroupContract(
        name="test_features",
        version=1,
        description="Test feature dataset.",
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
                description="Test value.",
            ),
        ),
    )


def test_synchronize_group_uses_repository_contract() -> None:
    contract = build_test_contract()

    repository = (
        InMemoryFeatureRepository()
    )

    settings = MLOpsSettings(
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

    first_report = synchronize_group(
        dataframe=dataframe,
        repository=repository,
        contract=contract,
        settings=settings,
    )

    assert (
        first_report[
            "rows_to_insert"
        ]
        == 2
    )

    assert (
        first_report[
            "rows_written"
        ]
        == 2
    )

    second_report = synchronize_group(
        dataframe=dataframe,
        repository=repository,
        contract=contract,
        settings=settings,
    )

    assert (
        second_report[
            "rows_to_insert"
        ]
        == 0
    )

    assert (
        second_report[
            "rows_to_update"
        ]
        == 0
    )

    assert (
        second_report[
            "rows_unchanged"
        ]
        == 2
    )

    assert (
        second_report[
            "rows_written"
        ]
        == 0
    )
