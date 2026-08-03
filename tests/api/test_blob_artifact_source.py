"""Tests for durable artifact materialization."""

from __future__ import annotations

from pathlib import Path

from app.api.config import APISettings
from app.api.services.blob_artifact_source import (
    BlobArtifactSource,
)
from app.artifacts.repository import (
    LocalArtifactRepository,
)


def test_materializes_latest_package(
    tmp_path: Path,
) -> None:
    """A published durable package should materialize locally."""

    durable_root = (
        tmp_path / "durable"
    )

    source_directory = (
        tmp_path / "source"
    )

    cache_directory = (
        tmp_path / "cache" / "latest"
    )

    source_directory.mkdir(
        parents=True
    )

    fixture_directory = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "aqi"
        / "latest"
    )

    required_names = [
        "live_pm25_aqi_forecast.parquet",
        "alert_episodes.json",
        "aqi_forecast_summary.json",
        "aqi_metadata.json",
        "phase_6_validation_report.json",
    ]

    for filename in required_names:
        (
            source_directory / filename
        ).write_bytes(
            (
                fixture_directory
                / filename
            ).read_bytes()
        )

    durable_repository = (
        LocalArtifactRepository(
            durable_root
        )
    )

    durable_repository.publish_run(
        artifact_type="aqi",
        run_id="test-aqi-run",
        source_directory=(
            source_directory
        ),
        validation_status=(
            "AQI_ALERT_PIPELINE_APPROVED"
        ),
        source_run_id=(
            "test-inference-run"
        ),
    )

    settings = APISettings(
        artifact_backend="azure_blob",
        azure_storage_account="testaccount",
        azure_storage_container="artifacts",
        phase_6_blob_cache_directory=(
            cache_directory
        ),
        artifact_cache_seconds=0,
    )

    source = BlobArtifactSource(
        settings,
        repository=durable_repository,
    )

    result = source.refresh(
        force=True
    )

    assert result.refreshed
    assert result.run_id == "test-aqi-run"

    assert {
        path.name
        for path in cache_directory.iterdir()
        if path.is_file()
    } == set(required_names)