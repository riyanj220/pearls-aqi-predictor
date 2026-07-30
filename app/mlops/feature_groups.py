"""Hopsworks feature-group schema adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.mlops.client import (
    HopsworksResources,
)
from app.mlops.config import (
    MLOpsSettings,
)
from app.mlops.contracts import (
    FeatureGroupContract,
)


class FeatureGroupConfigurationError(
    ValueError
):
    """Raised when a feature-group contract is invalid."""


class FeatureGroupCreationError(
    RuntimeError
):
    """Raised when feature-group metadata cannot be created."""


@dataclass(frozen=True)
class ResolvedFeatureGroups:
    """Resolved Hopsworks feature-group handles."""

    pm25: Any | None
    weather: Any | None
    engineered: Any | None
    dry_run: bool

    def safe_summary(
        self,
    ) -> dict[str, object]:
        """Return safe feature-group resolution metadata."""

        return {
            "dry_run": self.dry_run,
            "pm25_resolved": (
                self.pm25 is not None
            ),
            "weather_resolved": (
                self.weather is not None
            ),
            "engineered_resolved": (
                self.engineered is not None
            ),
        }


def validate_contract(
    contract: FeatureGroupContract,
) -> None:
    """Validate one feature-group metadata contract."""

    feature_names = contract.feature_names

    if len(feature_names) != len(
        set(feature_names)
    ):
        raise FeatureGroupConfigurationError(
            f"{contract.name} contains duplicate "
            "feature names."
        )

    missing_primary_keys = [
        column
        for column in contract.primary_key
        if column not in feature_names
    ]

    if missing_primary_keys:
        raise FeatureGroupConfigurationError(
            f"{contract.name} is missing primary-key "
            f"features: {missing_primary_keys}"
        )

    if contract.event_time not in feature_names:
        raise FeatureGroupConfigurationError(
            f"{contract.name} is missing event-time "
            f"feature {contract.event_time!r}."
        )

    forbidden_engineered_features = {
        "target_pm25_ug_m3",
        "target_time",
        "target_time_utc",
    }.intersection(feature_names)

    if forbidden_engineered_features:
        raise FeatureGroupConfigurationError(
            f"{contract.name} contains forbidden labels "
            f"or target timestamps: "
            f"{sorted(forbidden_engineered_features)}"
        )


def validate_contracts(
    contracts: dict[
        str,
        FeatureGroupContract,
    ],
) -> None:
    """Validate all required feature-group contracts."""

    expected_keys = {
        "pm25",
        "weather",
        "engineered",
    }

    if set(contracts) != expected_keys:
        raise FeatureGroupConfigurationError(
            "Expected exactly the PM2.5, weather, and "
            "engineered feature-group contracts."
        )

    names = [
        contract.name
        for contract in contracts.values()
    ]

    if len(names) != len(set(names)):
        raise FeatureGroupConfigurationError(
            "Feature-group names must be unique."
        )

    for contract in contracts.values():
        validate_contract(contract)


def _to_hopsworks_features(
    contract: FeatureGroupContract,
) -> list[Any]:
    """Convert local definitions to Hopsworks Feature objects."""

    try:
        from hsfs.feature import Feature
    except ImportError as error:
        raise FeatureGroupCreationError(
            "Could not import hsfs.feature.Feature."
        ) from error

    return [
        Feature(
            name=feature.name,
            type=feature.offline_type,
            description=feature.description,
        )
        for feature in contract.features
    ]


def _resolve_feature_group(
    *,
    feature_store: Any,
    contract: FeatureGroupContract,
) -> Any:
    """Resolve or create one feature-group metadata object."""

    return feature_store.get_or_create_feature_group(
        name=contract.name,
        version=contract.version,
        description=contract.description,
        primary_key=list(
            contract.primary_key
        ),
        event_time=contract.event_time,
        online_enabled=contract.online_enabled,
        features=_to_hopsworks_features(
            contract
        ),
    )


def create_or_get_feature_groups(
    *,
    resources: HopsworksResources,
    settings: MLOpsSettings,
    contracts: dict[
        str,
        FeatureGroupContract,
    ],
) -> ResolvedFeatureGroups:
    """Validate and resolve the three feature groups."""

    validate_contracts(contracts)

    if settings.mlops_dry_run:
        return ResolvedFeatureGroups(
            pm25=None,
            weather=None,
            engineered=None,
            dry_run=True,
        )

    if resources.feature_store is None:
        raise FeatureGroupCreationError(
            "The Hopsworks Feature Store was not resolved."
        )

    try:
        return ResolvedFeatureGroups(
            pm25=_resolve_feature_group(
                feature_store=resources.feature_store,
                contract=contracts["pm25"],
            ),
            weather=_resolve_feature_group(
                feature_store=resources.feature_store,
                contract=contracts["weather"],
            ),
            engineered=_resolve_feature_group(
                feature_store=resources.feature_store,
                contract=contracts["engineered"],
            ),
            dry_run=False,
        )

    except Exception as error:
        raise FeatureGroupCreationError(
            "Could not resolve the required Hopsworks "
            "feature groups."
        ) from error