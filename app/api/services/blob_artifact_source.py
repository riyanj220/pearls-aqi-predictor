"""Materialize the latest validated AQI package from durable storage."""

from __future__ import annotations

import hashlib
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.api.config import APISettings
from app.artifacts.repository import (
    ArtifactRepository as DurableArtifactRepository,
)
from app.artifacts.repository import (
    ArtifactRepositoryError as DurableRepositoryError,
)
from app.artifacts.repository import (
    create_artifact_repository,
)


class ArtifactMaterializationError(
    RuntimeError
):
    """Raised when durable artifacts cannot be materialized."""


@dataclass(frozen=True)
class MaterializationResult:
    """Result of one durable artifact refresh."""

    backend: str
    run_id: str | None
    source_run_id: str | None
    refreshed: bool
    cache_directory: Path


def calculate_bytes_sha256(
    data: bytes,
) -> str:
    """Calculate one SHA-256 checksum."""

    return hashlib.sha256(
        data
    ).hexdigest()


class BlobArtifactSource:
    """
    Download and verify the latest durable AQI package.

    The API continues reading normal local files. This class safely
    refreshes those files from Azure Blob Storage when the latest
    durable pointer changes.
    """

    ACCEPTABLE_VALIDATION_STATUSES = {
        "AQI_ALERT_PIPELINE_APPROVED",
        "AQI_ALERT_PIPELINE_APPROVED_WITH_LIMITATIONS",
    }

    def __init__(
        self,
        settings: APISettings,
        *,
        repository: (
            DurableArtifactRepository
            | None
        ) = None,
    ) -> None:
        self._settings = settings

        self._repository = (
            repository
            if repository is not None
            else self._create_repository()
        )

        self._lock = threading.RLock()

        self._last_checked_monotonic: (
            float | None
        ) = None

        self._materialized_run_id: (
            str | None
        ) = None

    def _create_repository(
        self,
    ) -> DurableArtifactRepository:
        """Create the configured durable repository."""

        try:
            return create_artifact_repository(
                backend="azure_blob",
                azure_storage_account=(
                    self._settings
                    .azure_storage_account
                ),
                azure_storage_container=(
                    self._settings
                    .azure_storage_container
                ),
            )
        except DurableRepositoryError as error:
            raise ArtifactMaterializationError(
                "Could not create Azure Blob "
                "artifact repository."
            ) from error

    def refresh(
        self,
        *,
        force: bool = False,
    ) -> MaterializationResult:
        """Refresh the local API cache when the latest run changes."""

        with self._lock:
            if (
                not force
                and not self._refresh_is_due()
                and self._local_cache_is_complete()
            ):
                return MaterializationResult(
                    backend="azure_blob",
                    run_id=(
                        self._materialized_run_id
                    ),
                    source_run_id=None,
                    refreshed=False,
                    cache_directory=(
                        self._settings
                        .active_phase_6_directory
                    ),
                )

            pointer = self._load_pointer()

            run_id = self._require_string(
                pointer,
                "run_id",
            )

            source_run_id = (
                self._optional_string(
                    pointer,
                    "source_run_id",
                )
            )

            validation_status = (
                self._require_string(
                    pointer,
                    "validation_status",
                )
            )

            if (
                validation_status
                not in self
                .ACCEPTABLE_VALIDATION_STATUSES
            ):
                raise ArtifactMaterializationError(
                    "Latest pointer does not identify "
                    "a serving-approved run: "
                    f"{validation_status}"
                )

            if (
                not force
                and run_id
                == self._materialized_run_id
                and self._local_cache_is_complete()
            ):
                self._mark_checked()

                return MaterializationResult(
                    backend="azure_blob",
                    run_id=run_id,
                    source_run_id=(
                        source_run_id
                    ),
                    refreshed=False,
                    cache_directory=(
                        self._settings
                        .active_phase_6_directory
                    ),
                )

            manifest = self._load_manifest(
                pointer
            )

            self._validate_pointer_manifest(
                pointer=pointer,
                manifest=manifest,
            )

            temporary_directory = (
                self._prepare_temporary_directory(
                    run_id
                )
            )

            try:
                self._download_manifest_files(
                    manifest=manifest,
                    temporary_directory=(
                        temporary_directory
                    ),
                )

                self._validate_required_files(
                    temporary_directory
                )

                self._publish_local_cache(
                    temporary_directory
                )

            except Exception:
                shutil.rmtree(
                    temporary_directory,
                    ignore_errors=True,
                )
                raise

            self._materialized_run_id = (
                run_id
            )

            self._mark_checked()

            return MaterializationResult(
                backend="azure_blob",
                run_id=run_id,
                source_run_id=source_run_id,
                refreshed=True,
                cache_directory=(
                    self._settings
                    .active_phase_6_directory
                ),
            )

    def _refresh_is_due(
        self,
    ) -> bool:
        """Return whether the durable pointer should be checked."""

        if (
            self._last_checked_monotonic
            is None
        ):
            return True

        elapsed_seconds = (
            time.monotonic()
            - self._last_checked_monotonic
        )

        return (
            elapsed_seconds
            >= self._settings
            .artifact_cache_seconds
        )

    def _mark_checked(
        self,
    ) -> None:
        """Record one successful pointer check."""

        self._last_checked_monotonic = (
            time.monotonic()
        )

    def _load_pointer(
        self,
    ) -> dict[str, Any]:
        """Read the latest durable AQI pointer."""

        try:
            return (
                self._repository
                .get_latest_pointer(
                    self._settings
                    .artifact_type
                )
            )
        except DurableRepositoryError as error:
            raise ArtifactMaterializationError(
                "Could not read the latest AQI "
                "artifact pointer."
            ) from error

    def _load_manifest(
        self,
        pointer: dict[str, Any],
    ) -> dict[str, Any]:
        """Read the manifest named by the latest pointer."""

        manifest_path = self._require_string(
            pointer,
            "manifest_path",
        )

        try:
            return (
                self._repository
                .download_json(
                    manifest_path
                )
            )
        except DurableRepositoryError as error:
            raise ArtifactMaterializationError(
                "Could not read the latest AQI "
                "artifact manifest."
            ) from error

    def _validate_pointer_manifest(
        self,
        *,
        pointer: dict[str, Any],
        manifest: dict[str, Any],
    ) -> None:
        """Confirm pointer and manifest identify one approved run."""

        pointer_run_id = (
            self._require_string(
                pointer,
                "run_id",
            )
        )

        manifest_run_id = (
            self._require_string(
                manifest,
                "run_id",
            )
        )

        if (
            pointer_run_id
            != manifest_run_id
        ):
            raise ArtifactMaterializationError(
                "Latest pointer and manifest "
                "contain different run IDs."
            )

        pointer_source_run_id = (
            self._optional_string(
                pointer,
                "source_run_id",
            )
        )

        manifest_source_run_id = (
            self._optional_string(
                manifest,
                "source_run_id",
            )
        )

        if (
            pointer_source_run_id
            != manifest_source_run_id
        ):
            raise ArtifactMaterializationError(
                "Latest pointer and manifest "
                "contain different source run IDs."
            )

        pointer_status = (
            self._require_string(
                pointer,
                "validation_status",
            )
        )

        manifest_status = (
            self._require_string(
                manifest,
                "validation_status",
            )
        )

        if pointer_status != manifest_status:
            raise ArtifactMaterializationError(
                "Latest pointer and manifest "
                "contain different validation statuses."
            )

        if (
            manifest_status
            not in self
            .ACCEPTABLE_VALIDATION_STATUSES
        ):
            raise ArtifactMaterializationError(
                "Manifest is not approved for serving."
            )

    def _prepare_temporary_directory(
        self,
        run_id: str,
    ) -> Path:
        """Create an empty temporary cache directory."""

        cache_directory = (
            self._settings
            .active_phase_6_directory
        )

        temporary_directory = (
            cache_directory.parent
            / f".{cache_directory.name}-{run_id}.tmp"
        )

        shutil.rmtree(
            temporary_directory,
            ignore_errors=True,
        )

        temporary_directory.mkdir(
            parents=True,
            exist_ok=False,
        )

        return temporary_directory

    def _download_manifest_files(
        self,
        *,
        manifest: dict[str, Any],
        temporary_directory: Path,
    ) -> None:
        """Download and checksum every manifest file."""

        artifact_prefix = (
            self._require_string(
                manifest,
                "artifact_prefix",
            )
        )

        files = manifest.get("files")

        if (
            not isinstance(files, list)
            or not files
        ):
            raise ArtifactMaterializationError(
                "Artifact manifest contains no files."
            )

        for record in files:
            if not isinstance(record, dict):
                raise ArtifactMaterializationError(
                    "Artifact manifest contains "
                    "an invalid file record."
                )

            relative_path = (
                self._require_string(
                    record,
                    "relative_path",
                )
            )

            if (
                "/" in relative_path
                or "\\" in relative_path
                or relative_path in {
                    ".",
                    "..",
                }
            ):
                raise ArtifactMaterializationError(
                    "Artifact filename is unsafe: "
                    f"{relative_path}"
                )

            expected_size = record.get(
                "size_bytes"
            )

            expected_checksum = (
                self._require_string(
                    record,
                    "sha256",
                )
            )

            if (
                not isinstance(
                    expected_size,
                    int,
                )
                or expected_size <= 0
            ):
                raise ArtifactMaterializationError(
                    "Artifact manifest contains "
                    "an invalid file size."
                )

            blob_path = (
                f"{artifact_prefix}/"
                f"{relative_path}"
            )

            try:
                data = (
                    self._repository
                    .download_bytes(
                        blob_path
                    )
                )
            except DurableRepositoryError as error:
                raise ArtifactMaterializationError(
                    "Could not download durable "
                    f"artifact: {relative_path}"
                ) from error

            if len(data) != expected_size:
                raise ArtifactMaterializationError(
                    "Downloaded artifact size mismatch: "
                    f"{relative_path}"
                )

            actual_checksum = (
                calculate_bytes_sha256(
                    data
                )
            )

            if (
                actual_checksum
                != expected_checksum
            ):
                raise ArtifactMaterializationError(
                    "Downloaded artifact checksum mismatch: "
                    f"{relative_path}"
                )

            destination = (
                temporary_directory
                / relative_path
            )

            destination.write_bytes(data)

    def _validate_required_files(
        self,
        directory: Path,
    ) -> None:
        """Require the exact files needed by the FastAPI repository."""

        required_names = {
            self._settings
            .phase_6_forecast_filename,
            self._settings
            .phase_6_alert_episodes_filename,
            self._settings
            .phase_6_summary_filename,
            self._settings
            .phase_6_metadata_filename,
            self._settings
            .phase_6_validation_filename,
        }

        actual_names = {
            path.name
            for path in directory.iterdir()
            if path.is_file()
        }

        missing_names = (
            required_names
            - actual_names
        )

        if missing_names:
            raise ArtifactMaterializationError(
                "Downloaded AQI package is missing: "
                f"{sorted(missing_names)}"
            )

        for filename in required_names:
            path = directory / filename

            if path.stat().st_size <= 0:
                raise ArtifactMaterializationError(
                    "Downloaded AQI artifact is empty: "
                    f"{filename}"
                )

    def _publish_local_cache(
        self,
        temporary_directory: Path,
    ) -> None:
        """Atomically replace the API's active local cache."""

        cache_directory = (
            self._settings
            .active_phase_6_directory
        )

        cache_directory.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        backup_directory = (
            cache_directory.parent
            / f".{cache_directory.name}.previous"
        )

        shutil.rmtree(
            backup_directory,
            ignore_errors=True,
        )

        try:
            if cache_directory.exists():
                cache_directory.replace(
                    backup_directory
                )

            temporary_directory.replace(
                cache_directory
            )

        except Exception as error:
            if (
                not cache_directory.exists()
                and backup_directory.exists()
            ):
                backup_directory.replace(
                    cache_directory
                )

            raise ArtifactMaterializationError(
                "Could not publish the refreshed "
                "API artifact cache."
            ) from error

        shutil.rmtree(
            backup_directory,
            ignore_errors=True,
        )

    def _local_cache_is_complete(
        self,
    ) -> bool:
        """Return whether all API-required cache files exist."""

        return all(
            path.exists()
            and path.is_file()
            and path.stat().st_size > 0
            for path in (
                self._settings.forecast_path,
                self._settings.alert_episodes_path,
                self._settings.summary_path,
                self._settings.metadata_path,
                self._settings.validation_report_path,
            )
        )

    @staticmethod
    def _require_string(
        payload: dict[str, Any],
        key: str,
    ) -> str:
        """Read one required non-empty string."""

        value = payload.get(key)

        if (
            not isinstance(value, str)
            or not value.strip()
        ):
            raise ArtifactMaterializationError(
                f"Artifact document has no valid {key}."
            )

        return value.strip()

    @staticmethod
    def _optional_string(
        payload: dict[str, Any],
        key: str,
    ) -> str | None:
        """Read one optional string."""

        value = payload.get(key)

        if value is None:
            return None

        if not isinstance(value, str):
            raise ArtifactMaterializationError(
                f"Artifact document has an invalid {key}."
            )

        cleaned_value = value.strip()

        return cleaned_value or None