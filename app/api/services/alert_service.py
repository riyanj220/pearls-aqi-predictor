"""Alert episode response mapping."""

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
from app.api.services.artifact_repository import (
    ArtifactBundle,
)
from app.api.services.readiness_service import (
    freshness_response,
)


class AlertService:
    """Map saved alert episodes into public response schemas."""

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
        """Return hourly forecast rows belonging to an episode."""

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
        """Map one saved Phase 6 episode."""

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
                peak_row[
                    "recommended_action"
                ]
            )

        return AlertEpisodeResponse(
            alert_episode_id=str(
                episode[
                    "alert_episode_id"
                ]
            ),
            start_time_utc=pd.to_datetime(
                episode[
                    "episode_start_time"
                ],
                utc=True,
            ),
            end_time_utc=pd.to_datetime(
                episode[
                    "episode_end_time"
                ],
                utc=True,
            ),
            duration_hours=int(
                episode[
                    "duration_hours"
                ]
            ),
            start_horizon=start_horizon,
            end_horizon=end_horizon,
            maximum_aqi=int(
                episode["peak_aqi"]
            ),
            maximum_category=str(
                episode[
                    "peak_category"
                ]
            ),
            maximum_alert_level=str(
                episode[
                    "maximum_alert_level"
                ]
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
                episode[
                    "episode_message"
                ]
            ),
            recommended_action=(
                recommended_action
            ),
        )

    def build_collection(
        self,
        bundle: ArtifactBundle,
    ) -> AlertEpisodeCollectionResponse:
        """Return all saved alert episodes."""

        episodes = [
            self.build_episode(
                episode=episode,
                bundle=bundle,
            )
            for episode
            in bundle.alert_episodes
        ]

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
    ) -> ActiveAlertsResponse:
        """Classify episodes relative to the current UTC time."""

        now_utc = datetime.now(
            timezone.utc
        )

        classified_episodes = []

        for episode_payload in (
            bundle.alert_episodes
        ):
            episode = self.build_episode(
                episode=episode_payload,
                bundle=bundle,
            )

            currently_active = (
                episode.start_time_utc
                <= now_utc
                <= episode.end_time_utc
            )

            upcoming = (
                episode.start_time_utc
                > now_utc
            )

            if (
                currently_active
                or (
                    include_upcoming
                    and upcoming
                )
            ):
                classified_episodes.append(
                    ActiveAlertEpisodeResponse(
                        **episode.model_dump(),
                        currently_active=(
                            currently_active
                        ),
                        upcoming=upcoming,
                    )
                )

        current_count = sum(
            episode.currently_active
            for episode
            in classified_episodes
        )

        upcoming_count = sum(
            episode.upcoming
            for episode
            in classified_episodes
        )

        return ActiveAlertsResponse(
            pipeline_run_id=(
                bundle.phase_6_run_id
            ),
            checked_at_utc=now_utc,
            current_count=current_count,
            upcoming_count=upcoming_count,
            episodes=classified_episodes,
        )