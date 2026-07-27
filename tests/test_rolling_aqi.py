import pandas as pd

from app.aqi.forecast_enrichment import (
    enrich_forecast_with_aqi,
)


def build_observed_pm25() -> pd.DataFrame:
    timestamps = pd.date_range(
        start="2026-01-01 00:00:00+00:00",
        periods=25,
        freq="h",
    )

    return pd.DataFrame(
        {
            "datetime_utc": timestamps,
            "pm25_ug_m3": [10.0] * 25,
        }
    )


def build_forecast() -> pd.DataFrame:
    reference_time = pd.Timestamp(
        "2026-01-02 00:00:00+00:00"
    )

    return pd.DataFrame(
        {
            "target_time": pd.date_range(
                start=reference_time + pd.Timedelta(hours=1),
                periods=72,
                freq="h",
            ),
            "forecast_horizon_hours": range(1, 73),
            "predicted_pm25_ug_m3": [20.0] * 72,
        }
    )


def test_complete_rolling_windows_are_generated() -> None:
    result = enrich_forecast_with_aqi(
        forecast_df=build_forecast(),
        observed_pm25_df=build_observed_pm25(),
    )

    assert len(result) == 72
    assert result["rolling_24h_pm25_is_complete"].all()
    assert result["rolling_24h_missing_hours"].eq(0).all()

    total_hours = (
        result["rolling_observed_hour_count"]
        + result["rolling_predicted_hour_count"]
    )

    assert total_hours.eq(24).all()


def test_first_window_contains_observed_and_predicted_hours() -> None:
    result = enrich_forecast_with_aqi(
        forecast_df=build_forecast(),
        observed_pm25_df=build_observed_pm25(),
    )

    first_row = result.iloc[0]

    assert first_row["rolling_observed_hour_count"] == 23
    assert first_row["rolling_predicted_hour_count"] == 1


def test_missing_history_hour_marks_window_incomplete() -> None:
    observed_df = build_observed_pm25().drop(index=10)

    result = enrich_forecast_with_aqi(
        forecast_df=build_forecast(),
        observed_pm25_df=observed_df,
    )

    assert not result.iloc[0]["rolling_24h_pm25_is_complete"]
    assert result.iloc[0]["rolling_24h_missing_hours"] == 1
    assert pd.isna(result.iloc[0]["rolling_24h_pm25_aqi"])