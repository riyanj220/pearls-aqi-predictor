"""Open-Meteo client for live hourly weather forecasts."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.core.config import Settings, settings


class OpenMeteoClientError(RuntimeError):
    """Raised when forecast weather cannot be fetched or validated."""


OPEN_METEO_HOURLY_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "surface_pressure",
    "precipitation",
    "rain",
    "cloud_cover",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
)


def _create_retry_session(
    app_settings: Settings,
) -> requests.Session:
    """Create an HTTP session with bounded retries."""

    retry_policy = Retry(
        total=app_settings.request_retry_count,
        connect=app_settings.request_retry_count,
        read=app_settings.request_retry_count,
        status=app_settings.request_retry_count,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )

    adapter = HTTPAdapter(max_retries=retry_policy)

    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


def _validate_response_location(
    payload: dict[str, Any],
    *,
    app_settings: Settings,
) -> None:
    """Validate that the returned grid point is reasonably nearby."""

    returned_latitude = payload.get("latitude")
    returned_longitude = payload.get("longitude")

    if returned_latitude is None or returned_longitude is None:
        raise OpenMeteoClientError(
            "Open-Meteo response does not contain coordinates."
        )

    latitude_difference = abs(
        float(returned_latitude) - app_settings.latitude
    )

    longitude_difference = abs(
        float(returned_longitude) - app_settings.longitude
    )

    # Open-Meteo returns its selected forecast grid point, which may
    # differ slightly from the requested coordinates.
    coordinate_tolerance_degrees = 0.25

    if (
        latitude_difference > coordinate_tolerance_degrees
        or longitude_difference > coordinate_tolerance_degrees
    ):
        raise OpenMeteoClientError(
            "Open-Meteo returned an unexpectedly distant grid point. "
            f"Returned=({returned_latitude}, {returned_longitude}), "
            f"requested=({app_settings.latitude}, "
            f"{app_settings.longitude})."
        )


def _normalize_hourly_weather(
    payload: dict[str, Any],
) -> pd.DataFrame:
    """Normalize Open-Meteo hourly output to the training schema."""

    hourly_payload = payload.get("hourly")

    if not isinstance(hourly_payload, dict):
        raise OpenMeteoClientError(
            "Open-Meteo response does not contain hourly data."
        )

    hourly_times = hourly_payload.get("time")

    if not isinstance(hourly_times, list) or not hourly_times:
        raise OpenMeteoClientError(
            "Open-Meteo hourly response has no timestamps."
        )

    missing_variables = [
        variable
        for variable in OPEN_METEO_HOURLY_VARIABLES
        if variable not in hourly_payload
    ]

    if missing_variables:
        raise OpenMeteoClientError(
            "Open-Meteo response is missing requested variables: "
            f"{missing_variables}"
        )

    expected_row_count = len(hourly_times)

    inconsistent_lengths = {
        variable: len(hourly_payload[variable])
        for variable in OPEN_METEO_HOURLY_VARIABLES
        if not isinstance(hourly_payload[variable], list)
        or len(hourly_payload[variable]) != expected_row_count
    }

    if inconsistent_lengths:
        raise OpenMeteoClientError(
            "Open-Meteo hourly arrays have inconsistent lengths: "
            f"{inconsistent_lengths}"
        )

    weather_df = pd.DataFrame(
        {
            "datetime_utc": hourly_times,
            **{
                variable: hourly_payload[variable]
                for variable in OPEN_METEO_HOURLY_VARIABLES
            },
        }
    )

    weather_df["datetime_utc"] = pd.to_datetime(
        weather_df["datetime_utc"],
        utc=True,
        errors="coerce",
    )

    invalid_timestamp_count = int(
        weather_df["datetime_utc"].isna().sum()
    )

    if invalid_timestamp_count:
        raise OpenMeteoClientError(
            "Open-Meteo returned invalid timestamps: "
            f"{invalid_timestamp_count}"
        )

    for variable in OPEN_METEO_HOURLY_VARIABLES:
        weather_df[variable] = pd.to_numeric(
            weather_df[variable],
            errors="coerce",
        )

    return (
        weather_df
        .sort_values("datetime_utc")
        .reset_index(drop=True)
    )


def _validate_hourly_weather(
    weather_df: pd.DataFrame,
) -> None:
    """Validate normalized forecast-weather values."""

    if weather_df.empty:
        raise OpenMeteoClientError(
            "Normalized weather forecast is empty."
        )

    duplicate_count = int(
        weather_df["datetime_utc"].duplicated().sum()
    )

    if duplicate_count:
        raise OpenMeteoClientError(
            "Duplicate Open-Meteo timestamps were returned: "
            f"{duplicate_count}"
        )

    if not weather_df["datetime_utc"].is_monotonic_increasing:
        raise OpenMeteoClientError(
            "Open-Meteo timestamps are not chronological."
        )

    missing_value_counts = (
        weather_df[
            list(OPEN_METEO_HOURLY_VARIABLES)
        ]
        .isna()
        .sum()
    )

    missing_value_counts = missing_value_counts.loc[
        missing_value_counts > 0
    ]

    if not missing_value_counts.empty:
        raise OpenMeteoClientError(
            "Open-Meteo forecast contains missing values: "
            f"{missing_value_counts.to_dict()}"
        )

    numeric_values = weather_df[
        list(OPEN_METEO_HOURLY_VARIABLES)
    ].to_numpy(dtype=float)

    if not np.isfinite(numeric_values).all():
        raise OpenMeteoClientError(
            "Open-Meteo forecast contains infinite values."
        )

    expected_timeline = pd.date_range(
        start=weather_df["datetime_utc"].min(),
        end=weather_df["datetime_utc"].max(),
        freq="h",
        tz="UTC",
    )

    missing_timestamps = expected_timeline.difference(
        pd.DatetimeIndex(weather_df["datetime_utc"])
    )

    if len(missing_timestamps) > 0:
        raise OpenMeteoClientError(
            "Open-Meteo forecast is not a continuous hourly "
            f"timeline. Missing hours={len(missing_timestamps)}."
        )

    quality_violations = {
        "humidity_below_0": int(
            weather_df["relative_humidity_2m"].lt(0).sum()
        ),
        "humidity_above_100": int(
            weather_df["relative_humidity_2m"].gt(100).sum()
        ),
        "cloud_cover_below_0": int(
            weather_df["cloud_cover"].lt(0).sum()
        ),
        "cloud_cover_above_100": int(
            weather_df["cloud_cover"].gt(100).sum()
        ),
        "negative_precipitation": int(
            weather_df["precipitation"].lt(0).sum()
        ),
        "negative_rain": int(
            weather_df["rain"].lt(0).sum()
        ),
        "negative_wind_speed": int(
            weather_df["wind_speed_10m"].lt(0).sum()
        ),
        "negative_wind_gusts": int(
            weather_df["wind_gusts_10m"].lt(0).sum()
        ),
        "wind_direction_below_0": int(
            weather_df["wind_direction_10m"].lt(0).sum()
        ),
        "wind_direction_above_360": int(
            weather_df["wind_direction_10m"].gt(360).sum()
        ),
        "non_positive_pressure": int(
            weather_df["surface_pressure"].le(0).sum()
        ),
    }

    if sum(quality_violations.values()) > 0:
        raise OpenMeteoClientError(
            "Open-Meteo forecast failed physical-range checks: "
            f"{quality_violations}"
        )


class OpenMeteoClient:
    """Fetch normalized hourly weather from Open-Meteo."""

    def __init__(
        self,
        app_settings: Settings = settings,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = app_settings
        self.session = session or _create_retry_session(
            app_settings
        )

    def fetch_hourly_weather(self) -> pd.DataFrame:
        """
        Fetch recent and forecast hourly weather.

        The wider returned timeline supports later selection of a
        slightly delayed PM2.5 reference hour while preserving all
        72 required target-weather hours.
        """

        params = {
            "latitude": self.settings.latitude,
            "longitude": self.settings.longitude,
            "hourly": ",".join(
                OPEN_METEO_HOURLY_VARIABLES
            ),
            "timezone": self.settings.timezone,
            "past_hours": self.settings.weather_past_hours,
            "forecast_hours": (
                self.settings.weather_forecast_hours
            ),
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
        }

        try:
            response = self.session.get(
                self.settings.open_meteo_forecast_url,
                params=params,
                timeout=self.settings.request_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise OpenMeteoClientError(
                "Open-Meteo request failed before a valid "
                "response was received."
            ) from exc

        if response.status_code == 429:
            raise OpenMeteoClientError(
                "Open-Meteo rate limit was exceeded."
            )

        if not response.ok:
            response_preview = response.text[:500]

            raise OpenMeteoClientError(
                "Open-Meteo returned an unsuccessful response. "
                f"status={response.status_code}, "
                f"body={response_preview!r}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise OpenMeteoClientError(
                "Open-Meteo returned invalid JSON."
            ) from exc

        if payload.get("error") is True:
            raise OpenMeteoClientError(
                "Open-Meteo reported an API error: "
                f"{payload.get('reason', 'unknown reason')}"
            )

        _validate_response_location(
            payload,
            app_settings=self.settings,
        )

        weather_df = _normalize_hourly_weather(payload)

        _validate_hourly_weather(weather_df)

        return weather_df