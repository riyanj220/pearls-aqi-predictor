"""Focused tests for the dashboard FastAPI client."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from dashboard.config import DashboardSettings
from dashboard.services.api_client import (
    DashboardAPIResponseError,
    DashboardAPITimeoutError,
    FastAPIClient,
)


class FakeResponse:
    """Small requests.Response substitute."""

    def __init__(
        self,
        *,
        payload: dict[str, Any],
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.fixture
def client() -> FastAPIClient:
    """Create a dashboard client with test settings."""

    settings = DashboardSettings(
        fastapi_base_url=(
            "http://testserver/api/v1"
        ),
        dashboard_request_timeout_seconds=2,
        dashboard_cache_ttl_seconds=0,
    )

    return FastAPIClient(settings)


def test_successful_forecast_request(
    client: FastAPIClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful responses should return the JSON payload."""

    expected_payload = {
        "pipeline_run_id": "phase-6-run",
        "hourly_forecast": [],
    }

    def fake_get(
        *_: Any,
        **__: Any,
    ) -> FakeResponse:
        return FakeResponse(
            payload=expected_payload,
            headers={
                "X-Request-ID": "request-123",
            },
        )

    monkeypatch.setattr(
        client._session,
        "get",
        fake_get,
    )

    payload = client.get_forecast()

    assert payload == expected_payload


def test_structured_api_error(
    client: FastAPIClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Structured FastAPI errors should become dashboard exceptions."""

    def fake_get(
        *_: Any,
        **__: Any,
    ) -> FakeResponse:
        return FakeResponse(
            status_code=503,
            payload={
                "error": {
                    "code": "FORECAST_STALE",
                    "message": (
                        "The forecast is stale."
                    ),
                    "details": {
                        "age_hours": 13,
                    },
                    "request_id": "request-503",
                }
            },
        )

    monkeypatch.setattr(
        client._session,
        "get",
        fake_get,
    )

    with pytest.raises(
        DashboardAPIResponseError
    ) as error_info:
        client.get_forecast()

    error = error_info.value

    assert error.status_code == 503
    assert error.code == "FORECAST_STALE"
    assert error.request_id == "request-503"


def test_timeout_error(
    client: FastAPIClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requests timeouts should become dashboard timeout errors."""

    def raise_timeout(
        *_: Any,
        **__: Any,
    ) -> None:
        raise requests.Timeout(
            "Request timed out"
        )

    monkeypatch.setattr(
        client._session,
        "get",
        raise_timeout,
    )

    with pytest.raises(
        DashboardAPITimeoutError
    ):
        client.get_readiness()