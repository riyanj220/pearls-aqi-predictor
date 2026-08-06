"""Small generic HTTPS JSON webhook client."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping


class WebhookConfigurationError(ValueError):
    """Raised when webhook configuration is invalid."""


class WebhookDeliveryError(RuntimeError):
    """Raised when a webhook request cannot be delivered."""


@dataclass(frozen=True)
class WebhookDeliveryResult:
    """Successful webhook-delivery metadata."""

    status_code: int
    response_body: str
    idempotency_key: str


class JsonWebhookClient:
    """Deliver JSON documents to one generic HTTPS endpoint."""

    def __init__(
        self,
        *,
        url: str,
        timeout_seconds: float = 15,
        bearer_token: str | None = None,
        allow_insecure_http: bool = False,
    ) -> None:
        normalized_url = url.strip()

        if not normalized_url:
            raise WebhookConfigurationError(
                "Webhook URL cannot be empty."
            )

        parsed = urllib.parse.urlparse(
            normalized_url
        )

        allowed_schemes = (
            {"https", "http"}
            if allow_insecure_http
            else {"https"}
        )

        if parsed.scheme.lower() not in allowed_schemes:
            raise WebhookConfigurationError(
                "Webhook URL must use HTTPS."
            )

        if not parsed.netloc:
            raise WebhookConfigurationError(
                "Webhook URL must contain a host."
            )

        if timeout_seconds <= 0:
            raise WebhookConfigurationError(
                "Webhook timeout must be positive."
            )

        self.url = normalized_url
        self.timeout_seconds = timeout_seconds
        self.bearer_token = (
            bearer_token.strip()
            if bearer_token
            and bearer_token.strip()
            else None
        )

    def send(
        self,
        *,
        payload: Mapping[str, Any],
        idempotency_key: str,
    ) -> WebhookDeliveryResult:
        """POST one JSON document."""

        normalized_key = (
            idempotency_key.strip()
        )

        if not normalized_key:
            raise WebhookConfigurationError(
                "Webhook idempotency key cannot be empty."
            )

        request_body = json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        ).encode("utf-8")

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": (
                "pearls-aqi-production-monitor/1.0"
            ),
            "Idempotency-Key": normalized_key,
        }

        if self.bearer_token is not None:
            headers["Authorization"] = (
                f"Bearer {self.bearer_token}"
            )

        request = urllib.request.Request(
            url=self.url,
            data=request_body,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                status_code = int(
                    response.status
                )

                response_body = (
                    response.read(4096)
                    .decode(
                        "utf-8",
                        errors="replace",
                    )
                )

        except urllib.error.HTTPError as error:
            response_body = (
                error.read(4096)
                .decode(
                    "utf-8",
                    errors="replace",
                )
            )

            raise WebhookDeliveryError(
                "Webhook returned an unsuccessful "
                f"HTTP response: {error.code}. "
                f"Response={response_body[:500]!r}"
            ) from error

        except urllib.error.URLError as error:
            raise WebhookDeliveryError(
                "Webhook endpoint could not be reached."
            ) from error

        except TimeoutError as error:
            raise WebhookDeliveryError(
                "Webhook request timed out."
            ) from error

        if not 200 <= status_code < 300:
            raise WebhookDeliveryError(
                "Webhook returned an unsuccessful "
                f"HTTP response: {status_code}."
            )

        return WebhookDeliveryResult(
            status_code=status_code,
            response_body=response_body,
            idempotency_key=normalized_key,
        )