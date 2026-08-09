"""Backend-independent model repository contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.mlops.config import (
    MLOpsSettings,
    ModelRegistryBackend,
)
from app.mlops.model_registry import (
    RegisteredModelResult,
    ResolvedProductionModel,
)


class ModelRepositoryError(RuntimeError):
    """Raised when model repository operations fail."""


class ModelRepositoryConfigurationError(
    ModelRepositoryError
):
    """Raised when the configured model backend is unsupported."""


class ModelRepository(ABC):
    """Backend-independent model registry repository."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Return backend identifier."""

    @abstractmethod
    def resolve_production_model(
        self,
        *,
        project_root: Path,
    ) -> ResolvedProductionModel:
        """Resolve and validate the production model."""

    @abstractmethod
    def register_candidate_model(
        self,
        *,
        candidate_directory: Path,
        metrics: dict[str, float],
    ) -> RegisteredModelResult:
        """Register one approved challenger."""


def create_model_repository(
    *,
    settings: MLOpsSettings,
) -> ModelRepository:
    """Create the configured model repository."""

    if (
        settings.model_registry_backend
        == ModelRegistryBackend.HOPSWORKS
    ):
        from app.mlops.hopsworks_model_repository import (
            HopsworksModelRepository,
        )

        return HopsworksModelRepository(
            settings=settings
        )

    raise ModelRepositoryConfigurationError(
        "No runtime ModelRepository implementation exists "
        f"for backend={settings.model_registry_backend.value!r}."
    )
