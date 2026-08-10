"""Hopsworks implementation of the model repository contract."""

from __future__ import annotations

from pathlib import Path

from app.mlops.client import (
    HopsworksConnectionError,
    connect_to_hopsworks,
)
from app.mlops.config import MLOpsSettings
from app.mlops.model_registry import (
    RegisteredModelResult,
    ResolvedProductionModel,
    register_candidate_model,
    resolve_production_model,
)
from app.mlops.model_repository import (
    ModelRepository,
    ModelRepositoryError,
)


class HopsworksModelRepository(
    ModelRepository
):
    """Model repository backed by Hopsworks Model Registry."""

    def __init__(
        self,
        *,
        settings: MLOpsSettings,
    ) -> None:
        self.settings = settings

        try:
            self.resources = (
                connect_to_hopsworks(
                    settings
                )
            )

        except HopsworksConnectionError as error:
            raise ModelRepositoryError(
                "Could not initialize Hopsworks "
                "model repository."
            ) from error

        if self.resources.model_registry is None:
            raise ModelRepositoryError(
                "Hopsworks Model Registry was not resolved."
            )

    @property
    def backend_name(self) -> str:
        """Return backend identifier."""

        return "hopsworks"

    def resolve_production_model(
        self,
        *,
        project_root: Path,
    ) -> ResolvedProductionModel:
        """Resolve configured Hopsworks production model."""

        try:
            return resolve_production_model(
                resources=self.resources,
                settings=self.settings,
                project_root=project_root,
            )

        except Exception as error:
            raise ModelRepositoryError(
                "Could not resolve the production model."
            ) from error

    def register_candidate_model(
        self,
        *,
        candidate_directory: Path,
        metrics: dict[str, float],
    ) -> RegisteredModelResult:
        """Register one approved challenger."""

        try:
            return register_candidate_model(
                resources=self.resources,
                settings=self.settings,
                candidate_directory=(
                    candidate_directory
                ),
                metrics=metrics,
            )

        except Exception as error:
            raise ModelRepositoryError(
                "Could not register challenger model."
            ) from error
