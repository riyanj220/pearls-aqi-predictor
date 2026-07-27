"""AQI health guidance, alert assignment, and episode grouping."""

from __future__ import annotations

import numpy as np
import pandas as pd


class AQIAlertError(ValueError):
    """Raised when AQI alerts cannot be generated safely."""


CATEGORY_ALERT_CONFIG: dict[str, dict[str, object]] = {
    "Good": {
        "alert_level": "NORMAL",
        "alert_rank": 0,
        "alert_is_active": False,
        "sensitive_groups_alert": False,
        "general_population_alert": False,
        "hazardous_alert": False,
        "health_message": (
            "Air quality is satisfactory and poses little "
            "or no expected health risk."
        ),
        "recommended_action": (
            "Normal outdoor activities may continue."
        ),
    },
    "Moderate": {
        "alert_level": "NORMAL",
        "alert_rank": 0,
        "alert_is_active": False,
        "sensitive_groups_alert": False,
        "general_population_alert": False,
        "hazardous_alert": False,
        "health_message": (
            "Air quality is generally acceptable, although "
            "unusually sensitive people may be affected."
        ),
        "recommended_action": (
            "Most people may continue normal activities. "
            "Unusually sensitive people should monitor symptoms."
        ),
    },
    "Unhealthy for Sensitive Groups": {
        "alert_level": "ADVISORY",
        "alert_rank": 1,
        "alert_is_active": True,
        "sensitive_groups_alert": True,
        "general_population_alert": False,
        "hazardous_alert": False,
        "health_message": (
            "Sensitive groups may experience health effects."
        ),
        "recommended_action": (
            "Sensitive groups should reduce prolonged or heavy "
            "outdoor activity."
        ),
    },
    "Unhealthy": {
        "alert_level": "WARNING",
        "alert_rank": 2,
        "alert_is_active": True,
        "sensitive_groups_alert": True,
        "general_population_alert": True,
        "hazardous_alert": False,
        "health_message": (
            "Some members of the general public may experience "
            "health effects, with greater risk for sensitive groups."
        ),
        "recommended_action": (
            "Reduce prolonged or heavy outdoor activity. Sensitive "
            "groups should avoid strenuous outdoor activity."
        ),
    },
    "Very Unhealthy": {
        "alert_level": "SEVERE",
        "alert_rank": 3,
        "alert_is_active": True,
        "sensitive_groups_alert": True,
        "general_population_alert": True,
        "hazardous_alert": False,
        "health_message": (
            "The risk of health effects is increased for everyone."
        ),
        "recommended_action": (
            "Avoid prolonged or strenuous outdoor activity and "
            "reduce exposure."
        ),
    },
    "Hazardous": {
        "alert_level": "EMERGENCY",
        "alert_rank": 4,
        "alert_is_active": True,
        "sensitive_groups_alert": True,
        "general_population_alert": True,
        "hazardous_alert": True,
        "health_message": (
            "Emergency health conditions are possible and everyone "
            "is more likely to be affected."
        ),
        "recommended_action": (
            "Avoid outdoor physical activity and minimize exposure "
            "to outdoor air."
        ),
    },
    "Beyond the AQI": {
        "alert_level": "EMERGENCY",
        "alert_rank": 4,
        "alert_is_active": True,
        "sensitive_groups_alert": True,
        "general_population_alert": True,
        "hazardous_alert": True,
        "health_message": (
            "Pollution exceeds the standard AQI reporting scale and "
            "represents emergency conditions."
        ),
        "recommended_action": (
            "Avoid outdoor exposure and follow instructions from "
            "local health and emergency authorities."
        ),
    },
}


ALERT_EPISODE_COLUMNS = [
    "alert_episode_id",
    "episode_start_time",
    "episode_end_time",
    "duration_hours",
    "start_horizon",
    "end_horizon",
    "peak_aqi",
    "peak_time",
    "maximum_alert_level",
    "maximum_alert_rank",
    "peak_category",
    "alert_basis",
    "episode_message",
]


def _validate_enriched_forecast(
    forecast_df: pd.DataFrame,
) -> pd.DataFrame:
    """Validate and normalize the AQI-enriched forecast."""

    required_columns = {
        "target_time",
        "forecast_horizon_hours",
        "indicative_hourly_pm25_aqi",
        "indicative_hourly_aqi_category",
        "rolling_24h_pm25_is_complete",
        "rolling_24h_pm25_aqi",
        "rolling_24h_aqi_category",
    }

    missing_columns = sorted(
        required_columns.difference(forecast_df.columns)
    )

    if missing_columns:
        raise AQIAlertError(
            "AQI-enriched forecast is missing required columns: "
            f"{missing_columns}"
        )

    validated_df = forecast_df.copy()

    validated_df["target_time"] = pd.to_datetime(
        validated_df["target_time"],
        utc=True,
        errors="coerce",
    )

    validated_df["forecast_horizon_hours"] = pd.to_numeric(
        validated_df["forecast_horizon_hours"],
        errors="coerce",
    )

    if validated_df["target_time"].isna().any():
        raise AQIAlertError(
            "Forecast contains invalid target timestamps."
        )

    if validated_df["forecast_horizon_hours"].isna().any():
        raise AQIAlertError(
            "Forecast contains invalid horizon values."
        )

    validated_df = (
        validated_df
        .sort_values("forecast_horizon_hours")
        .reset_index(drop=True)
    )

    if validated_df["target_time"].duplicated().any():
        raise AQIAlertError(
            "Forecast contains duplicate target timestamps."
        )

    return validated_df


def add_aqi_alerts(
    forecast_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Add health guidance and alert fields to an AQI forecast.

    Complete rolling 24-hour AQI is preferred. Indicative hourly AQI
    is used only when rolling AQI is unavailable.
    """

    alerted_df = _validate_enriched_forecast(
        forecast_df
    )

    rolling_available = (
        alerted_df["rolling_24h_pm25_is_complete"]
        .fillna(False)
        .astype(bool)
        & alerted_df["rolling_24h_pm25_aqi"].notna()
        & alerted_df["rolling_24h_aqi_category"].notna()
    )

    alerted_df["alert_basis"] = np.where(
        rolling_available,
        "rolling_24h_pm25_aqi",
        "indicative_hourly_pm25_aqi",
    )

    alerted_df["alert_used_hourly_fallback"] = (
        ~rolling_available
    )

    alerted_df["alert_trigger_aqi"] = (
        alerted_df["rolling_24h_pm25_aqi"]
        .where(
            rolling_available,
            alerted_df["indicative_hourly_pm25_aqi"],
        )
        .astype("Int64")
    )

    alerted_df["alert_trigger_category"] = (
        alerted_df["rolling_24h_aqi_category"]
        .where(
            rolling_available,
            alerted_df[
                "indicative_hourly_aqi_category"
            ],
        )
    )

    unknown_categories = sorted(
        set(
            alerted_df[
                "alert_trigger_category"
            ].dropna()
        ).difference(CATEGORY_ALERT_CONFIG)
    )

    if unknown_categories:
        raise AQIAlertError(
            "No alert configuration exists for categories: "
            f"{unknown_categories}"
        )

    if alerted_df["alert_trigger_aqi"].isna().any():
        raise AQIAlertError(
            "Some rows have no usable AQI alert value."
        )

    if alerted_df["alert_trigger_category"].isna().any():
        raise AQIAlertError(
            "Some rows have no usable AQI category."
        )

    def config_value(
        category: str,
        key: str,
    ) -> object:
        return CATEGORY_ALERT_CONFIG[
            str(category)
        ][key]

    alerted_df["alert_level"] = (
        alerted_df["alert_trigger_category"]
        .map(
            lambda category: config_value(
                category,
                "alert_level",
            )
        )
        .astype("string")
    )

    alerted_df["alert_rank"] = (
        alerted_df["alert_trigger_category"]
        .map(
            lambda category: config_value(
                category,
                "alert_rank",
            )
        )
        .astype("int64")
    )

    boolean_config_columns = [
        "alert_is_active",
        "sensitive_groups_alert",
        "general_population_alert",
        "hazardous_alert",
    ]

    for column in boolean_config_columns:
        alerted_df[column] = (
            alerted_df["alert_trigger_category"]
            .map(
                lambda category: config_value(
                    category,
                    column,
                )
            )
            .astype(bool)
        )

    alerted_df["health_message"] = (
        alerted_df["alert_trigger_category"]
        .map(
            lambda category: config_value(
                category,
                "health_message",
            )
        )
        .astype("string")
    )

    alerted_df["recommended_action"] = (
        alerted_df["alert_trigger_category"]
        .map(
            lambda category: config_value(
                category,
                "recommended_action",
            )
        )
        .astype("string")
    )

    alerted_df["alert_message"] = (
        alerted_df["alert_level"]
        + ": "
        + alerted_df["alert_trigger_category"]
        + " AQI "
        + alerted_df["alert_trigger_aqi"].astype("string")
        + ". "
        + alerted_df["recommended_action"]
    )

    return alerted_df


def build_alert_episodes(
    alerted_forecast_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Group consecutive active alert hours into alert episodes.

    An episode continues while active alert rows remain exactly one
    hour apart. Changes in severity remain part of the same episode.
    """

    required_columns = {
        "target_time",
        "forecast_horizon_hours",
        "alert_is_active",
        "alert_rank",
        "alert_level",
        "alert_trigger_aqi",
        "alert_trigger_category",
        "alert_basis",
    }

    missing_columns = sorted(
        required_columns.difference(
            alerted_forecast_df.columns
        )
    )

    if missing_columns:
        raise AQIAlertError(
            "Alerted forecast is missing columns: "
            f"{missing_columns}"
        )

    active_df = (
        alerted_forecast_df.loc[
            alerted_forecast_df[
                "alert_is_active"
            ].astype(bool)
        ]
        .copy()
        .sort_values("target_time")
        .reset_index(drop=True)
    )

    if active_df.empty:
        return pd.DataFrame(
            columns=ALERT_EPISODE_COLUMNS
        )

    time_difference = (
        active_df["target_time"].diff()
    )

    new_episode = (
        time_difference.isna()
        | time_difference.ne(
            pd.Timedelta(hours=1)
        )
    )

    active_df["_episode_number"] = (
        new_episode.cumsum()
    )

    episode_records: list[dict[str, object]] = []

    for episode_number, episode_df in (
        active_df.groupby(
            "_episode_number",
            sort=True,
        )
    ):
        peak_row_index = (
            episode_df["alert_trigger_aqi"]
            .astype(float)
            .idxmax()
        )

        peak_row = episode_df.loc[
            peak_row_index
        ]

        maximum_rank = int(
            episode_df["alert_rank"].max()
        )

        maximum_rank_rows = (
            episode_df.loc[
                episode_df["alert_rank"].eq(
                    maximum_rank
                )
            ]
        )

        maximum_level = str(
            maximum_rank_rows[
                "alert_level"
            ].iloc[0]
        )

        episode_start = (
            episode_df["target_time"].min()
        )

        episode_end = (
            episode_df["target_time"].max()
        )

        duration_hours = int(
            (
                episode_end
                - episode_start
            ).total_seconds()
            / 3_600
        ) + 1

        unique_bases = (
            episode_df["alert_basis"]
            .dropna()
            .unique()
            .tolist()
        )

        episode_records.append(
            {
                "alert_episode_id": (
                    f"alert_episode_{int(episode_number):03d}"
                ),
                "episode_start_time": episode_start,
                "episode_end_time": episode_end,
                "duration_hours": duration_hours,
                "start_horizon": int(
                    episode_df[
                        "forecast_horizon_hours"
                    ].min()
                ),
                "end_horizon": int(
                    episode_df[
                        "forecast_horizon_hours"
                    ].max()
                ),
                "peak_aqi": int(
                    peak_row["alert_trigger_aqi"]
                ),
                "peak_time": peak_row[
                    "target_time"
                ],
                "maximum_alert_level": (
                    maximum_level
                ),
                "maximum_alert_rank": (
                    maximum_rank
                ),
                "peak_category": str(
                    peak_row[
                        "alert_trigger_category"
                    ]
                ),
                "alert_basis": (
                    unique_bases[0]
                    if len(unique_bases) == 1
                    else "mixed"
                ),
                "episode_message": (
                    f"{maximum_level} AQI episode from "
                    f"{episode_start} to {episode_end}; "
                    f"peak AQI {int(peak_row['alert_trigger_aqi'])} "
                    f"({peak_row['alert_trigger_category']})."
                ),
            }
        )

    return pd.DataFrame(
        episode_records,
        columns=ALERT_EPISODE_COLUMNS,
    )