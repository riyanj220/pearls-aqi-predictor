import pandas as pd

from app.alerts.aqi_alerts import (
    add_aqi_alerts,
    build_alert_episodes,
)


def build_alert_input(
    rolling_aqi: int,
    category: str,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "target_time": [
                pd.Timestamp("2026-01-01 01:00:00+00:00")
            ],
            "forecast_horizon_hours": [1],
            "indicative_hourly_pm25_aqi": [rolling_aqi],
            "indicative_hourly_aqi_category": [category],
            "rolling_24h_pm25_is_complete": [True],
            "rolling_24h_pm25_aqi": [rolling_aqi],
            "rolling_24h_aqi_category": [category],
        }
    )


def test_unhealthy_category_creates_warning() -> None:
    result = add_aqi_alerts(
        build_alert_input(
            rolling_aqi=175,
            category="Unhealthy",
        )
    )

    row = result.iloc[0]

    assert row["alert_level"] == "WARNING"
    assert bool(row["alert_is_active"])
    assert bool(row["general_population_alert"])


def test_hourly_aqi_is_used_as_fallback() -> None:
    input_df = build_alert_input(
        rolling_aqi=120,
        category="Unhealthy for Sensitive Groups",
    )

    input_df["rolling_24h_pm25_is_complete"] = False
    input_df["rolling_24h_pm25_aqi"] = pd.NA
    input_df["rolling_24h_aqi_category"] = pd.NA

    result = add_aqi_alerts(input_df)

    row = result.iloc[0]

    assert row["alert_basis"] == "indicative_hourly_pm25_aqi"
    assert bool(row["alert_used_hourly_fallback"])
    assert row["alert_level"] == "ADVISORY"


def test_consecutive_active_hours_form_episodes() -> None:
    forecast_df = pd.DataFrame(
        {
            "target_time": pd.date_range(
                start="2026-01-01 00:00:00+00:00",
                periods=6,
                freq="h",
            ),
            "forecast_horizon_hours": range(1, 7),
            "alert_is_active": [
                False,
                True,
                True,
                False,
                True,
                True,
            ],
            "alert_rank": [0, 1, 2, 0, 3, 4],
            "alert_level": [
                "NORMAL",
                "ADVISORY",
                "WARNING",
                "NORMAL",
                "SEVERE",
                "EMERGENCY",
            ],
            "alert_trigger_aqi": [
                80,
                120,
                175,
                90,
                250,
                350,
            ],
            "alert_trigger_category": [
                "Moderate",
                "Unhealthy for Sensitive Groups",
                "Unhealthy",
                "Moderate",
                "Very Unhealthy",
                "Hazardous",
            ],
            "alert_basis": [
                "rolling_24h_pm25_aqi"
            ] * 6,
        }
    )

    episodes = build_alert_episodes(forecast_df)

    assert len(episodes) == 2
    assert episodes["duration_hours"].tolist() == [2, 2]
    assert episodes["peak_aqi"].tolist() == [175, 350]
    assert episodes["maximum_alert_level"].tolist() == [
        "WARNING",
        "EMERGENCY",
    ]