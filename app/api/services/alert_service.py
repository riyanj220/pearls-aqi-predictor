"""Alert episode response mapping and filtering."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from app.api.config import APISettings
from app.api.schemas.alerts import (
    ActiveAlertEpisodeResponse,
    ActiveAlertsResponse,
    AlertEpisodeCollectionResponse,
    AlertEpisodeResponse,
)
from app.api.schemas.common import (
    AlertLevel,
)
from app.api.services.artifact_repository import (
    ArtifactBundle,
)
from app.api.services.readiness_service import (
    freshness_response,
)


ALERT_LEVEL_RANK: dict[str, int] = {
    "NORMAL": 0,
    "ADVISORY": 1,
    "WARNING": 2,
    "SEVERE": 3,
    "EMERGENCY": 4,
}


class AlertService:
    """Map and filter saved alert episodes."""

    def __init__(
        self,
        *,
        settings: APISettings,
    ) -> None:
        self._settings = settings

    @staticmethod
    def _episode_forecast_rows(
        *,
        bundle: ArtifactBundle,
        start_horizon: int,
        end_horizon: int,
    ) -> pd.DataFrame:
        """Return hourly forecast rows within one episode."""

        return bundle.forecast_df.loc[
            bundle.forecast_df[
                "forecast_horizon_hours"
            ].between(
                start_horizon,
                end_horizon,
            )
        ]

    def build_episode(
        self,
        *,
        episode: dict[str, object],
        bundle: ArtifactBundle,
    ) -> AlertEpisodeResponse:
        """Convert one stored episode into the public schema."""

        start_horizon = int(
            episode["start_horizon"]
        )

        end_horizon = int(
            episode["end_horizon"]
        )

        episode_rows = (
            self._episode_forecast_rows(
                bundle=bundle,
                start_horizon=start_horizon,
                end_horizon=end_horizon,
            )
        )

        if episode_rows.empty:
            sensitive_groups_affected = False
            general_population_affected = False
            hazardous = False

            recommended_action = (
                "Follow the health guidance for "
                "the reported AQI category."
            )
        else:
            sensitive_groups_affected = bool(
                episode_rows[
                    "sensitive_groups_alert"
                ].any()
            )

            general_population_affected = bool(
                episode_rows[
                    "general_population_alert"
                ].any()
            )

            hazardous = bool(
                episode_rows[
                    "hazardous_alert"
                ].any()
            )

            peak_row = episode_rows.loc[
                episode_rows[
                    "alert_trigger_aqi"
                ].astype(float).idxmax()
            ]

            recommended_action = str(
                peak_row["recommended_action"]
            )

        return AlertEpisodeResponse(
            alert_episode_id=str(
                episode["alert_episode_id"]
            ),
            start_time_utc=pd.to_datetime(
                episode["episode_start_time"],
                utc=True,
            ),
            end_time_utc=pd.to_datetime(
                episode["episode_end_time"],
                utc=True,
            ),
            duration_hours=int(
                episode["duration_hours"]
            ),
            start_horizon=start_horizon,
            end_horizon=end_horizon,
            maximum_aqi=int(
                episode["peak_aqi"]
            ),
            maximum_category=str(
                episode["peak_category"]
            ),
            maximum_alert_level=str(
                episode["maximum_alert_level"]
            ),
            peak_time_utc=pd.to_datetime(
                episode["peak_time"],
                utc=True,
            ),
            alert_basis=str(
                episode["alert_basis"]
            ),
            sensitive_groups_affected=(
                sensitive_groups_affected
            ),
            general_population_affected=(
                general_population_affected
            ),
            hazardous=hazardous,
            summary_message=str(
                episode["episode_message"]
            ),
            recommended_action=(
                recommended_action
            ),
        )

    @staticmethod
    def _passes_filters(
        *,
        episode: AlertEpisodeResponse,
        minimum_level: AlertLevel | None,
        hazardous_only: bool,
    ) -> bool:
        """Return whether an episode satisfies alert filters."""

        if minimum_level is not None:
            episode_rank = ALERT_LEVEL_RANK[
                str(episode.maximum_alert_level)
            ]

            minimum_rank = ALERT_LEVEL_RANK[
                minimum_level.value
            ]

            if episode_rank < minimum_rank:
                return False

        if hazardous_only and not episode.hazardous:
            return False

        return True

    def build_collection(
        self,
        *,
        bundle: ArtifactBundle,
        minimum_level: AlertLevel | None = None,
        hazardous_only: bool = False,
    ) -> AlertEpisodeCollectionResponse:
        """Return filtered forecast alert episodes."""

        episodes = []

        for episode_payload in bundle.alert_episodes:
            episode = self.build_episode(
                episode=episode_payload,
                bundle=bundle,
            )

            if self._passes_filters(
                episode=episode,
                minimum_level=minimum_level,
                hazardous_only=hazardous_only,
            ):
                episodes.append(episode)

        return AlertEpisodeCollectionResponse(
            pipeline_run_id=(
                bundle.phase_6_run_id
            ),
            generated_at_utc=(
                bundle.generated_at_utc
            ),
            freshness=freshness_response(
                bundle=bundle,
                settings=self._settings,
            ),
            episode_count=len(episodes),
            episodes=episodes,
        )

    def build_active_collection(
        self,
        *,
        bundle: ArtifactBundle,
        include_upcoming: bool,
        minimum_level: AlertLevel | None = None,
        hazardous_only: bool = False,
    ) -> ActiveAlertsResponse:
        """Return filtered current and upcoming episodes."""

        now_utc = datetime.now(
            timezone.utc
        )

        classified_episodes = []

        for episode_payload in bundle.alert_episodes:
            episode = self.build_episode(
                episode=episode_payload,
                bundle=bundle,
            )

            if not self._passes_filters(
                episode=episode,
                minimum_level=minimum_level,
                hazardous_only=hazardous_only,
            ):
                continue

            currently_active = (
                episode.start_time_utc
                <= now_utc
                <= episode.end_time_utc
            )

            upcoming = (
                episode.start_time_utc
                > now_utc
            )

            if not (
                currently_active
                or (
                    include_upcoming
                    and upcoming
                )
            ):
                continue

            classified_episodes.append(
                ActiveAlertEpisodeResponse(
                    **episode.model_dump(),
                    currently_active=(
                        currently_active
                    ),
                    upcoming=upcoming,
                )
            )

        return ActiveAlertsResponse(
            pipeline_run_id=(
                bundle.phase_6_run_id
            ),
            checked_at_utc=now_utc,
            current_count=sum(
                episode.currently_active
                for episode
                in classified_episodes
            ),
            upcoming_count=sum(
                episode.upcoming
                for episode
                in classified_episodes
            ),
            episodes=classified_episodes,
        )