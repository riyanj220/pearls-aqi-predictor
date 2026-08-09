"""Hopsworks implementation of the feature repository contract."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.mlops.client import (
    HopsworksConnectionError,
    connect_to_hopsworks,
)
from app.mlops.config import MLOpsSettings
from app.mlops.contracts import (
    FeatureGroupContract,
)
from app.mlops.feature_groups import (
    create_or_get_feature_groups,
)
from app.mlops.feature_repository import (
    FeatureRepository,
    FeatureRepositoryError,
    empty_feature_frame,
)


class HopsworksFeatureRepository(
    FeatureRepository
):
    """Feature repository backed by Hopsworks Feature Store."""

    def __init__(
        self,
        *,
        settings: MLOpsSettings,
        contracts: dict[str, FeatureGroupContract],
        create_if_missing: bool = False,
    ) -> None:
        self.settings = settings
        self.contracts = contracts

        try:
            resources = connect_to_hopsworks(
                settings
            )
        except HopsworksConnectionError as error:
            raise FeatureRepositoryError(
                "Could not initialize the Hopsworks "
                "feature repository."
            ) from error

        if resources.feature_store is None:
            raise FeatureRepositoryError(
                "Hopsworks Feature Store was not resolved."
            )

        self.resources = resources

        if create_if_missing:
            resolved = create_or_get_feature_groups(
                resources=resources,
                settings=settings,
                contracts=contracts,
            )

            self._handles: dict[str, Any | None] = {
                contracts["pm25"].name: (
                    resolved.pm25
                ),
                contracts["weather"].name: (
                    resolved.weather
                ),
                contracts["engineered"].name: (
                    resolved.engineered
                ),
            }

        else:
            feature_store = (
                resources.feature_store
            )

            try:
                self._handles = {
                    contract.name: (
                        feature_store
                        .get_feature_group(
                            name=contract.name,
                            version=contract.version,
                        )
                    )
                    for contract
                    in contracts.values()
                }

            except Exception as error:
                raise FeatureRepositoryError(
                    "Could not resolve configured "
                    "Hopsworks feature groups."
                ) from error

    @property
    def backend_name(self) -> str:
        """Return backend identifier."""

        return "hopsworks"

    @property
    def source_label(self) -> str:
        """Return human-readable source."""

        return "Hopsworks Feature Store"

    def _get_handle(
        self,
        contract: FeatureGroupContract,
    ) -> Any:
        """Resolve one feature-group handle."""

        handle = self._handles.get(
            contract.name
        )

        if handle is None:
            raise FeatureRepositoryError(
                "Feature dataset was not resolved: "
                f"{contract.name}"
            )

        return handle

    @staticmethod
    def _normalize_readback(
        *,
        dataframe: pd.DataFrame | None,
        contract: FeatureGroupContract,
    ) -> pd.DataFrame:
        """Normalize one Hopsworks read result."""

        if (
            dataframe is None
            or dataframe.empty
        ):
            return empty_feature_frame(
                contract
            )

        result = dataframe.copy()

        result.columns = [
            str(column).lower()
            for column in result.columns
        ]

        return result

    def read_dataset(
        self,
        *,
        contract: FeatureGroupContract,
    ) -> pd.DataFrame:
        """Read the complete Hopsworks feature group."""

        handle = self._get_handle(
            contract
        )

        try:
            dataframe = handle.read(
                dataframe_type="pandas"
            )
        except Exception as error:
            raise FeatureRepositoryError(
                "Could not read feature dataset "
                f"{contract.name}."
            ) from error

        return self._normalize_readback(
            dataframe=dataframe,
            contract=contract,
        )

    def read_range(
        self,
        *,
        contract: FeatureGroupContract,
        start_time_utc: pd.Timestamp,
        end_time_exclusive_utc: pd.Timestamp,
    ) -> pd.DataFrame:
        """Read one Hopsworks event-time interval."""

        handle = self._get_handle(
            contract
        )

        try:
            dataframe = handle.read(
                dataframe_type="pandas",
                start_time=(
                    start_time_utc
                    .to_pydatetime()
                ),
                end_time=(
                    end_time_exclusive_utc
                    .to_pydatetime()
                ),
            )

        except Exception as error:
            raise FeatureRepositoryError(
                "Could not read feature range "
                f"for {contract.name}."
            ) from error

        return self._normalize_readback(
            dataframe=dataframe,
            contract=contract,
        )

    def latest_event_time(
        self,
        *,
        contract: FeatureGroupContract,
    ) -> pd.Timestamp | None:
        """Return the latest stored event time."""

        dataframe = self.read_dataset(
            contract=contract
        )

        if dataframe.empty:
            return None

        if (
            contract.event_time
            not in dataframe.columns
        ):
            raise FeatureRepositoryError(
                f"{contract.name} does not contain "
                f"{contract.event_time}."
            )

        event_times = pd.to_datetime(
            dataframe[
                contract.event_time
            ],
            utc=True,
            errors="coerce",
        ).dropna()

        if event_times.empty:
            return None

        return (
            event_times
            .max()
            .floor("h")
        )

    def upsert(
        self,
        *,
        contract: FeatureGroupContract,
        dataframe: pd.DataFrame,
    ) -> None:
        """Upsert prepared rows into Hopsworks."""

        if dataframe.empty:
            return

        contract.validate_dataframe(
            dataframe
        )

        handle = self._get_handle(
            contract
        )

        try:
            handle.insert(
                dataframe,
                operation="upsert",
                wait=True,
            )

        except Exception as error:
            raise FeatureRepositoryError(
                "Could not upsert feature dataset "
                f"{contract.name}."
            ) from error
