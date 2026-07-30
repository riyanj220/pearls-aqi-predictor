"""Stable Phase 9 feature-store contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


LOCATION_KEY = "zafar_memon_dha_karachi"

OPENAQ_LOCATION_ID = 4814327
OPENAQ_SENSOR_ID = 13387396

REFERENCE_LATITUDE = 24.814741
REFERENCE_LONGITUDE = 67.067062


@dataclass(frozen=True)
class FeatureDefinition:
    """One feature-store column definition."""

    name: str
    offline_type: str
    description: str
    nullable: bool = False


@dataclass(frozen=True)
class FeatureGroupContract:
    """Stable feature-group schema and key contract."""

    name: str
    version: int
    description: str
    primary_key: tuple[str, ...]
    event_time: str
    online_enabled: bool
    features: tuple[FeatureDefinition, ...]

    @property
    def feature_names(self) -> list[str]:
        """Return feature names in contract order."""

        return [
            feature.name
            for feature in self.features
        ]

    def validate_dataframe(
        self,
        dataframe: pd.DataFrame,
        *,
        allow_additional_columns: bool = False,
    ) -> None:
        """Validate a DataFrame before Feature Store insertion."""

        if not isinstance(dataframe, pd.DataFrame):
            raise TypeError(
                f"{self.name} input must be a pandas DataFrame."
            )

        missing_columns = [
            column
            for column in self.feature_names
            if column not in dataframe.columns
        ]

        if missing_columns:
            raise ValueError(
                f"{self.name} is missing required columns: "
                f"{missing_columns}"
            )

        if not allow_additional_columns:
            additional_columns = [
                column
                for column in dataframe.columns
                if column not in self.feature_names
            ]

            if additional_columns:
                raise ValueError(
                    f"{self.name} contains unexpected columns: "
                    f"{additional_columns}"
                )

        null_key_columns = [
            column
            for column in (
                *self.primary_key,
                self.event_time,
            )
            if dataframe[column].isna().any()
        ]

        if null_key_columns:
            raise ValueError(
                f"{self.name} contains null key/event-time "
                f"values in: {null_key_columns}"
            )

        duplicate_columns = list(
            dict.fromkeys(
                [
                    *self.primary_key,
                    self.event_time,
                ]
            )
        )

        duplicate_count = int(
            dataframe.duplicated(
                subset=duplicate_columns,
            ).sum()
        )

        if duplicate_count:
            raise ValueError(
                f"{self.name} contains {duplicate_count} "
                "duplicate logical records."
            )

    def safe_summary(self) -> dict[str, Any]:
        """Return a serializable contract summary."""

        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "primary_key": list(self.primary_key),
            "event_time": self.event_time,
            "online_enabled": self.online_enabled,
            "feature_count": len(self.features),
            "features": [
                {
                    "name": feature.name,
                    "offline_type": feature.offline_type,
                    "description": feature.description,
                    "nullable": feature.nullable,
                }
                for feature in self.features
            ],
        }


def build_pm25_observation_contract(
    *,
    name: str,
    version: int,
) -> FeatureGroupContract:
    """Return the hourly PM2.5 observation contract."""

    return FeatureGroupContract(
        name=name,
        version=version,
        description=(
            "Validated hourly PM2.5 observations for the "
            "Zafar Memon DHA reference location."
        ),
        primary_key=(
            "location_key",
            "sensor_id",
        ),
        event_time="datetime_utc",
        online_enabled=False,
        features=(
            FeatureDefinition(
                "location_key",
                "string",
                "Stable project location identifier.",
            ),
            FeatureDefinition(
                "location_id",
                "bigint",
                "OpenAQ location identifier.",
            ),
            FeatureDefinition(
                "sensor_id",
                "bigint",
                "OpenAQ sensor identifier.",
            ),
            FeatureDefinition(
                "datetime_utc",
                "timestamp",
                "UTC hour represented by the observation.",
            ),
            FeatureDefinition(
                "pm25_ug_m3",
                "double",
                "Validated hourly PM2.5 concentration.",
                nullable=True,
            ),
            FeatureDefinition(
                "pm25_quality_status",
                "string",
                "Result of the established PM2.5 quality rules.",
            ),
            FeatureDefinition(
                "pm25_is_missing",
                "boolean",
                "Whether valid PM2.5 is unavailable for the hour.",
            ),
            FeatureDefinition(
                "source",
                "string",
                "Pollution source name.",
            ),
            FeatureDefinition(
                "retrieved_at_utc",
                "timestamp",
                "UTC time at which the source data was retrieved.",
            ),
            FeatureDefinition(
                "pipeline_run_id",
                "string",
                "Identifier of the ingestion pipeline run.",
            ),
            FeatureDefinition(
                "source_data_version",
                "string",
                "Version of the source validation contract.",
            ),
        ),
    )


def build_weather_observation_contract(
    *,
    name: str,
    version: int,
) -> FeatureGroupContract:
    """Return the hourly historical-weather contract."""

    weather_features = (
        FeatureDefinition(
            "temperature_2m_c",
            "double",
            "Air temperature at two metres in Celsius.",
        ),
        FeatureDefinition(
            "relative_humidity_2m_pct",
            "double",
            "Relative humidity at two metres.",
        ),
        FeatureDefinition(
            "dew_point_2m_c",
            "double",
            "Dew point at two metres in Celsius.",
        ),
        FeatureDefinition(
            "surface_pressure_hpa",
            "double",
            "Surface pressure in hectopascals.",
        ),
        FeatureDefinition(
            "precipitation_mm",
            "double",
            "Hourly precipitation in millimetres.",
        ),
        FeatureDefinition(
            "rain_mm",
            "double",
            "Hourly rain in millimetres.",
        ),
        FeatureDefinition(
            "cloud_cover_pct",
            "double",
            "Total cloud cover percentage.",
        ),
        FeatureDefinition(
            "wind_speed_10m_kmh",
            "double",
            "Wind speed at ten metres.",
        ),
        FeatureDefinition(
            "wind_direction_10m_deg",
            "double",
            "Wind direction at ten metres.",
        ),
        FeatureDefinition(
            "wind_gusts_10m_kmh",
            "double",
            "Wind gust speed at ten metres.",
        ),
    )

    return FeatureGroupContract(
        name=name,
        version=version,
        description=(
            "Validated hourly historical weather observations "
            "for the Zafar Memon DHA reference location."
        ),
        primary_key=("location_key",),
        event_time="datetime_utc",
        online_enabled=False,
        features=(
            FeatureDefinition(
                "location_key",
                "string",
                "Stable project location identifier.",
            ),
            FeatureDefinition(
                "datetime_utc",
                "timestamp",
                "UTC hour represented by the observation.",
            ),
            *weather_features,
            FeatureDefinition(
                "source",
                "string",
                "Weather source name.",
            ),
            FeatureDefinition(
                "retrieved_at_utc",
                "timestamp",
                "UTC source retrieval time.",
            ),
            FeatureDefinition(
                "pipeline_run_id",
                "string",
                "Identifier of the ingestion pipeline run.",
            ),
            FeatureDefinition(
                "source_data_version",
                "string",
                "Version of the source validation contract.",
            ),
        ),
    )


def build_engineered_feature_contract(
    *,
    name: str,
    version: int,
    model_feature_columns: list[str],
) -> FeatureGroupContract:
    """Build the reusable reference-time feature contract."""

    excluded_columns = {
    "forecast_horizon_hours",
    "target_time",
    "target_time_utc",
    "target_pm25_ug_m3",
    }


    reference_feature_columns = [
        column
        for column in model_feature_columns
        if column not in excluded_columns
        and not column.startswith("target_")
    ]

    generated_features = tuple(
        FeatureDefinition(
            name=column,
            offline_type="double",
            description=(
                "Reusable Phase 2 reference-time model feature."
            ),
            nullable=True,
        )
        for column in reference_feature_columns
    )

    return FeatureGroupContract(
        name=name,
        version=version,
        description=(
            "Reusable reference-time PM2.5, current-weather "
            "and calendar features produced by the finalized "
            "Phase 2 feature pipeline."
        ),
        primary_key=("location_key",),
        event_time="reference_time",
        online_enabled=False,
        features=(
            FeatureDefinition(
                "location_key",
                "string",
                "Stable project location identifier.",
            ),
            FeatureDefinition(
                "reference_time",
                "timestamp",
                "UTC reference time for feature computation.",
            ),
            *generated_features,
            FeatureDefinition(
                "feature_pipeline_version",
                "string",
                "Version of the feature-generation contract.",
            ),
            FeatureDefinition(
                "pipeline_run_id",
                "string",
                "Identifier of the feature pipeline run.",
            ),
        ),
    )


def build_feature_group_contracts(
    *,
    pm25_version: int,
    weather_version: int,
    engineered_version: int,
    pm25_name: str,
    weather_name: str,
    engineered_name: str,
    model_feature_columns: list[str],
) -> dict[str, FeatureGroupContract]:
    """Build all required Phase 9 feature-group contracts."""

    return {
        "pm25": build_pm25_observation_contract(
            name=pm25_name,
            version=pm25_version,
        ),
        "weather": build_weather_observation_contract(
            name=weather_name,
            version=weather_version,
        ),
        "engineered": build_engineered_feature_contract(
            name=engineered_name,
            version=engineered_version,
            model_feature_columns=model_feature_columns,
        ),
    }