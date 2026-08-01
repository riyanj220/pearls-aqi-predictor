"""Durable local and Azure Blob artifact repositories.

Artifact publication follows this order:

1. write files under an immutable run prefix
2. validate and checksum every file
3. write the run manifest
4. update the latest pointer only after success

Updating the latest pointer last prevents readers from discovering a
partially published run.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Iterable, Mapping

from azure.core.exceptions import (
    AzureError,
    ResourceNotFoundError,
)
from azure.identity import DefaultAzureCredential
from azure.storage.blob import (
    BlobServiceClient,
    ContentSettings,
)


class ArtifactRepositoryError(RuntimeError):
    """Raised when artifact storage or publication fails."""


@dataclass(frozen=True)
class ArtifactRecord:
    """Metadata for one published artifact."""

    relative_path: str
    size_bytes: int
    sha256: str
    content_type: str


@dataclass(frozen=True)
class RunManifest:
    """Manifest describing one immutable artifact run."""

    artifact_type: str
    run_id: str
    published_at_utc: str
    artifact_prefix: str
    validation_status: str
    source_run_id: str | None
    files: list[ArtifactRecord]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe manifest."""

        payload = asdict(self)
        payload["files"] = [
            asdict(record)
            for record in self.files
        ]
        return payload


@dataclass(frozen=True)
class LatestPointer:
    """Pointer to the latest successfully published run."""

    artifact_type: str
    run_id: str
    artifact_prefix: str
    manifest_path: str
    published_at_utc: str
    validation_status: str
    source_run_id: str | None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe pointer."""

        return asdict(self)


@dataclass(frozen=True)
class PublicationResult:
    """Result returned by a successful publication."""

    manifest: RunManifest
    latest_pointer: LatestPointer


def normalize_relative_path(
    value: str | Path,
) -> str:
    """Normalize and validate one repository-relative path."""

    raw_value = str(value).replace("\\", "/")
    path = PurePosixPath(raw_value)

    if path.is_absolute():
        raise ArtifactRepositoryError(
            f"Absolute artifact path is not allowed: {value}"
        )

    if ".." in path.parts:
        raise ArtifactRepositoryError(
            f"Parent traversal is not allowed: {value}"
        )

    normalized = path.as_posix().strip("/")

    if not normalized or normalized == ".":
        raise ArtifactRepositoryError(
            "Artifact path cannot be empty."
        )

    return normalized


def calculate_file_sha256(
    path: Path,
    *,
    chunk_size: int = 1024 * 1024,
) -> str:
    """Calculate a file SHA-256 checksum."""

    digest = hashlib.sha256()

    with path.open("rb") as file:
        while chunk := file.read(chunk_size):
            digest.update(chunk)

    return digest.hexdigest()


def calculate_bytes_sha256(
    data: bytes,
) -> str:
    """Calculate a bytes SHA-256 checksum."""

    return hashlib.sha256(data).hexdigest()


def infer_content_type(
    path: Path | str,
) -> str:
    """Infer a safe content type."""

    content_type, _ = mimetypes.guess_type(
        str(path)
    )

    return content_type or "application/octet-stream"


def serialize_json(
    payload: Mapping[str, Any],
) -> bytes:
    """Serialize JSON deterministically."""

    return json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        default=str,
    ).encode("utf-8")


def discover_source_files(
    source_directory: Path,
) -> list[Path]:
    """Return all non-empty files in deterministic order."""

    if not source_directory.exists():
        raise ArtifactRepositoryError(
            "Source artifact directory does not exist: "
            f"{source_directory}"
        )

    if not source_directory.is_dir():
        raise ArtifactRepositoryError(
            "Source artifact path is not a directory: "
            f"{source_directory}"
        )

    files = sorted(
        path
        for path in source_directory.rglob("*")
        if path.is_file()
    )

    if not files:
        raise ArtifactRepositoryError(
            "Source artifact directory contains no files."
        )

    empty_files = [
        path
        for path in files
        if path.stat().st_size == 0
    ]

    if empty_files:
        raise ArtifactRepositoryError(
            "Source artifact directory contains empty files: "
            f"{empty_files}"
        )

    return files


class ArtifactRepository(ABC):
    """Abstract artifact repository."""

    @abstractmethod
    def upload_file(
        self,
        *,
        source_path: Path,
        destination_path: str,
        overwrite: bool,
    ) -> ArtifactRecord:
        """Upload one file."""

    @abstractmethod
    def upload_bytes(
        self,
        *,
        data: bytes,
        destination_path: str,
        content_type: str,
        overwrite: bool,
    ) -> ArtifactRecord:
        """Upload bytes."""

    @abstractmethod
    def download_bytes(
        self,
        path: str,
    ) -> bytes:
        """Download bytes."""

    @abstractmethod
    def exists(
        self,
        path: str,
    ) -> bool:
        """Return whether an artifact exists."""

    def upload_json(
        self,
        *,
        payload: Mapping[str, Any],
        destination_path: str,
        overwrite: bool,
    ) -> ArtifactRecord:
        """Upload one JSON document."""

        return self.upload_bytes(
            data=serialize_json(payload),
            destination_path=destination_path,
            content_type="application/json",
            overwrite=overwrite,
        )

    def download_json(
        self,
        path: str,
    ) -> dict[str, Any]:
        """Download and parse one JSON object."""

        try:
            payload = json.loads(
                self.download_bytes(path).decode(
                    "utf-8"
                )
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as error:
            raise ArtifactRepositoryError(
                f"Artifact does not contain valid JSON: {path}"
            ) from error

        if not isinstance(payload, dict):
            raise ArtifactRepositoryError(
                f"Expected JSON object at: {path}"
            )

        return payload

    def publish_run(
        self,
        *,
        artifact_type: str,
        run_id: str,
        source_directory: Path,
        validation_status: str,
        source_run_id: str | None = None,
    ) -> PublicationResult:
        """Publish an immutable run and update latest last."""

        normalized_artifact_type = (
            normalize_relative_path(
                artifact_type
            )
        )

        normalized_run_id = normalize_relative_path(
            run_id
        )

        if "/" in normalized_artifact_type:
            raise ArtifactRepositoryError(
                "artifact_type must contain one path segment."
            )

        if "/" in normalized_run_id:
            raise ArtifactRepositoryError(
                "run_id must contain one path segment."
            )

        if validation_status not in {
            "PASSED",
            "AQI_ALERT_PIPELINE_APPROVED",
        }:
            raise ArtifactRepositoryError(
                "Only successfully validated runs may "
                "update the latest pointer."
            )

        source_files = discover_source_files(
            source_directory
        )

        run_prefix = (
            f"{normalized_artifact_type}/runs/"
            f"{normalized_run_id}"
        )

        manifest_path = (
            f"{run_prefix}/manifest.json"
        )

        latest_pointer_path = (
            f"{normalized_artifact_type}/"
            "latest/pointer.json"
        )

        if self.exists(manifest_path):
            raise ArtifactRepositoryError(
                "An immutable run with this ID already exists: "
                f"{normalized_run_id}"
            )

        records: list[ArtifactRecord] = []

        for source_path in source_files:
            relative_path = source_path.relative_to(
                source_directory
            ).as_posix()

            destination_path = (
                f"{run_prefix}/{relative_path}"
            )

            record = self.upload_file(
                source_path=source_path,
                destination_path=destination_path,
                overwrite=False,
            )

            expected_checksum = (
                calculate_file_sha256(
                    source_path
                )
            )

            if record.sha256 != expected_checksum:
                raise ArtifactRepositoryError(
                    "Uploaded artifact checksum mismatch: "
                    f"{relative_path}"
                )

            records.append(
                ArtifactRecord(
                    relative_path=relative_path,
                    size_bytes=record.size_bytes,
                    sha256=record.sha256,
                    content_type=record.content_type,
                )
            )

        published_at_utc = datetime.now(
            timezone.utc
        ).isoformat()

        manifest = RunManifest(
            artifact_type=normalized_artifact_type,
            run_id=normalized_run_id,
            published_at_utc=published_at_utc,
            artifact_prefix=run_prefix,
            validation_status=validation_status,
            source_run_id=source_run_id,
            files=records,
        )

        self.upload_json(
            payload=manifest.to_dict(),
            destination_path=manifest_path,
            overwrite=False,
        )

        latest_pointer = LatestPointer(
            artifact_type=normalized_artifact_type,
            run_id=normalized_run_id,
            artifact_prefix=run_prefix,
            manifest_path=manifest_path,
            published_at_utc=published_at_utc,
            validation_status=validation_status,
            source_run_id=source_run_id,
        )

        # This is deliberately the final write.
        self.upload_json(
            payload=latest_pointer.to_dict(),
            destination_path=latest_pointer_path,
            overwrite=True,
        )

        return PublicationResult(
            manifest=manifest,
            latest_pointer=latest_pointer,
        )

    def get_latest_pointer(
        self,
        artifact_type: str,
    ) -> dict[str, Any]:
        """Read the latest successful run pointer."""

        normalized = normalize_relative_path(
            artifact_type
        )

        return self.download_json(
            f"{normalized}/latest/pointer.json"
        )

    def get_latest_manifest(
        self,
        artifact_type: str,
    ) -> dict[str, Any]:
        """Read the latest successful run manifest."""

        pointer = self.get_latest_pointer(
            artifact_type
        )

        manifest_path = pointer.get(
            "manifest_path"
        )

        if not isinstance(
            manifest_path,
            str,
        ) or not manifest_path:
            raise ArtifactRepositoryError(
                "Latest pointer does not contain "
                "a valid manifest path."
            )

        return self.download_json(
            manifest_path
        )


class LocalArtifactRepository(
    ArtifactRepository
):
    """Filesystem artifact repository for local development."""

    def __init__(
        self,
        root_directory: Path,
    ) -> None:
        self.root_directory = (
            root_directory.resolve()
        )

        self.root_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    def resolve_path(
        self,
        relative_path: str,
    ) -> Path:
        """Resolve one safe path below the root."""

        normalized = normalize_relative_path(
            relative_path
        )

        resolved = (
            self.root_directory
            / normalized
        ).resolve()

        if (
            self.root_directory
            not in resolved.parents
            and resolved
            != self.root_directory
        ):
            raise ArtifactRepositoryError(
                "Resolved path escaped artifact root."
            )

        return resolved

    def upload_file(
        self,
        *,
        source_path: Path,
        destination_path: str,
        overwrite: bool,
    ) -> ArtifactRecord:
        """Copy one file into local storage."""

        destination = self.resolve_path(
            destination_path
        )

        if destination.exists() and not overwrite:
            raise ArtifactRepositoryError(
                f"Artifact already exists: {destination_path}"
            )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        shutil.copy2(
            source_path,
            destination,
        )

        return ArtifactRecord(
            relative_path=normalize_relative_path(
                destination_path
            ),
            size_bytes=destination.stat().st_size,
            sha256=calculate_file_sha256(
                destination
            ),
            content_type=infer_content_type(
                destination
            ),
        )

    def upload_bytes(
        self,
        *,
        data: bytes,
        destination_path: str,
        content_type: str,
        overwrite: bool,
    ) -> ArtifactRecord:
        """Write bytes into local storage."""

        destination = self.resolve_path(
            destination_path
        )

        if destination.exists() and not overwrite:
            raise ArtifactRepositoryError(
                f"Artifact already exists: {destination_path}"
            )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        destination.write_bytes(data)

        return ArtifactRecord(
            relative_path=normalize_relative_path(
                destination_path
            ),
            size_bytes=len(data),
            sha256=calculate_bytes_sha256(data),
            content_type=content_type,
        )

    def download_bytes(
        self,
        path: str,
    ) -> bytes:
        """Read local artifact bytes."""

        artifact_path = self.resolve_path(path)

        if not artifact_path.exists():
            raise ArtifactRepositoryError(
                f"Artifact does not exist: {path}"
            )

        return artifact_path.read_bytes()

    def exists(
        self,
        path: str,
    ) -> bool:
        """Return whether a local artifact exists."""

        return self.resolve_path(path).exists()


class AzureBlobArtifactRepository(
    ArtifactRepository
):
    """Azure Blob repository using passwordless authentication."""

    def __init__(
        self,
        *,
        account_name: str,
        container_name: str,
        credential: Any | None = None,
    ) -> None:
        if not account_name.strip():
            raise ArtifactRepositoryError(
                "Azure Storage account name is required."
            )

        if not container_name.strip():
            raise ArtifactRepositoryError(
                "Azure Storage container name is required."
            )

        self.account_name = account_name.strip()
        self.container_name = container_name.strip()

        account_url = (
            f"https://{self.account_name}"
            ".blob.core.windows.net"
        )

        self.credential = (
            credential
            if credential is not None
            else DefaultAzureCredential()
        )

        self.service_client = BlobServiceClient(
            account_url=account_url,
            credential=self.credential,
        )

        self.container_client = (
            self.service_client
            .get_container_client(
                self.container_name
            )
        )

    def upload_file(
        self,
        *,
        source_path: Path,
        destination_path: str,
        overwrite: bool,
    ) -> ArtifactRecord:
        """Upload one file to Azure Blob Storage."""

        normalized = normalize_relative_path(
            destination_path
        )

        content_type = infer_content_type(
            source_path
        )

        try:
            with source_path.open("rb") as file:
                self.container_client.upload_blob(
                    name=normalized,
                    data=file,
                    overwrite=overwrite,
                    content_settings=ContentSettings(
                        content_type=content_type
                    ),
                )
        except AzureError as error:
            raise ArtifactRepositoryError(
                "Could not upload Azure Blob artifact: "
                f"{normalized}"
            ) from error

        return ArtifactRecord(
            relative_path=normalized,
            size_bytes=source_path.stat().st_size,
            sha256=calculate_file_sha256(
                source_path
            ),
            content_type=content_type,
        )

    def upload_bytes(
        self,
        *,
        data: bytes,
        destination_path: str,
        content_type: str,
        overwrite: bool,
    ) -> ArtifactRecord:
        """Upload bytes to Azure Blob Storage."""

        normalized = normalize_relative_path(
            destination_path
        )

        try:
            self.container_client.upload_blob(
                name=normalized,
                data=data,
                overwrite=overwrite,
                content_settings=ContentSettings(
                    content_type=content_type
                ),
            )
        except AzureError as error:
            raise ArtifactRepositoryError(
                "Could not upload Azure Blob artifact: "
                f"{normalized}"
            ) from error

        return ArtifactRecord(
            relative_path=normalized,
            size_bytes=len(data),
            sha256=calculate_bytes_sha256(data),
            content_type=content_type,
        )

    def download_bytes(
        self,
        path: str,
    ) -> bytes:
        """Download bytes from Azure Blob Storage."""

        normalized = normalize_relative_path(
            path
        )

        try:
            return (
                self.container_client
                .download_blob(normalized)
                .readall()
            )
        except ResourceNotFoundError as error:
            raise ArtifactRepositoryError(
                f"Azure Blob artifact does not exist: {normalized}"
            ) from error
        except AzureError as error:
            raise ArtifactRepositoryError(
                f"Could not download Azure Blob artifact: {normalized}"
            ) from error

    def exists(
        self,
        path: str,
    ) -> bool:
        """Return whether an Azure Blob exists."""

        normalized = normalize_relative_path(
            path
        )

        try:
            return (
                self.container_client
                .get_blob_client(normalized)
                .exists()
            )
        except AzureError as error:
            raise ArtifactRepositoryError(
                "Could not inspect Azure Blob artifact: "
                f"{normalized}"
            ) from error


def create_artifact_repository(
    *,
    backend: str,
    local_root: Path | None = None,
    azure_storage_account: str | None = None,
    azure_storage_container: str | None = None,
) -> ArtifactRepository:
    """Create the configured artifact repository."""

    normalized_backend = backend.strip().lower()

    if normalized_backend == "local":
        if local_root is None:
            raise ArtifactRepositoryError(
                "local_root is required for local storage."
            )

        return LocalArtifactRepository(
            root_directory=local_root
        )

    if normalized_backend == "azure_blob":
        if not azure_storage_account:
            raise ArtifactRepositoryError(
                "AZURE_STORAGE_ACCOUNT is required."
            )

        if not azure_storage_container:
            raise ArtifactRepositoryError(
                "AZURE_STORAGE_CONTAINER is required."
            )

        return AzureBlobArtifactRepository(
            account_name=azure_storage_account,
            container_name=azure_storage_container,
        )

    raise ArtifactRepositoryError(
        "Artifact backend must be local or azure_blob."
    )