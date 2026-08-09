from __future__ import annotations

import json
from pathlib import Path

import joblib

from app.artifacts.repository import (
    LocalArtifactRepository,
)
from app.mlops.azure_blob_model_repository import (
    AzureBlobModelRepository,
)
from app.mlops.config import MLOpsSettings
from app.mlops.model_repository import (
    ModelRepositoryError,
)


def create_candidate(
    root: Path,
    *,
    value: int,
) -> Path:
    directory = (
        root / f"candidate-{value}"
    )

    directory.mkdir()

    joblib.dump(
        {
            "model_value": value,
        },
        directory
        / "best_model.joblib",
    )

    (
        directory
        / "model_feature_columns.json"
    ).write_text(
        json.dumps(
            {
                "feature_columns": [
                    "feature_a",
                    "feature_b",
                ]
            }
        ),
        encoding="utf-8",
    )

    (
        directory
        / "candidate_metadata.json"
    ).write_text(
        json.dumps(
            {
                "candidate": value
            }
        ),
        encoding="utf-8",
    )

    return directory


def create_repository(
    tmp_path: Path,
) -> AzureBlobModelRepository:

    transport = (
        LocalArtifactRepository(
            root_directory=(
                tmp_path / "blob"
            )
        )
    )

    settings = MLOpsSettings(
        model_registry_backend=(
            "azure_blob"
        ),
        azure_storage_account=(
            "testaccount"
        ),
        azure_storage_container=(
            "testcontainer"
        ),
        azure_model_registry_prefix=(
            "model-registry"
        ),
        hopsworks_model_name=(
            "pearls_aqi_pm25_forecaster"
        ),
        model_cache_directory=(
            str(
                tmp_path / "cache"
            )
        ),
    )

    return AzureBlobModelRepository(
        settings=settings,
        repository=transport,
    )


def test_candidate_registration_is_versioned(
    tmp_path: Path,
) -> None:

    repository = create_repository(
        tmp_path
    )

    candidate_1 = create_candidate(
        tmp_path,
        value=1,
    )

    candidate_2 = create_candidate(
        tmp_path,
        value=2,
    )

    first = (
        repository
        .register_candidate_model(
            candidate_directory=(
                candidate_1
            ),
            metrics={
                "test_mae": 10.0
            },
        )
    )

    second = (
        repository
        .register_candidate_model(
            candidate_directory=(
                candidate_2
            ),
            metrics={
                "test_mae": 9.0
            },
        )
    )

    assert first.version == 1
    assert second.version == 2

    assert first.status == "CANDIDATE"
    assert second.status == "CANDIDATE"


def test_candidate_registration_does_not_promote(
    tmp_path: Path,
) -> None:

    repository = create_repository(
        tmp_path
    )

    candidate = create_candidate(
        tmp_path,
        value=1,
    )

    repository.register_candidate_model(
        candidate_directory=(
            candidate
        ),
        metrics={
            "test_mae": 10.0
        },
    )

    assert not repository.repository.exists(
        repository.production_pointer_path
    )


def test_production_pointer_can_select_version(
    tmp_path: Path,
) -> None:

    repository = create_repository(
        tmp_path
    )

    candidate = create_candidate(
        tmp_path,
        value=1,
    )

    registered = (
        repository
        .register_candidate_model(
            candidate_directory=(
                candidate
            ),
            metrics={
                "test_mae": 10.0
            },
        )
    )

    pointer = (
        repository
        .set_production_version(
            version=(
                registered.version
            )
        )
    )

    assert pointer["version"] == 1

    assert (
        pointer["production_status"]
        == "PRODUCTION"
    )


def test_missing_version_cannot_be_promoted(
    tmp_path: Path,
) -> None:

    repository = create_repository(
        tmp_path
    )

    try:
        repository.set_production_version(
            version=99
        )
    except ModelRepositoryError:
        pass
    else:
        raise AssertionError(
            "Missing model version "
            "was unexpectedly promoted."
        )
