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
    ModelLoadingMode,
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

from app.mlops.champion_challenger import (
    ChampionChallengerError,
    PromotionDecision,
    evaluate_promotion_gates,
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
    "DatasetParityResult",
    "FeatureViewError",
    "ResolvedFeatureView",
    "TrainingDatasetError",
    "build_hopsworks_backed_training_dataset",
    "compare_training_datasets",
    "create_or_get_reference_feature_view",
    "read_hopsworks_reference_features",
    "save_versioned_training_snapshot",

    "ModelRegistryError",
    "RegisteredModelResult",
    "ResolvedProductionModel",
    "calculate_sha256",
    "prepare_model_package",
    "register_initial_production_model",
    "resolve_production_model",

    "ModelLoadingMode",

    "HORIZON_GROUPS",
    "RetrainingEligibility",
    "RetrainingError",
    "evaluate_candidate",
    "evaluate_retraining_eligibility",
    "train_candidate_model",

    "ChampionChallengerError",
    "PromotionDecision",
    "evaluate_promotion_gates",
]