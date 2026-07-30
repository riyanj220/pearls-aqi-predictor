"""Hopsworks feature-view management."""

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


class FeatureViewError(RuntimeError):
    """Raised when a feature view cannot be resolved."""


@dataclass(frozen=True)
class ResolvedFeatureView:
    """Resolved feature-view metadata."""

    feature_view: Any | None
    name: str
    version: int
    dry_run: bool
    feature_count: int

    def safe_summary(self) -> dict[str, object]:
        """Return JSON-safe feature-view metadata."""

        return {
            "name": self.name,
            "version": self.version,
            "dry_run": self.dry_run,
            "resolved": self.feature_view is not None,
            "feature_count": self.feature_count,
        }


def create_or_get_reference_feature_view(
    *,
    resources: HopsworksResources,
    settings: MLOpsSettings,
    engineered_feature_group: Any,
    engineered_contract: FeatureGroupContract,
) -> ResolvedFeatureView:
    """Create or resolve the reference-time feature view."""

    selected_columns = (
        engineered_contract.feature_names
    )

    if settings.mlops_dry_run:
        return ResolvedFeatureView(
            feature_view=None,
            name=settings.hopsworks_feature_view_name,
            version=(
                settings.hopsworks_feature_view_version
            ),
            dry_run=True,
            feature_count=len(selected_columns),
        )

    if resources.feature_store is None:
        raise FeatureViewError(
            "Hopsworks Feature Store is unavailable."
        )

    try:
        query = engineered_feature_group.select(
            selected_columns
        )

        feature_view = (
            resources.feature_store
            .get_or_create_feature_view(
                name=(
                    settings
                    .hopsworks_feature_view_name
                ),
                version=(
                    settings
                    .hopsworks_feature_view_version
                ),
                description=(
                    "Reference-time PM2.5, current-weather "
                    "and calendar features for the "
                    "72-hour PM2.5 forecasting model."
                ),
                query=query,
            )
        )

    except Exception as error:
        raise FeatureViewError(
            "Could not create or resolve the "
            "reference-time feature view."
        ) from error

    return ResolvedFeatureView(
        feature_view=feature_view,
        name=settings.hopsworks_feature_view_name,
        version=(
            settings.hopsworks_feature_view_version
        ),
        dry_run=False,
        feature_count=len(selected_columns),
    )