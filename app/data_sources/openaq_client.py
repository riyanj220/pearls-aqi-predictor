"""OpenAQ client for recent hourly PM2.5 observations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.core.config import Settings, settings


class OpenAQClientError(RuntimeError):
    """Raised when OpenAQ data cannot be fetched or validated."""


def _create_retry_session(
    app_settings: Settings,
) -> requests.Session:
    """Create an HTTP session with limited retry behavior."""

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

    adapter = HTTPAdapter(
        max_retries=retry_policy
    )

    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


def _utc_isoformat(
    value: datetime,
) -> str:
    """Return an ISO-8601 UTC datetime accepted by OpenAQ."""

    if value.tzinfo is None:
        raise OpenAQClientError(
            "OpenAQ request datetimes must be timezone-aware."
        )

    utc_value = value.astimezone(timezone.utc)

    return utc_value.isoformat().replace(
        "+00:00",
        "Z",
    )


def _extract_nested_value(
    payload: dict[str, Any],
    *keys: str,
) -> Any:
    """Safely extract a nested dictionary value."""

    current_value: Any = payload

    for key in keys:
        if not isinstance(current_value, dict):
            return None

        current_value = current_value.get(key)

    return current_value


def _extract_hourly_pm25_value(
    record: dict[str, Any],
) -> float | None:
    """
    Extract the hourly PM2.5 value from an OpenAQ result.

    The endpoint may expose the aggregate directly as `value` or
    inside the summary as `avg`.
    """

    candidate_value = record.get("value")

    if candidate_value is None:
        candidate_value = _extract_nested_value(
            record,
            "summary",
            "avg",
        )

    if candidate_value is None:
        return None

    try:
        return float(candidate_value)
    except (TypeError, ValueError):
        return None


def _normalize_hourly_results(
    results: list[dict[str, Any]],
    *,
    sensor_id: int,
) -> pd.DataFrame:
    """Normalize OpenAQ hourly results to the project schema."""

    normalized_records: list[dict[str, Any]] = []

    for record in results:
        parameter = record.get("parameter") or {}

        datetime_from_utc = _extract_nested_value(
            record,
            "period",
            "datetimeFrom",
            "utc",
        )

        if datetime_from_utc is None:
            datetime_from_utc = _extract_nested_value(
                record,
                "datetimeFrom",
                "utc",
            )

        datetime_to_utc = _extract_nested_value(
            record,
            "period",
            "datetimeTo",
            "utc",
        )

        if datetime_to_utc is None:
            datetime_to_utc = _extract_nested_value(
                record,
                "datetimeTo",
                "utc",
            )

        normalized_records.append(
            {
                "datetime_utc": datetime_from_utc,
                "datetime_to_utc": datetime_to_utc,
                "pm25_ug_m3_raw": (
                    _extract_hourly_pm25_value(record)
                ),
                "parameter": parameter.get("name"),
                "units": parameter.get("units"),
                "sensor_id": sensor_id,
                "has_flags": bool(
                    _extract_nested_value(
                        record,
                        "flagInfo",
                        "hasFlags",
                    )
                    or False
                ),
            }
        )

    return pd.DataFrame(normalized_records)


def _clean_hourly_pm25(
    dataframe: pd.DataFrame,
    *,
    app_settings: Settings,
) -> pd.DataFrame:
    """
    Apply the validated PM2.5 cleaning rules.

    Zero and negative values are converted to missing values.
    Plausible high values are retained.
    No interpolation is performed.
    """

    required_columns = {
        "datetime_utc",
        "pm25_ug_m3_raw",
        "parameter",
        "units",
        "sensor_id",
        "has_flags",
    }

    missing_columns = sorted(
        required_columns.difference(dataframe.columns)
    )

    if missing_columns:
        raise OpenAQClientError(
            "Normalized OpenAQ data is missing columns: "
            f"{missing_columns}"
        )

    cleaned_df = dataframe.copy()

    cleaned_df["datetime_utc"] = pd.to_datetime(
        cleaned_df["datetime_utc"],
        utc=True,
        errors="coerce",
    )

    cleaned_df["datetime_to_utc"] = pd.to_datetime(
        cleaned_df["datetime_to_utc"],
        utc=True,
        errors="coerce",
    )

    cleaned_df["pm25_ug_m3_raw"] = pd.to_numeric(
        cleaned_df["pm25_ug_m3_raw"],
        errors="coerce",
    )

    invalid_timestamp_count = int(
        cleaned_df["datetime_utc"].isna().sum()
    )

    if invalid_timestamp_count:
        raise OpenAQClientError(
            "OpenAQ returned invalid hourly timestamps: "
            f"{invalid_timestamp_count}"
        )

    unexpected_parameters = sorted(
        cleaned_df.loc[
            cleaned_df["parameter"].notna()
            & ~cleaned_df["parameter"].eq(
                app_settings.pollutant
            ),
            "parameter",
        ]
        .astype(str)
        .unique()
        .tolist()
    )

    if unexpected_parameters:
        raise OpenAQClientError(
            "Unexpected pollutant parameters returned: "
            f"{unexpected_parameters}"
        )

    unexpected_sensor_ids = sorted(
        cleaned_df.loc[
            ~cleaned_df["sensor_id"].eq(
                app_settings.openaq_sensor_id
            ),
            "sensor_id",
        ]
        .unique()
        .tolist()
    )

    if unexpected_sensor_ids:
        raise OpenAQClientError(
            "Unexpected OpenAQ sensor IDs returned: "
            f"{unexpected_sensor_ids}"
        )

    cleaned_df["pm25_zero_flag"] = (
        cleaned_df["pm25_ug_m3_raw"].eq(0)
    )

    cleaned_df["pm25_negative_flag"] = (
        cleaned_df["pm25_ug_m3_raw"].lt(0)
    )

    cleaned_df["pm25_ug_m3"] = (
        cleaned_df["pm25_ug_m3_raw"].mask(
            cleaned_df[
                [
                    "pm25_zero_flag",
                    "pm25_negative_flag",
                ]
            ].any(axis=1)
        )
    )

    cleaned_df = (
        cleaned_df
        .sort_values("datetime_utc")
        .drop_duplicates(
            subset=["datetime_utc"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    if not cleaned_df[
        "datetime_utc"
    ].is_monotonic_increasing:
        raise OpenAQClientError(
            "Cleaned OpenAQ timestamps are not chronological."
        )

    if cleaned_df["datetime_utc"].duplicated().any():
        raise OpenAQClientError(
            "Duplicate OpenAQ hourly timestamps remain."
        )

    if cleaned_df["pm25_ug_m3"].eq(0).any():
        raise OpenAQClientError(
            "Exact zero PM2.5 values remain after cleaning."
        )

    if cleaned_df["pm25_ug_m3"].lt(0).any():
        raise OpenAQClientError(
            "Negative PM2.5 values remain after cleaning."
        )

    return cleaned_df[
        [
            "datetime_utc",
            "datetime_to_utc",
            "pm25_ug_m3",
            "pm25_ug_m3_raw",
            "pm25_zero_flag",
            "pm25_negative_flag",
            "has_flags",
            "parameter",
            "units",
            "sensor_id",
        ]
    ]


class OpenAQClient:
    """Fetch recent hourly PM2.5 observations from OpenAQ."""

    def __init__(
        self,
        app_settings: Settings = settings,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = app_settings
        self.session = session or _create_retry_session(
            app_settings
        )

    @property
    def hourly_sensor_url(self) -> str:
        """Return the precomputed hourly sensor endpoint."""

        return (
            f"{self.settings.openaq_base_url}"
            f"/sensors/"
            f"{self.settings.openaq_sensor_id}"
            f"/hours"
        )

    def fetch_recent_hourly_pm25(
        self,
        *,
        end_time: datetime | None = None,
        lookback_hours: int | None = None,
    ) -> pd.DataFrame:
        """
        Fetch and clean recent hourly PM2.5 observations.

        No missing timestamps or PM2.5 values are interpolated.
        """

        api_key = self.settings.require_openaq_api_key()

        request_end_time = end_time or datetime.now(
            timezone.utc
        )

        if request_end_time.tzinfo is None:
            raise OpenAQClientError(
                "end_time must be timezone-aware."
            )

        requested_lookback = (
            lookback_hours
            or self.settings.requested_pm25_lookback_hours
        )

        if requested_lookback <= 0:
            raise OpenAQClientError(
                "lookback_hours must be greater than zero."
            )

        request_start_time = (
            request_end_time
            - timedelta(hours=requested_lookback)
        )

        headers = {
            "X-API-Key": api_key,
            "Accept": "application/json",
        }

        # The configured lookback is small, but a larger limit keeps
        # this method safe if the lookback is increased later.
        params = {
            "datetime_from": _utc_isoformat(
                request_start_time
            ),
            "datetime_to": _utc_isoformat(
                request_end_time
            ),
            "limit": min(
                max(requested_lookback + 24, 100),
                1_000,
            ),
            "page": 1,
        }

        try:
            response = self.session.get(
                self.hourly_sensor_url,
                headers=headers,
                params=params,
                timeout=self.settings.request_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise OpenAQClientError(
                "OpenAQ request failed before receiving "
                "a valid response."
            ) from exc

        if response.status_code == 401:
            raise OpenAQClientError(
                "OpenAQ rejected the API key."
            )

        if response.status_code == 429:
            raise OpenAQClientError(
                "OpenAQ rate limit was exceeded."
            )

        if not response.ok:
            response_preview = response.text[:500]

            raise OpenAQClientError(
                "OpenAQ returned an unsuccessful response. "
                f"status={response.status_code}, "
                f"body={response_preview!r}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise OpenAQClientError(
                "OpenAQ returned invalid JSON."
            ) from exc

        results = payload.get("results")

        if not isinstance(results, list):
            raise OpenAQClientError(
                "OpenAQ response does not contain a "
                "valid results list."
            )

        if not results:
            raise OpenAQClientError(
                "OpenAQ returned no hourly PM2.5 results "
                "for the requested window."
            )

        normalized_df = _normalize_hourly_results(
            results,
            sensor_id=self.settings.openaq_sensor_id,
        )

        return _clean_hourly_pm25(
            normalized_df,
            app_settings=self.settings,
        )