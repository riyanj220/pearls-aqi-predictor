"""Azure Blob-backed model registry."""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib

from app.artifacts.repository import (
    ArtifactRepository,
    ArtifactRepositoryError,
    calculate_bytes_sha256,
    calculate_file_sha256,
    create_artifact_repository,
)
from app.mlops.config import MLOpsSettings
from app.mlops.model_registry import (
    RegisteredModelResult,
    ResolvedProductionModel,
    _replace_registry_cache,
)
from app.mlops.model_repository import (
    ModelRepository,
    ModelRepositoryError,
)


class AzureBlobModelRepository(
    ModelRepository
):
    """Versioned model registry backed by Azure Blob Storage."""

    def __init__(
        self,
        *,
        settings: MLOpsSettings,
        repository: ArtifactRepository | None = None,
    ) -> None:
        self.settings = settings

        if not settings.azure_storage_account:
            raise ModelRepositoryError(
                "AZURE_STORAGE_ACCOUNT is required "
                "for the Azure Blob model registry."
            )

        self.prefix = (
            settings
            .azure_model_registry_prefix
            .strip("/")
        )

        if not self.prefix:
            raise ModelRepositoryError(
                "AZURE_MODEL_REGISTRY_PREFIX cannot be empty."
            )

        self.model_name = (
            settings.hopsworks_model_name
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
            raise ModelRepositoryError(
                "Could not initialize Azure Blob "
                "model repository."
            ) from error

    @property
    def backend_name(self) -> str:
        """Return backend identifier."""

        return "azure_blob"

    @property
    def model_prefix(self) -> str:
        """Return the prefix for this model."""

        return (
            f"{self.prefix}/"
            f"{self.model_name}"
        )

    @property
    def index_path(self) -> str:
        """Return model index path."""

        return (
            f"{self.model_prefix}/"
            "index.json"
        )

    @property
    def production_pointer_path(
        self,
    ) -> str:
        """Return production model pointer path."""

        return (
            f"{self.model_prefix}/"
            "production/pointer.json"
        )

    def version_prefix(
        self,
        version: int,
    ) -> str:
        """Return one immutable model-version prefix."""

        if version < 1:
            raise ModelRepositoryError(
                "Model version must be >= 1."
            )

        return (
            f"{self.model_prefix}/"
            f"versions/{version}"
        )

    def manifest_path(
        self,
        version: int,
    ) -> str:
        """Return one version manifest path."""

        return (
            f"{self.version_prefix(version)}/"
            "manifest.json"
        )

    def _load_index(
        self,
    ) -> dict[str, Any]:
        """Load the model index or return an empty index."""

        try:
            if not self.repository.exists(
                self.index_path
            ):
                return {
                    "model_name": (
                        self.model_name
                    ),
                    "latest_version": 0,
                    "versions": [],
                }

            payload = (
                self.repository
                .download_json(
                    self.index_path
                )
            )

        except ArtifactRepositoryError as error:
            raise ModelRepositoryError(
                "Could not read Azure Blob "
                "model registry index."
            ) from error

        if (
            payload.get("model_name")
            != self.model_name
        ):
            raise ModelRepositoryError(
                "Model registry index belongs "
                "to a different model."
            )

        versions = payload.get(
            "versions"
        )

        if not isinstance(
            versions,
            list,
        ):
            raise ModelRepositoryError(
                "Model registry index has an "
                "invalid versions list."
            )

        return payload

    def _next_version(
        self,
    ) -> int:
        """Allocate the next sequential model version."""

        index = self._load_index()

        latest = index.get(
            "latest_version",
            0,
        )

        try:
            latest_version = int(
                latest
            )
        except (
            TypeError,
            ValueError,
        ) as error:
            raise ModelRepositoryError(
                "Model registry latest_version "
                "is invalid."
            ) from error

        return latest_version + 1

    def _discover_package_files(
        self,
        directory: Path,
    ) -> list[Path]:
        """Return top-level files included in a model version."""

        files = sorted(
            path
            for path in directory.iterdir()
            if path.is_file()
        )

        if not files:
            raise ModelRepositoryError(
                "Model package contains no files."
            )

        return files

    def _validate_candidate_package(
        self,
        directory: Path,
    ) -> Path:
        """Validate the minimum challenger package."""

        model_path = (
            directory
            / "best_model.joblib"
        )

        required = [
            model_path,
            directory
            / "model_feature_columns.json",
            directory
            / "candidate_metadata.json",
        ]

        missing = [
            str(path)
            for path in required
            if not path.exists()
        ]

        if missing:
            raise ModelRepositoryError(
                "Candidate package is incomplete: "
                f"{missing}"
            )

        try:
            joblib.load(
                model_path
            )
        except Exception as error:
            raise ModelRepositoryError(
                "Candidate model cannot be "
                "loaded with joblib."
            ) from error

        return model_path

    def _write_index_entry(
        self,
        *,
        version: int,
        status: str,
        checksum_sha256: str,
        registered_at_utc: str,
    ) -> None:
        """Update the registry index after immutable publication."""

        index = self._load_index()

        versions = list(
            index["versions"]
        )

        versions.append(
            {
                "version": version,
                "status": status,
                "checksum_sha256": (
                    checksum_sha256
                ),
                "artifact_prefix": (
                    self.version_prefix(
                        version
                    )
                ),
                "registered_at_utc": (
                    registered_at_utc
                ),
            }
        )

        payload = {
            "model_name": (
                self.model_name
            ),
            "latest_version": version,
            "updated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "versions": versions,
        }

        try:
            self.repository.upload_json(
                payload=payload,
                destination_path=(
                    self.index_path
                ),
                overwrite=True,
            )
        except ArtifactRepositoryError as error:
            raise ModelRepositoryError(
                "Could not update Azure Blob "
                "model registry index."
            ) from error

    def register_candidate_model(
        self,
        *,
        candidate_directory: Path,
        metrics: dict[str, float],
    ) -> RegisteredModelResult:
        """Register one immutable challenger version."""

        candidate_directory = (
            candidate_directory
            .resolve()
        )

        model_path = (
            self._validate_candidate_package(
                candidate_directory
            )
        )

        checksum = (
            calculate_file_sha256(
                model_path
            )
        )

        version = (
            self._next_version()
        )

        version_prefix = (
            self.version_prefix(
                version
            )
        )

        manifest_path = (
            self.manifest_path(
                version
            )
        )

        try:
            if self.repository.exists(
                manifest_path
            ):
                raise ModelRepositoryError(
                    "Allocated model version "
                    "already exists."
                )

        except ArtifactRepositoryError as error:
            raise ModelRepositoryError(
                "Could not inspect model version."
            ) from error

        registered_at = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        registry_metadata = {
            "model_name": (
                self.model_name
            ),
            "version": version,
            "registration_status": (
                "CANDIDATE"
            ),
            "artifact_checksum_sha256": (
                checksum
            ),
            "registered_at_utc": (
                registered_at
            ),
            "registered_from": (
                candidate_directory.name
            ),
            "metrics": {
                str(name): float(value)
                for name, value
                in metrics.items()
            },
        }

        records: list[
            dict[str, Any]
        ] = []

        package_files = (
            self._discover_package_files(
                candidate_directory
            )
        )

        try:
            for source_path in package_files:
                destination = (
                    f"{version_prefix}/"
                    f"{source_path.name}"
                )

                record = (
                    self.repository
                    .upload_file(
                        source_path=source_path,
                        destination_path=(
                            destination
                        ),
                        overwrite=False,
                    )
                )

                records.append(
                    {
                        "relative_path": (
                            source_path.name
                        ),
                        "size_bytes": (
                            record.size_bytes
                        ),
                        "sha256": (
                            record.sha256
                        ),
                    }
                )

            registry_bytes = json.dumps(
                registry_metadata,
                indent=2,
                sort_keys=True,
            ).encode(
                "utf-8"
            )

            registry_path = (
                f"{version_prefix}/"
                "registry_metadata.json"
            )

            self.repository.upload_bytes(
                data=registry_bytes,
                destination_path=(
                    registry_path
                ),
                content_type=(
                    "application/json"
                ),
                overwrite=False,
            )

            records.append(
                {
                    "relative_path": (
                        "registry_metadata.json"
                    ),
                    "size_bytes": (
                        len(
                            registry_bytes
                        )
                    ),
                    "sha256": (
                        calculate_bytes_sha256(
                            registry_bytes
                        )
                    ),
                }
            )

            manifest = {
                "model_name": (
                    self.model_name
                ),
                "version": version,
                "registration_status": (
                    "CANDIDATE"
                ),
                "artifact_prefix": (
                    version_prefix
                ),
                "registered_at_utc": (
                    registered_at
                ),
                "model_checksum_sha256": (
                    checksum
                ),
                "files": records,
            }

            # Manifest is deliberately the final
            # immutable write for this version.
            self.repository.upload_json(
                payload=manifest,
                destination_path=(
                    manifest_path
                ),
                overwrite=False,
            )

        except ArtifactRepositoryError as error:
            raise ModelRepositoryError(
                "Could not publish Azure Blob "
                "model version."
            ) from error

        self._write_index_entry(
            version=version,
            status="CANDIDATE",
            checksum_sha256=checksum,
            registered_at_utc=(
                registered_at
            ),
        )

        return RegisteredModelResult(
            name=self.model_name,
            version=version,
            status="CANDIDATE",
            checksum_sha256=checksum,
            model_directory=(
                version_prefix
            ),
        )

    def set_production_version(
        self,
        *,
        version: int,
    ) -> dict[str, Any]:
        """Atomically designate one registered version for production."""

        manifest_path = (
            self.manifest_path(
                version
            )
        )

        try:
            if not self.repository.exists(
                manifest_path
            ):
                raise ModelRepositoryError(
                    "Cannot promote missing model "
                    f"version {version}."
                )

            manifest = (
                self.repository
                .download_json(
                    manifest_path
                )
            )

        except ArtifactRepositoryError as error:
            raise ModelRepositoryError(
                "Could not inspect model version "
                "for production designation."
            ) from error

        checksum = str(
            manifest.get(
                "model_checksum_sha256",
                "",
            )
        )

        if not checksum:
            raise ModelRepositoryError(
                "Model manifest does not contain "
                "a checksum."
            )

        pointer = {
            "model_name": (
                self.model_name
            ),
            "version": version,
            "artifact_prefix": (
                self.version_prefix(
                    version
                )
            ),
            "manifest_path": (
                manifest_path
            ),
            "model_checksum_sha256": (
                checksum
            ),
            "production_status": (
                "PRODUCTION"
            ),
            "promoted_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
        }

        try:
            # This is the only mutable production
            # designation in the registry.
            self.repository.upload_json(
                payload=pointer,
                destination_path=(
                    self.production_pointer_path
                ),
                overwrite=True,
            )

        except ArtifactRepositoryError as error:
            raise ModelRepositoryError(
                "Could not update production "
                "model pointer."
            ) from error

        return pointer

    def _download_version(
        self,
        *,
        version: int,
        destination: Path,
    ) -> dict[str, Any]:
        """Download and validate one immutable model bundle."""

        manifest_path = (
            self.manifest_path(
                version
            )
        )

        try:
            manifest = (
                self.repository
                .download_json(
                    manifest_path
                )
            )
        except ArtifactRepositoryError as error:
            raise ModelRepositoryError(
                "Could not download model manifest."
            ) from error

        files = manifest.get(
            "files"
        )

        if (
            not isinstance(files, list)
            or not files
        ):
            raise ModelRepositoryError(
                "Model manifest contains no files."
            )

        destination.mkdir(
            parents=True,
            exist_ok=False,
        )

        version_prefix = (
            self.version_prefix(
                version
            )
        )

        for record in files:
            if not isinstance(
                record,
                dict,
            ):
                raise ModelRepositoryError(
                    "Invalid model manifest file record."
                )

            filename = str(
                record.get(
                    "relative_path",
                    "",
                )
            ).strip()

            expected_checksum = str(
                record.get(
                    "sha256",
                    "",
                )
            ).strip()

            if (
                not filename
                or "/" in filename
                or "\\" in filename
                or not expected_checksum
            ):
                raise ModelRepositoryError(
                    "Model manifest contains "
                    "an unsafe file record."
                )

            remote_path = (
                f"{version_prefix}/"
                f"{filename}"
            )

            try:
                data = (
                    self.repository
                    .download_bytes(
                        remote_path
                    )
                )
            except ArtifactRepositoryError as error:
                raise ModelRepositoryError(
                    "Could not download model "
                    f"file {filename}."
                ) from error

            actual_checksum = (
                calculate_bytes_sha256(
                    data
                )
            )

            if (
                actual_checksum
                != expected_checksum
            ):
                raise ModelRepositoryError(
                    "Downloaded model file "
                    f"checksum mismatch: {filename}"
                )

            (
                destination
                / filename
            ).write_bytes(
                data
            )

        return manifest

    def resolve_production_model(
        self,
        *,
        project_root: Path,
    ) -> ResolvedProductionModel:
        """Resolve the version selected by the production pointer."""

        try:
            pointer = (
                self.repository
                .download_json(
                    self.production_pointer_path
                )
            )
        except ArtifactRepositoryError as error:
            raise ModelRepositoryError(
                "Azure Blob model registry has "
                "no readable production pointer."
            ) from error

        if (
            pointer.get(
                "production_status"
            )
            != "PRODUCTION"
        ):
            raise ModelRepositoryError(
                "Azure Blob model pointer is not "
                "marked PRODUCTION."
            )

        try:
            version = int(
                pointer["version"]
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise ModelRepositoryError(
                "Production model pointer has "
                "an invalid version."
            ) from error

        temporary_root = Path(
            tempfile.mkdtemp(
                prefix=(
                    "pearls-model-"
                )
            )
        )

        temporary_bundle = (
            temporary_root
            / "bundle"
        )

        try:
            manifest = (
                self._download_version(
                    version=version,
                    destination=(
                        temporary_bundle
                    ),
                )
            )

            model_path = (
                temporary_bundle
                / "best_model.joblib"
            )

            feature_columns_path = (
                temporary_bundle
                / "model_feature_columns.json"
            )

            model_metadata_path = (
                temporary_bundle
                / "model_metadata.json"
            )

            required = [
                model_path,
                feature_columns_path,
            ]

            missing = [
                str(path)
                for path in required
                if not path.exists()
            ]

            if missing:
                raise ModelRepositoryError(
                    "Production model bundle is "
                    f"incomplete: {missing}"
                )

            expected_checksum = str(
                pointer.get(
                    "model_checksum_sha256",
                    "",
                )
            )

            actual_checksum = (
                calculate_file_sha256(
                    model_path
                )
            )

            if (
                not expected_checksum
                or actual_checksum
                != expected_checksum
            ):
                raise ModelRepositoryError(
                    "Production model checksum "
                    "does not match pointer."
                )

            try:
                joblib.load(
                    model_path
                )
            except Exception as error:
                raise ModelRepositoryError(
                    "Production model cannot be "
                    "loaded with joblib."
                ) from error

            # A production cache must retain the
            # existing fallback contract expected
            # by model_source.py.
            cache_registry_metadata = {
                "model_name": (
                    self.model_name
                ),
                "model_status": (
                    "PRODUCTION"
                ),
                "version": version,
                "artifact_checksum_sha256": (
                    actual_checksum
                ),
                "source_backend": (
                    "azure_blob"
                ),
                "source_manifest": (
                    manifest
                ),
            }

            registry_metadata_path = (
                temporary_bundle
                / "registry_metadata.json"
            )

            registry_metadata_path.write_text(
                json.dumps(
                    cache_registry_metadata,
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )

            cache_root = (
                project_root
                / self.settings
                .model_cache_directory
            ).resolve()

            resolved_cache = (
                _replace_registry_cache(
                    source_directory=(
                        temporary_bundle
                    ),
                    cache_directory=(
                        cache_root
                    ),
                )
            )

        finally:
            shutil.rmtree(
                temporary_root,
                ignore_errors=True,
            )

        resolved_model_metadata = (
            resolved_cache
            / "model_metadata.json"
        )

        # Candidate bundles currently contain
        # candidate_metadata.json rather than
        # model_metadata.json. Production seeding
        # in 10P-F will include model_metadata.json.
        if not resolved_model_metadata.exists():
            resolved_model_metadata = (
                resolved_cache
                / "candidate_metadata.json"
            )

        if not (
            resolved_model_metadata.exists()
        ):
            raise ModelRepositoryError(
                "Resolved production model has "
                "no metadata document."
            )

        return ResolvedProductionModel(
            name=self.model_name,
            version=version,
            status="PRODUCTION",
            downloaded_directory=(
                resolved_cache
            ),
            model_artifact_path=(
                resolved_cache
                / "best_model.joblib"
            ),
            feature_columns_path=(
                resolved_cache
                / "model_feature_columns.json"
            ),
            metadata_path=(
                resolved_cache
                / "registry_metadata.json"
            ),
            checksum_sha256=(
                actual_checksum
            ),
        )
