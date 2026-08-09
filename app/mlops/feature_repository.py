"""Backend-independent feature repository contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from app.mlops.config import (
    FeatureStoreBackend,
    MLOpsSettings,
)
from app.mlops.contracts import (
    FeatureGroupContract,
)


class FeatureRepositoryError(RuntimeError):
    """Raised when feature repository operations fail."""


class FeatureRepositoryConfigurationError(
    FeatureRepositoryError
):
    """Raised when the configured backend is unsupported."""


class FeatureRepository(ABC):
    """Backend-independent repository for ML feature datasets."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Return the configured backend identifier."""

    @property
    @abstractmethod
    def source_label(self) -> str:
        """Return a human-readable source description."""

    @abstractmethod
    def read_dataset(
        self,
        *,
        contract: FeatureGroupContract,
    ) -> pd.DataFrame:
        """Read the complete logical feature dataset."""

    @abstractmethod
    def read_range(
        self,
        *,
        contract: FeatureGroupContract,
        start_time_utc: pd.Timestamp,
        end_time_exclusive_utc: pd.Timestamp,
    ) -> pd.DataFrame:
        """Read feature rows within an event-time interval."""

    @abstractmethod
    def latest_event_time(
        self,
        *,
        contract: FeatureGroupContract,
    ) -> pd.Timestamp | None:
        """Return the latest valid stored event timestamp."""

    @abstractmethod
    def upsert(
        self,
        *,
        contract: FeatureGroupContract,
        dataframe: pd.DataFrame,
    ) -> None:
        """Insert or update prepared feature rows."""


def empty_feature_frame(
    contract: FeatureGroupContract,
) -> pd.DataFrame:
    """Return an empty frame matching a feature contract."""

    return pd.DataFrame(
        columns=contract.feature_names
    )


def create_feature_repository(
    *,
    settings: MLOpsSettings,
    contracts: dict[str, FeatureGroupContract],
    create_if_missing: bool = False,
) -> FeatureRepository:
    """Create the configured feature repository."""

    if (
        settings.feature_store_backend
        == FeatureStoreBackend.HOPSWORKS
    ):
        from app.mlops.hopsworks_feature_repository import (
            HopsworksFeatureRepository,
        )

        return HopsworksFeatureRepository(
            settings=settings,
            contracts=contracts,
            create_if_missing=create_if_missing,
        )

    if (
        settings.feature_store_backend
        == FeatureStoreBackend.AZURE_BLOB
    ):
        from app.mlops.azure_blob_feature_repository import (
            AzureBlobFeatureRepository,
        )

        return AzureBlobFeatureRepository(
            settings=settings,
            contracts=contracts,
        )

    raise FeatureRepositoryConfigurationError(
        "No runtime FeatureRepository implementation exists "
        f"for backend={settings.feature_store_backend.value!r}."
    )
