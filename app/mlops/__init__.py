"""Hopsworks and local MLOps integration package."""

from app.mlops.champion_challenger import (
    ChampionChallengerError,
    PromotionDecision,
    evaluate_promotion_gates,
)
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
    ModelLoadingMode,
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
from app.mlops.model_registry import (
    ModelRegistryError,
    RegisteredModelResult,
    ResolvedProductionModel,
    calculate_sha256,
    prepare_model_package,
    register_initial_production_model,
    resolve_production_model,
)
from app.mlops.retraining import (
    HORIZON_GROUPS,
    RetrainingEligibility,
    RetrainingError,
    evaluate_candidate,
    evaluate_retraining_eligibility,
    train_candidate_model,
)
from app.pipelines.feature_views import (
    FeatureViewError,
    ResolvedFeatureView,
    create_or_get_reference_feature_view,
)
from app.pipelines.training_datasets import (
    DatasetParityResult,
    TrainingDatasetError,
    build_hopsworks_backed_training_dataset,
    compare_training_datasets,
    read_hopsworks_reference_features,
    save_versioned_training_snapshot,
)

__all__ = [
    "HORIZON_GROUPS",
    "ChampionChallengerError",
    "DatasetParityResult",
    "FeatureDefinition",
    "FeatureGroupConfigurationError",
    "FeatureGroupContract",
    "FeatureGroupCreationError",
    "FeatureStoreBackend",
    "FeatureViewError",
    "HopsworksConfigurationError",
    "HopsworksConnectionError",
    "HopsworksDependencyError",
    "HopsworksResources",
    "MLOpsSettings",
    "MissingInterval",
    "ModelLoadingMode",
    "ModelRegistryBackend",
    "ModelRegistryError",
    "PromotionDecision",
    "RegisteredModelResult",
    "ResolvedFeatureGroups",
    "ResolvedFeatureView",
    "ResolvedProductionModel",
    "RetrainingEligibility",
    "RetrainingError",
    "TrainingDatasetError",
    "build_feature_group_contracts",
    "build_hopsworks_backed_training_dataset",
    "calculate_sha256",
    "compare_training_datasets",
    "connect_to_hopsworks",
    "create_or_get_feature_groups",
    "create_or_get_reference_feature_view",
    "detect_hourly_gaps",
    "evaluate_candidate",
    "evaluate_promotion_gates",
    "evaluate_retraining_eligibility",
    "get_hopsworks_sdk_version",
    "get_mlops_settings",
    "prepare_model_package",
    "read_hopsworks_reference_features",
    "register_initial_production_model",
    "resolve_production_model",
    "save_versioned_training_snapshot",
    "train_candidate_model",
    "validate_contracts",
]
