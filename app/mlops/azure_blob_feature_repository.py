"""Azure Blob-backed feature repository."""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import pandas as pd

from app.artifacts.repository import (
    ArtifactRepository,
    ArtifactRepositoryError,
    create_artifact_repository,
)
from app.mlops.config import MLOpsSettings
from app.mlops.contracts import (
    FeatureGroupContract,
)
from app.mlops.feature_repository import (
    FeatureRepository,
    FeatureRepositoryError,
    empty_feature_frame,
)


class AzureBlobFeatureRepository(
    FeatureRepository
):
    """Parquet-based feature repository stored in Azure Blob."""

    def __init__(
        self,
        *,
        settings: MLOpsSettings,
        contracts: dict[str, FeatureGroupContract],
        repository: ArtifactRepository | None = None,
    ) -> None:
        self.settings = settings
        self.contracts = contracts

        if not settings.azure_storage_account:
            raise FeatureRepositoryError(
                "AZURE_STORAGE_ACCOUNT is required "
                "for the Azure Blob feature repository."
            )

        self.prefix = (
            settings
            .azure_feature_store_prefix
            .strip("/")
        )

        if not self.prefix:
            raise FeatureRepositoryError(
                "AZURE_FEATURE_STORE_PREFIX "
                "cannot be empty."
            )

        try:
            self.repository = (
                repository
                if repository is not None
                else create_artifact_repository(
                    backend="azure_blob",
                    azure_storage_account=(
                        settings
                        .azure_storage_account
                    ),
                    azure_storage_container=(
                        settings
                        .azure_storage_container
                    ),
                )
            )

        except ArtifactRepositoryError as error:
            raise FeatureRepositoryError(
                "Could not initialize Azure Blob "
                "feature repository."
            ) from error

    @property
    def backend_name(self) -> str:
        return "azure_blob"

    @property
    def source_label(self) -> str:
        return "Azure Blob Feature Repository"

    def _dataset_prefix(
        self,
        contract: FeatureGroupContract,
    ) -> str:
        return (
            f"{self.prefix}/"
            f"{contract.name}"
        )

    def _data_path(
        self,
        contract: FeatureGroupContract,
    ) -> str:
        return (
            f"{self._dataset_prefix(contract)}"
            "/data.parquet"
        )

    def _metadata_path(
        self,
        contract: FeatureGroupContract,
    ) -> str:
        return (
            f"{self._dataset_prefix(contract)}"
            "/metadata.json"
        )

    def _serialize_parquet(
        self,
        dataframe: pd.DataFrame,
    ) -> bytes:
        buffer = io.BytesIO()

        dataframe.to_parquet(
            buffer,
            index=False,
        )

        return buffer.getvalue()

    def _deserialize_parquet(
        self,
        data: bytes,
    ) -> pd.DataFrame:
        try:
            return pd.read_parquet(
                io.BytesIO(data)
            )
        except Exception as error:
            raise FeatureRepositoryError(
                "Could not decode feature Parquet data."
            ) from error

    def _normalize_dataset(
        self,
        *,
        dataframe: pd.DataFrame,
        contract: FeatureGroupContract,
    ) -> pd.DataFrame:
        if dataframe.empty:
            return empty_feature_frame(
                contract
            )

        missing_columns = sorted(
            set(
                contract.feature_names
            ).difference(
                dataframe.columns
            )
        )

        if missing_columns:
            raise FeatureRepositoryError(
                f"{contract.name} is missing "
                f"required columns: "
                f"{missing_columns}"
            )

        result = dataframe[
            contract.feature_names
        ].copy()

        result[
            contract.event_time
        ] = pd.to_datetime(
            result[
                contract.event_time
            ],
            utc=True,
            errors="raise",
        ).dt.floor("h")

        logical_key = list(
            dict.fromkeys(
                [
                    *contract.primary_key,
                    contract.event_time,
                ]
            )
        )

        result = (
            result
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

        contract.validate_dataframe(
            result
        )

        return result

    def read_dataset(
        self,
        *,
        contract: FeatureGroupContract,
    ) -> pd.DataFrame:
        path = self._data_path(
            contract
        )

        try:
            if not self.repository.exists(
                path
            ):
                return empty_feature_frame(
                    contract
                )

            data = self.repository.download_bytes(
                path
            )

        except ArtifactRepositoryError as error:
            raise FeatureRepositoryError(
                "Could not read Azure Blob feature "
                f"dataset {contract.name}."
            ) from error

        dataframe = (
            self._deserialize_parquet(
                data
            )
        )

        return self._normalize_dataset(
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
            errors="raise",
        )

        return (
            dataframe.loc[
                event_times.ge(
                    start_time_utc
                )
                & event_times.lt(
                    end_time_exclusive_utc
                )
            ]
            .copy()
            .reset_index(
                drop=True
            )
        )

    def latest_event_time(
        self,
        *,
        contract: FeatureGroupContract,
    ) -> pd.Timestamp | None:
        metadata_path = (
            self._metadata_path(
                contract
            )
        )

        try:
            if self.repository.exists(
                metadata_path
            ):
                metadata = (
                    self.repository
                    .download_json(
                        metadata_path
                    )
                )

                latest_value = (
                    metadata.get(
                        "latest_event_time_utc"
                    )
                )

                if latest_value:
                    timestamp = pd.Timestamp(
                        latest_value
                    )

                    if timestamp.tzinfo is None:
                        timestamp = (
                            timestamp
                            .tz_localize(
                                "UTC"
                            )
                        )
                    else:
                        timestamp = (
                            timestamp
                            .tz_convert(
                                "UTC"
                            )
                        )

                    return (
                        timestamp.floor(
                            "h"
                        )
                    )

        except (
            ArtifactRepositoryError,
            ValueError,
            TypeError,
        ):
            pass

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
                errors="raise",
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
        if dataframe.empty:
            return

        contract.validate_dataframe(
            dataframe
        )

        existing = self.read_dataset(
            contract=contract
        )

        combined = pd.concat(
            [
                existing,
                dataframe,
            ],
            ignore_index=True,
        )

        combined = (
            self._normalize_dataset(
                dataframe=combined,
                contract=contract,
            )
        )

        latest_event_time = (
            pd.to_datetime(
                combined[
                    contract.event_time
                ],
                utc=True,
                errors="raise",
            )
            .max()
            .floor("h")
        )

        metadata = {
            "dataset_name": (
                contract.name
            ),
            "dataset_version": (
                contract.version
            ),
            "backend": "azure_blob",
            "row_count": int(
                len(combined)
            ),
            "event_time_column": (
                contract.event_time
            ),
            "primary_key": list(
                contract.primary_key
            ),
            "latest_event_time_utc": (
                latest_event_time
                .isoformat()
            ),
            "updated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "schema": (
                contract.safe_summary()
            ),
        }

        parquet_bytes = (
            self._serialize_parquet(
                combined
            )
        )

        try:
            self.repository.upload_bytes(
                data=parquet_bytes,
                destination_path=(
                    self._data_path(
                        contract
                    )
                ),
                content_type=(
                    "application/"
                    "vnd.apache.parquet"
                ),
                overwrite=True,
            )

            self.repository.upload_json(
                payload=metadata,
                destination_path=(
                    self._metadata_path(
                        contract
                    )
                ),
                overwrite=True,
            )

        except ArtifactRepositoryError as error:
            raise FeatureRepositoryError(
                "Could not write Azure Blob feature "
                f"dataset {contract.name}."
            ) from error
