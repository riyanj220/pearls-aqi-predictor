"""Reusable FastAPI client for the Streamlit dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from dashboard.config import (
    DashboardSettings,
    get_dashboard_settings,
)


class DashboardAPIError(RuntimeError):
    """Base exception for dashboard API failures."""


class DashboardAPIConnectionError(
    DashboardAPIError
):
    """Raised when FastAPI cannot be reached."""


class DashboardAPITimeoutError(
    DashboardAPIError
):
    """Raised when a FastAPI request times out."""


class DashboardAPIResponseError(
    DashboardAPIError
):
    """Raised for a structured non-success API response."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)

        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        self.request_id = request_id


class DashboardAPIContractError(
    DashboardAPIError
):
    """Raised when an API response violates the expected shape."""


@dataclass(frozen=True)
class APIResult:
    """One successful API response."""

    payload: dict[str, Any]
    request_id: str | None


class FastAPIClient:
    """Central HTTP client for all dashboard API calls."""

    def __init__(
        self,
        settings: DashboardSettings | None = None,
    ) -> None:
        self.settings = (
            settings
            or get_dashboard_settings()
        )

        self._session = requests.Session()

        retry_strategy = Retry(
            total=2,
            connect=2,
            read=1,
            backoff_factor=0.3,
            status_forcelist=(
                502,
                503,
                504,
            ),
            allowed_methods=frozenset(
                {"GET"}
            ),
            raise_on_status=False,
        )

        adapter = HTTPAdapter(
            max_retries=retry_strategy
        )

        self._session.mount(
            "http://",
            adapter,
        )

        self._session.mount(
            "https://",
            adapter,
        )

    def _url(self, path: str) -> str:
        """Build a complete API URL."""

        normalized_path = (
            "/" + path.lstrip("/")
        )

        return (
            f"{self.settings.fastapi_base_url}"
            f"{normalized_path}"
        )

    def _get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> APIResult:
        """Execute one safe GET request."""

        url = self._url(path)

        try:
            response = self._session.get(
                url,
                params=params,
                timeout=(
                    self.settings
                    .dashboard_request_timeout_seconds
                ),
                headers={
                    "Accept": "application/json",
                },
            )
        except requests.Timeout as exc:
            raise DashboardAPITimeoutError(
                f"FastAPI request timed out: {url}"
            ) from exc
        except requests.ConnectionError as exc:
            raise DashboardAPIConnectionError(
                f"Could not connect to FastAPI: {url}"
            ) from exc
        except requests.RequestException as exc:
            raise DashboardAPIConnectionError(
                f"FastAPI request failed: {url}"
            ) from exc

        try:
            payload = response.json()
        except requests.JSONDecodeError as exc:
            raise DashboardAPIContractError(
                "FastAPI returned invalid JSON."
            ) from exc

        if not isinstance(payload, dict):
            raise DashboardAPIContractError(
                "FastAPI response must be a JSON object."
            )

        request_id = (
            response.headers.get(
                "X-Request-ID"
            )
        )

        if not response.ok:
            error = payload.get(
                "error",
                {},
            )

            if isinstance(error, dict):
                code = str(
                    error.get(
                        "code",
                        "API_REQUEST_FAILED",
                    )
                )

                message = str(
                    error.get(
                        "message",
                        "The API request failed.",
                    )
                )

                details = error.get(
                    "details",
                    {},
                )

                if not isinstance(
                    details,
                    dict,
                ):
                    details = {}

                request_id = (
                    error.get("request_id")
                    or request_id
                )
            else:
                code = "API_REQUEST_FAILED"
                message = "The API request failed."
                details = {}

            raise DashboardAPIResponseError(
                status_code=(
                    response.status_code
                ),
                code=code,
                message=message,
                details=details,
                request_id=(
                    str(request_id)
                    if request_id
                    else None
                ),
            )

        return APIResult(
            payload=payload,
            request_id=request_id,
        )

    def get_liveness(self) -> dict[str, Any]:
        return self._get(
            "/health/live"
        ).payload

    def get_readiness(self) -> dict[str, Any]:
        return self._get(
            "/health/ready"
        ).payload

    def get_forecast(self) -> dict[str, Any]:
        return self._get(
            "/forecast"
        ).payload

    def get_hourly_forecast(
        self,
        *,
        minimum_horizon: int | None = None,
        maximum_horizon: int | None = None,
        category: str | None = None,
        alert_level: str | None = None,
        alerts_only: bool = False,
    ) -> dict[str, Any]:
        params = {
            "minimum_horizon": minimum_horizon,
            "maximum_horizon": maximum_horizon,
            "category": category,
            "alert_level": alert_level,
            "alerts_only": alerts_only,
        }

        clean_params = {
            key: value
            for key, value
            in params.items()
            if value is not None
        }

        return self._get(
            "/forecast/hourly",
            params=clean_params,
        ).payload

    def get_summary(self) -> dict[str, Any]:
        return self._get(
            "/forecast/summary"
        ).payload

    def get_alerts(
        self,
        *,
        minimum_level: str | None = None,
        hazardous_only: bool = False,
    ) -> dict[str, Any]:
        params = {
            "minimum_level": minimum_level,
            "hazardous_only": hazardous_only,
        }

        clean_params = {
            key: value
            for key, value
            in params.items()
            if value is not None
        }

        return self._get(
            "/alerts",
            params=clean_params,
        ).payload

    def get_active_alerts(
        self,
        *,
        include_upcoming: bool = True,
    ) -> dict[str, Any]:
        return self._get(
            "/alerts/active",
            params={
                "include_upcoming": (
                    include_upcoming
                )
            },
        ).payload

    def get_metadata(self) -> dict[str, Any]:
        return self._get(
            "/metadata"
        ).payload

    def get_pipeline_status(
        self,
    ) -> dict[str, Any]:
        return self._get(
            "/pipeline/status"
        ).payload

def clear_dashboard_api_cache() -> None:
    """Clear all Streamlit API response caches."""

    try:
        import streamlit as st
    except ImportError:
        return

    st.cache_data.clear()


def get_cached_api_client() -> FastAPIClient:
    """Return a lightweight API client."""

    return FastAPIClient()


def cached_forecast() -> dict[str, Any]:
    """Load the complete forecast with a short Streamlit TTL."""

    import streamlit as st

    settings = get_dashboard_settings()

    @st.cache_data(
        ttl=settings.dashboard_cache_ttl_seconds,
        show_spinner=False,
    )
    def _load(
        base_url: str,
    ) -> dict[str, Any]:
        client = FastAPIClient(settings)
        return client.get_forecast()

    return _load(
        settings.fastapi_base_url
    )


def cached_readiness() -> dict[str, Any]:
    """Load readiness with a short Streamlit TTL."""

    import streamlit as st

    settings = get_dashboard_settings()

    @st.cache_data(
        ttl=settings.dashboard_cache_ttl_seconds,
        show_spinner=False,
    )
    def _load(
        base_url: str,
    ) -> dict[str, Any]:
        client = FastAPIClient(settings)

        return client.get_readiness()

    return _load(
        settings.fastapi_base_url
    )

def cached_alerts() -> dict[str, Any]:
    """Load all alert episodes with a short Streamlit cache."""

    import streamlit as st

    settings = get_dashboard_settings()

    @st.cache_data(
        ttl=settings.dashboard_cache_ttl_seconds,
        show_spinner=False,
    )
    def _load(
        base_url: str,
    ) -> dict[str, Any]:
        client = FastAPIClient(settings)

        return client.get_alerts()

    return _load(
        settings.fastapi_base_url
    )


def cached_active_alerts() -> dict[str, Any]:
    """Load current and upcoming alert episodes."""

    import streamlit as st

    settings = get_dashboard_settings()

    @st.cache_data(
        ttl=settings.dashboard_cache_ttl_seconds,
        show_spinner=False,
    )
    def _load(
        base_url: str,
    ) -> dict[str, Any]:
        client = FastAPIClient(settings)

        return client.get_active_alerts(
            include_upcoming=True
        )

    return _load(
        settings.fastapi_base_url
    )


def cached_metadata() -> dict[str, Any]:
    """Load public metadata."""

    import streamlit as st

    settings = get_dashboard_settings()

    @st.cache_data(
        ttl=settings.dashboard_cache_ttl_seconds,
        show_spinner=False,
    )
    def _load(
        base_url: str,
    ) -> dict[str, Any]:
        client = FastAPIClient(settings)

        return client.get_metadata()

    return _load(
        settings.fastapi_base_url
    )


def cached_pipeline_status() -> dict[str, Any]:
    """Load the latest pipeline status."""

    import streamlit as st

    settings = get_dashboard_settings()

    @st.cache_data(
        ttl=settings.dashboard_cache_ttl_seconds,
        show_spinner=False,
    )
    def _load(
        base_url: str,
    ) -> dict[str, Any]:
        client = FastAPIClient(settings)

        return client.get_pipeline_status()

    return _load(
        settings.fastapi_base_url
    )


def cached_liveness() -> dict[str, Any]:
    """Load FastAPI process liveness."""

    import streamlit as st

    settings = get_dashboard_settings()

    @st.cache_data(
        ttl=settings.dashboard_cache_ttl_seconds,
        show_spinner=False,
    )
    def _load(
        base_url: str,
    ) -> dict[str, Any]:
        client = FastAPIClient(settings)

        return client.get_liveness()

    return _load(
        settings.fastapi_base_url
    )