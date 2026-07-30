"""Hopsworks and local MLOps integration package."""

from app.mlops.client import (
    HopsworksConfigurationError,
    HopsworksConnectionError,
    HopsworksDependencyError,
    HopsworksResources,
    connect_to_hopsworks,
    get_hopsworks_sdk_version,
)
from app.mlops.config import (
    FeatureStoreBackend,
    MLOpsSettings,
    ModelRegistryBackend,
    get_mlops_settings,
)

from app.mlops.contracts import (
    FeatureDefinition,
    FeatureGroupContract,
    build_feature_group_contracts,
)
from app.mlops.feature_groups import (
    FeatureGroupConfigurationError,
    FeatureGroupCreationError,
    ResolvedFeatureGroups,
    create_or_get_feature_groups,
    validate_contracts,
)

from app.mlops.gaps import (
    MissingInterval,
    detect_hourly_gaps,
)

__all__ = [
    "FeatureStoreBackend",
    "HopsworksConfigurationError",
    "HopsworksConnectionError",
    "HopsworksDependencyError",
    "HopsworksResources",
    "MLOpsSettings",
    "ModelRegistryBackend",
    "connect_to_hopsworks",
    "get_hopsworks_sdk_version",
    "get_mlops_settings",
    "FeatureDefinition",
    "FeatureGroupContract",
    "FeatureGroupConfigurationError",
    "FeatureGroupCreationError",
    "ResolvedFeatureGroups",
    "build_feature_group_contracts",
    "create_or_get_feature_groups",
    "validate_contracts",
    "MissingInterval",
    "detect_hourly_gaps",
]