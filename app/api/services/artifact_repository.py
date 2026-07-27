"""Validated and cached access to the latest Phase 6 artifacts."""

from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.api.config import APISettings
from app.api.schemas.common import FreshnessStatus


class ArtifactRepositoryError(RuntimeError):
    """Base exception for artifact repository failures."""


class ArtifactNotFoundError(ArtifactRepositoryError):
    """Raised when a required Phase 6 artifact is absent."""


class ArtifactFormatError(ArtifactRepositoryError):
    """Raised when Parquet or JSON cannot be loaded."""


class ArtifactSchemaError(ArtifactRepositoryError):
    """Raised when artifact contents violate the contract."""


class ArtifactRunMismatchError(ArtifactRepositoryError):
    """Raised when artifacts belong to different runs."""


@dataclass(frozen=True)
class ArtifactFreshness:
    """Calculated age and freshness state."""

    generated_at_utc: datetime | None
    age_minutes: float | None
    age_hours: float | None
    status: FreshnessStatus


@dataclass(frozen=True)
class ArtifactBundle:
    """One validated Phase 6 artifact package."""

    forecast_df: pd.DataFrame
    alert_episodes: list[dict[str, Any]]
    summary: dict[str, Any]
    metadata: dict[str, Any]
    validation_report: dict[str, Any]

    phase_6_run_id: str
    source_phase_5_run_id: str

    generated_at_utc: datetime
    loaded_at_utc: datetime

    freshness: ArtifactFreshness


@dataclass
class _CacheEntry:
    """Internal in-memory cache state."""

    bundle: ArtifactBundle
    loaded_monotonic: float

    file_signature: tuple[
        tuple[str, int, int],
        ...
    ]


class ArtifactRepository:
    """
    Load, validate, and cache the latest Phase 6 artifacts.

    Each API worker has its own in-memory repository cache.
    """

    ACCEPTABLE_PHASE_6_STATUSES = {
        "AQI_ALERT_PIPELINE_APPROVED",
        "AQI_ALERT_PIPELINE_APPROVED_WITH_LIMITATIONS",
    }

    REQUIRED_FORECAST_COLUMNS = {
        "pipeline_run_id",
        "prediction_generated_at_utc",
        "reference_time",
        "target_time",
        "forecast_horizon_hours",
        "predicted_pm25_ug_m3",
        "indicative_hourly_pm25_aqi",
        "indicative_hourly_aqi_category",
        "indicative_hourly_aqi_color_hex",
        "rolling_24h_pm25_ug_m3",
        "rolling_24h_pm25_aqi",
        "rolling_24h_aqi_category",
        "rolling_24h_aqi_color_hex",
        "rolling_24h_pm25_is_complete",
        "rolling_24h_missing_hours",
        "rolling_observed_hour_count",
        "rolling_predicted_hour_count",
        "alert_basis",
        "alert_trigger_aqi",
        "alert_trigger_category",
        "alert_level",
        "alert_is_active",
        "sensitive_groups_alert",
        "general_population_alert",
        "hazardous_alert",
        "health_message",
        "recommended_action",
        "location_name",
    }

    def __init__(
        self,
        settings: APISettings,
    ) -> None:
        self._settings = settings
        self._lock = threading.RLock()
        self._cache: _CacheEntry | None = None

    @property
    def required_paths(self) -> tuple[Path, ...]:
        """Return all required Phase 6 artifact paths."""

        return (
            self._settings.forecast_path,
            self._settings.alert_episodes_path,
            self._settings.summary_path,
            self._settings.metadata_path,
            self._settings.validation_report_path,
        )

    def clear_cache(self) -> None:
        """Remove the current in-memory artifact cache."""

        with self._lock:
            self._cache = None

    def load_latest(
        self,
        *,
        force_reload: bool = False,
    ) -> ArtifactBundle:
        """
        Return the validated latest Phase 6 package.

        Cached data is reused until the cache expires or source files
        change.
        """

        with self._lock:
            self._validate_required_files_exist()

            current_signature = (
                self._build_file_signature()
            )

            if (
                not force_reload
                and self._cache is not None
                and self._cache_is_usable(
                    current_signature
                )
            ):
                return self._cache.bundle

            bundle = self._load_and_validate_bundle()

            self._cache = _CacheEntry(
                bundle=bundle,
                loaded_monotonic=time.monotonic(),
                file_signature=current_signature,
            )

            return bundle

    def _cache_is_usable(
        self,
        current_signature: tuple[
            tuple[str, int, int],
            ...
        ],
    ) -> bool:
        """Return whether the current cache can be reused."""

        if self._cache is None:
            return False

        cache_age_seconds = (
            time.monotonic()
            - self._cache.loaded_monotonic
        )

        cache_within_ttl = (
            cache_age_seconds
            <= self._settings.artifact_cache_seconds
        )

        source_files_unchanged = (
            self._cache.file_signature
            == current_signature
        )

        return (
            cache_within_ttl
            and source_files_unchanged
        )

    def _validate_required_files_exist(self) -> None:
        """Ensure every required artifact exists and is non-empty."""

        missing_paths = [
            path
            for path in self.required_paths
            if not path.exists()
        ]

        if missing_paths:
            raise ArtifactNotFoundError(
                "Required Phase 6 artifacts are missing: "
                + ", ".join(
                    path.name
                    for path in missing_paths
                )
            )

        empty_paths = [
            path
            for path in self.required_paths
            if path.stat().st_size <= 0
        ]

        if empty_paths:
            raise ArtifactFormatError(
                "Required Phase 6 artifacts are empty: "
                + ", ".join(
                    path.name
                    for path in empty_paths
                )
            )

    def _build_file_signature(
        self,
    ) -> tuple[tuple[str, int, int], ...]:
        """
        Build a signature from name, size, and modification time.

        This lets the repository detect newly published latest files.
        """

        return tuple(
            (
                path.name,
                path.stat().st_size,
                path.stat().st_mtime_ns,
            )
            for path in sorted(
                self.required_paths,
                key=lambda item: item.name,
            )
        )

    def _load_and_validate_bundle(
        self,
    ) -> ArtifactBundle:
        """Read all artifacts and validate their consistency."""

        forecast_df = self._load_forecast()

        alert_episodes = self._load_json(
            self._settings.alert_episodes_path,
            expected_type=list,
        )

        summary = self._load_json(
            self._settings.summary_path,
            expected_type=dict,
        )

        metadata = self._load_json(
            self._settings.metadata_path,
            expected_type=dict,
        )

        validation_report = self._load_json(
            self._settings.validation_report_path,
            expected_type=dict,
        )

        validated_forecast_df = (
            self._validate_forecast(
                forecast_df
            )
        )

        (
            phase_6_run_id,
            source_phase_5_run_id,
        ) = self._validate_run_consistency(
            forecast_df=validated_forecast_df,
            summary=summary,
            metadata=metadata,
            validation_report=validation_report,
        )

        self._validate_phase_6_status(
            validation_report
        )

        generated_at_utc = self._extract_generated_at(
            summary
        )

        freshness = self.calculate_freshness(
            generated_at_utc
        )

        loaded_at_utc = datetime.now(
            timezone.utc
        )

        safe_alert_episodes = json_safe_value(
            alert_episodes
        )

        safe_summary = json_safe_value(
            summary
        )

        safe_metadata = json_safe_value(
            metadata
        )

        safe_validation_report = json_safe_value(
            validation_report
        )

        if not isinstance(
            safe_alert_episodes,
            list,
        ):
            raise ArtifactSchemaError(
                "Alert episodes must be a JSON list."
            )

        if not isinstance(safe_summary, dict):
            raise ArtifactSchemaError(
                "Forecast summary must be a JSON object."
            )

        if not isinstance(safe_metadata, dict):
            raise ArtifactSchemaError(
                "AQI metadata must be a JSON object."
            )

        if not isinstance(
            safe_validation_report,
            dict,
        ):
            raise ArtifactSchemaError(
                "Validation report must be a JSON object."
            )

        return ArtifactBundle(
            forecast_df=validated_forecast_df,
            alert_episodes=safe_alert_episodes,
            summary=safe_summary,
            metadata=safe_metadata,
            validation_report=(
                safe_validation_report
            ),
            phase_6_run_id=phase_6_run_id,
            source_phase_5_run_id=(
                source_phase_5_run_id
            ),
            generated_at_utc=generated_at_utc,
            loaded_at_utc=loaded_at_utc,
            freshness=freshness,
        )

    def _load_forecast(self) -> pd.DataFrame:
        """Read the Phase 6 forecast Parquet file."""

        try:
            forecast_df = pd.read_parquet(
                self._settings.forecast_path
            )
        except Exception as exc:
            raise ArtifactFormatError(
                "Could not read the Phase 6 forecast Parquet file."
            ) from exc

        if not isinstance(
            forecast_df,
            pd.DataFrame,
        ):
            raise ArtifactFormatError(
                "Forecast artifact did not produce a DataFrame."
            )

        return forecast_df

    @staticmethod
    def _load_json(
        path: Path,
        *,
        expected_type: type,
    ) -> Any:
        """Read JSON and validate its top-level type."""

        try:
            with path.open(
                "r",
                encoding="utf-8",
            ) as file:
                payload = json.load(file)
        except json.JSONDecodeError as exc:
            raise ArtifactFormatError(
                f"Invalid JSON artifact: {path.name}"
            ) from exc
        except OSError as exc:
            raise ArtifactFormatError(
                f"Could not read JSON artifact: {path.name}"
            ) from exc

        if not isinstance(
            payload,
            expected_type,
        ):
            raise ArtifactSchemaError(
                f"{path.name} must contain "
                f"{expected_type.__name__}, received "
                f"{type(payload).__name__}."
            )

        return payload

    def _validate_forecast(
        self,
        forecast_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Validate the Phase 6 forecast serving contract."""

        missing_columns = sorted(
            self.REQUIRED_FORECAST_COLUMNS.difference(
                forecast_df.columns
            )
        )

        if missing_columns:
            raise ArtifactSchemaError(
                "Forecast is missing required columns: "
                f"{missing_columns}"
            )

        validated_df = forecast_df.copy()

        timestamp_columns = [
            "prediction_generated_at_utc",
            "reference_time",
            "target_time",
        ]

        for column in timestamp_columns:
            validated_df[column] = pd.to_datetime(
                validated_df[column],
                utc=True,
                errors="coerce",
            )

        validated_df[
            "forecast_horizon_hours"
        ] = pd.to_numeric(
            validated_df[
                "forecast_horizon_hours"
            ],
            errors="coerce",
        )

        numeric_columns = [
            "predicted_pm25_ug_m3",
            "indicative_hourly_pm25_aqi",
            "rolling_24h_pm25_ug_m3",
            "rolling_24h_pm25_aqi",
            "alert_trigger_aqi",
        ]

        for column in numeric_columns:
            validated_df[column] = pd.to_numeric(
                validated_df[column],
                errors="coerce",
            )

        validated_df = (
            validated_df
            .sort_values(
                "forecast_horizon_hours"
            )
            .reset_index(drop=True)
        )

        if len(validated_df) != 72:
            raise ArtifactSchemaError(
                "Forecast must contain exactly 72 rows."
            )

        expected_horizons = list(
            range(1, 73)
        )

        actual_horizons = (
            validated_df[
                "forecast_horizon_hours"
            ]
            .astype("Int64")
            .tolist()
        )

        if actual_horizons != expected_horizons:
            raise ArtifactSchemaError(
                "Forecast horizons must be exactly 1 through 72."
            )

        if validated_df[
            "target_time"
        ].isna().any():
            raise ArtifactSchemaError(
                "Forecast contains invalid target timestamps."
            )

        if validated_df[
            "target_time"
        ].duplicated().any():
            raise ArtifactSchemaError(
                "Forecast contains duplicate target timestamps."
            )

        if not validated_df[
            "target_time"
        ].is_monotonic_increasing:
            raise ArtifactSchemaError(
                "Forecast target timestamps are not ordered."
            )

        if validated_df[
            "reference_time"
        ].nunique() != 1:
            raise ArtifactSchemaError(
                "Forecast must contain one reference timestamp."
            )

        self._validate_hourly_timestamps(
            validated_df
        )

        predicted_pm25 = validated_df[
            "predicted_pm25_ug_m3"
        ].to_numpy(dtype=float)

        if not np.isfinite(
            predicted_pm25
        ).all():
            raise ArtifactSchemaError(
                "Forecast contains missing or infinite PM2.5 values."
            )

        if (
            validated_df[
                "predicted_pm25_ug_m3"
            ].lt(0).any()
        ):
            raise ArtifactSchemaError(
                "Forecast contains negative PM2.5 values."
            )

        required_non_null_columns = [
            "indicative_hourly_pm25_aqi",
            "indicative_hourly_aqi_category",
            "indicative_hourly_aqi_color_hex",
            "alert_level",
            "alert_basis",
            "alert_trigger_aqi",
            "alert_trigger_category",
            "health_message",
            "recommended_action",
        ]

        missing_required_values = {
            column: int(
                validated_df[
                    column
                ].isna().sum()
            )
            for column
            in required_non_null_columns
            if validated_df[
                column
            ].isna().any()
        }

        if missing_required_values:
            raise ArtifactSchemaError(
                "Forecast contains missing required values: "
                f"{missing_required_values}"
            )

        self._validate_rolling_fields(
            validated_df
        )

        return validated_df

    @staticmethod
    def _validate_hourly_timestamps(
        forecast_df: pd.DataFrame,
    ) -> None:
        """Require an exact one-hour target cadence."""

        target_differences = (
            forecast_df[
                "target_time"
            ]
            .diff()
            .dropna()
        )

        if not target_differences.eq(
            pd.Timedelta(hours=1)
        ).all():
            raise ArtifactSchemaError(
                "Forecast target timestamps must be hourly."
            )

        reference_time = forecast_df[
            "reference_time"
        ].iloc[0]

        expected_target_times = pd.date_range(
            start=reference_time
            + pd.Timedelta(hours=1),
            periods=72,
            freq="h",
            tz="UTC",
        )

        actual_target_times = pd.DatetimeIndex(
            forecast_df[
                "target_time"
            ]
        )

        if not actual_target_times.equals(
            expected_target_times
        ):
            raise ArtifactSchemaError(
                "Target timestamps do not match forecast horizons."
            )

    @staticmethod
    def _validate_rolling_fields(
        forecast_df: pd.DataFrame,
    ) -> None:
        """Validate complete and incomplete rolling-window rules."""

        complete_mask = (
            forecast_df[
                "rolling_24h_pm25_is_complete"
            ]
            .fillna(False)
            .astype(bool)
        )

        complete_missing_aqi = int(
            forecast_df.loc[
                complete_mask,
                "rolling_24h_pm25_aqi",
            ].isna().sum()
        )

        incomplete_non_null_aqi = int(
            forecast_df.loc[
                ~complete_mask,
                "rolling_24h_pm25_aqi",
            ].notna().sum()
        )

        if complete_missing_aqi:
            raise ArtifactSchemaError(
                "Complete rolling windows contain missing AQI."
            )

        if incomplete_non_null_aqi:
            raise ArtifactSchemaError(
                "Incomplete rolling windows contain non-null AQI."
            )

    @staticmethod
    def _validate_phase_6_status(
        validation_report: dict[str, Any],
    ) -> None:
        """Require a Phase 6 status approved for serving."""

        status = str(
            validation_report.get(
                "status",
                "",
            )
        )

        if (
            status
            not in ArtifactRepository
            .ACCEPTABLE_PHASE_6_STATUSES
        ):
            raise ArtifactSchemaError(
                "Phase 6 validation status does not permit serving: "
                f"{status or 'missing'}"
            )

    @staticmethod
    def _validate_run_consistency(
        *,
        forecast_df: pd.DataFrame,
        summary: dict[str, Any],
        metadata: dict[str, Any],
        validation_report: dict[str, Any],
    ) -> tuple[str, str]:
        """Confirm all Phase 6 artifacts describe one run."""

        phase_6_run_ids = {
            str(
                summary.get(
                    "phase_6_run_id",
                    "",
                )
            ),
            str(
                metadata.get(
                    "phase_6_run_id",
                    "",
                )
            ),
            str(
                validation_report.get(
                    "phase_6_run_id",
                    "",
                )
            ),
        }

        if "" in phase_6_run_ids:
            raise ArtifactSchemaError(
                "One or more Phase 6 run IDs are missing."
            )

        if len(phase_6_run_ids) != 1:
            raise ArtifactRunMismatchError(
                "Phase 6 artifacts contain mismatched run IDs."
            )

        source_phase_5_run_ids = {
            str(
                summary.get(
                    "source_phase_5_run_id",
                    "",
                )
            ),
            str(
                metadata.get(
                    "source_phase_5_run_id",
                    "",
                )
            ),
            str(
                validation_report.get(
                    "source_phase_5_run_id",
                    "",
                )
            ),
        }

        forecast_run_ids = set(
            forecast_df[
                "pipeline_run_id"
            ]
            .astype(str)
            .unique()
            .tolist()
        )

        if "" in source_phase_5_run_ids:
            raise ArtifactSchemaError(
                "One or more source Phase 5 run IDs are missing."
            )

        if len(source_phase_5_run_ids) != 1:
            raise ArtifactRunMismatchError(
                "Artifacts contain mismatched source Phase 5 run IDs."
            )

        if len(forecast_run_ids) != 1:
            raise ArtifactRunMismatchError(
                "Forecast rows contain multiple Phase 5 run IDs."
            )

        source_phase_5_run_id = next(
            iter(source_phase_5_run_ids)
        )

        forecast_run_id = next(
            iter(forecast_run_ids)
        )

        if (
            source_phase_5_run_id
            != forecast_run_id
        ):
            raise ArtifactRunMismatchError(
                "Forecast Phase 5 run ID does not match metadata."
            )

        phase_6_run_id = next(
            iter(phase_6_run_ids)
        )

        return (
            phase_6_run_id,
            source_phase_5_run_id,
        )

    @staticmethod
    def _extract_generated_at(
        summary: dict[str, Any],
    ) -> datetime:
        """Read and normalize the Phase 6 generation timestamp."""

        generated_value = summary.get(
            "generated_at_utc"
        )

        generated_timestamp = pd.to_datetime(
            generated_value,
            utc=True,
            errors="coerce",
        )

        if pd.isna(generated_timestamp):
            raise ArtifactSchemaError(
                "Forecast summary has no valid generated_at_utc."
            )

        return generated_timestamp.to_pydatetime()

    def calculate_freshness(
        self,
        generated_at_utc: datetime | None,
        *,
        now_utc: datetime | None = None,
    ) -> ArtifactFreshness:
        """Calculate age and configured freshness status."""

        if generated_at_utc is None:
            return ArtifactFreshness(
                generated_at_utc=None,
                age_minutes=None,
                age_hours=None,
                status=FreshnessStatus.UNKNOWN,
            )

        normalized_generated_time = (
            generated_at_utc
            if generated_at_utc.tzinfo is not None
            else generated_at_utc.replace(
                tzinfo=timezone.utc
            )
        )

        normalized_now = (
            now_utc
            if now_utc is not None
            else datetime.now(timezone.utc)
        )

        if normalized_now.tzinfo is None:
            normalized_now = (
                normalized_now.replace(
                    tzinfo=timezone.utc
                )
            )

        age_seconds = max(
            0.0,
            (
                normalized_now
                - normalized_generated_time
            ).total_seconds(),
        )

        age_minutes = age_seconds / 60
        age_hours = age_seconds / 3_600

        if (
            age_hours
            >= self._settings
            .forecast_staleness_threshold_hours
        ):
            status = FreshnessStatus.STALE

        elif (
            age_hours
            >= self._settings
            .forecast_aging_threshold_hours
        ):
            status = FreshnessStatus.AGING

        else:
            status = FreshnessStatus.FRESH

        return ArtifactFreshness(
            generated_at_utc=(
                normalized_generated_time
            ),
            age_minutes=round(
                age_minutes,
                3,
            ),
            age_hours=round(
                age_hours,
                3,
            ),
            status=status,
        )


def json_safe_value(
    value: Any,
) -> Any:
    """
    Convert pandas and NumPy values into JSON-safe Python values.

    Missing values become None rather than NaN.
    """

    if value is None:
        return None

    if value is pd.NA or value is pd.NaT:
        return None

    if isinstance(
        value,
        (
            pd.Timestamp,
            datetime,
        ),
    ):
        timestamp = pd.Timestamp(value)

        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize(
                "UTC"
            )
        else:
            timestamp = timestamp.tz_convert(
                "UTC"
            )

        return timestamp.to_pydatetime()

    if isinstance(
        value,
        np.generic,
    ):
        return json_safe_value(
            value.item()
        )

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None

        return value

    if isinstance(value, dict):
        return {
            str(key): json_safe_value(
                item
            )
            for key, item in value.items()
        }

    if isinstance(
        value,
        (
            list,
            tuple,
            set,
        ),
    ):
        return [
            json_safe_value(item)
            for item in value
        ]

    return value


def dataframe_to_public_records(
    dataframe: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Convert a DataFrame into JSON-safe row dictionaries."""

    raw_records = dataframe.to_dict(
        orient="records"
    )

    safe_records = json_safe_value(
        raw_records
    )

    if not isinstance(safe_records, list):
        raise ArtifactSchemaError(
            "DataFrame record conversion failed."
        )

    return safe_records