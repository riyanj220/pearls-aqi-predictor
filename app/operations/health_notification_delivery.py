"""Durable webhook outbox for production-health incidents."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

from app.artifacts.repository import (
    ArtifactRepository,
)
from app.notifications.webhook import (
    JsonWebhookClient,
)


NOTIFICATION_OUTBOX_PATH = (
    "production-health/notifications/outbox.json"
)

NOTIFICATION_RECEIPT_PREFIX = (
    "production-health/notifications/receipts"
)

SUPPORTED_NOTIFICATION_TYPES = {
    "INCIDENT_OPENED",
    "INCIDENT_CHANGED",
    "INCIDENT_RESOLVED",
}


class HealthNotificationError(RuntimeError):
    """Raised when incident notification handling fails."""


def utc_now() -> datetime:
    """Return current timezone-aware UTC time."""

    return datetime.now(
        timezone.utc
    )


def read_environment_value(
    name: str,
    *,
    default: str | None = None,
) -> str | None:
    """Read and normalize one environment variable."""

    value = os.getenv(
        name,
        default,
    )

    if value is None:
        return None

    normalized = value.strip()

    return normalized or None


def read_environment_bool(
    name: str,
    *,
    default: bool,
) -> bool:
    """Read one boolean environment variable."""

    raw_value = read_environment_value(
        name
    )

    if raw_value is None:
        return default

    normalized = raw_value.lower()

    if normalized in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True

    if normalized in {
        "0",
        "false",
        "no",
        "off",
    }:
        return False

    raise HealthNotificationError(
        f"{name} must contain a boolean value."
    )


def read_timeout_seconds() -> float:
    """Read the webhook timeout."""

    raw_value = read_environment_value(
        "PRODUCTION_HEALTH_WEBHOOK_TIMEOUT_SECONDS",
        default="15",
    )

    try:
        timeout = float(
            raw_value or "15"
        )
    except ValueError as error:
        raise HealthNotificationError(
            "PRODUCTION_HEALTH_WEBHOOK_TIMEOUT_SECONDS "
            "must be numeric."
        ) from error

    if timeout <= 0:
        raise HealthNotificationError(
            "Webhook timeout must be positive."
        )

    return timeout


def load_outbox(
    repository: ArtifactRepository,
) -> dict[str, Any]:
    """Load the durable notification outbox."""

    if not repository.exists(
        NOTIFICATION_OUTBOX_PATH
    ):
        return {
            "version": 1,
            "pending": [],
            "updated_at_utc": (
                utc_now().isoformat()
            ),
        }

    outbox = repository.download_json(
        NOTIFICATION_OUTBOX_PATH
    )

    pending = outbox.get(
        "pending"
    )

    if not isinstance(pending, list):
        raise HealthNotificationError(
            "Notification outbox pending value "
            "must be a list."
        )

    return {
        "version": 1,
        "pending": [
            item
            for item in pending
            if isinstance(item, dict)
        ],
        "updated_at_utc": outbox.get(
            "updated_at_utc"
        ),
    }


def save_outbox(
    *,
    repository: ArtifactRepository,
    pending: list[dict[str, Any]],
    now: datetime,
) -> None:
    """Persist mutable notification outbox state."""

    repository.upload_json(
        payload={
            "version": 1,
            "pending": pending,
            "pending_count": len(
                pending
            ),
            "updated_at_utc": (
                now.isoformat()
            ),
        },
        destination_path=(
            NOTIFICATION_OUTBOX_PATH
        ),
        overwrite=True,
    )


def build_notification_id(
    *,
    notification_type: str,
    incident_id: str,
    history_path: str | None,
) -> str:
    """Build a stable notification identifier."""

    payload = {
        "notification_type": (
            notification_type
        ),
        "incident_id": incident_id,
        "history_path": history_path,
    }

    digest = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    return (
        f"{notification_type.lower()}_"
        f"{digest[:20]}"
    )


def build_notification_event(
    *,
    incident_evaluation: dict[str, Any],
    health_report: dict[str, Any],
    health_run_id: str,
    now: datetime,
) -> dict[str, Any] | None:
    """Build a webhook event when notification is required."""

    if not bool(
        incident_evaluation.get(
            "notification_required"
        )
    ):
        return None

    notification_type = str(
        incident_evaluation.get(
            "notification_type",
            "",
        )
    )

    if (
        notification_type
        not in SUPPORTED_NOTIFICATION_TYPES
    ):
        raise HealthNotificationError(
            "Unsupported health notification type: "
            f"{notification_type!r}"
        )

    incident = incident_evaluation.get(
        "incident"
    )

    if not isinstance(
        incident,
        dict,
    ):
        raise HealthNotificationError(
            "Notification event requires incident data."
        )

    incident_id = str(
        incident.get(
            "incident_id",
            "",
        )
    )

    if not incident_id:
        raise HealthNotificationError(
            "Incident does not contain an incident ID."
        )

    history_path_value = (
        incident_evaluation.get(
            "history_path"
        )
    )

    history_path = (
        str(history_path_value)
        if history_path_value
        else None
    )

    notification_id = (
        build_notification_id(
            notification_type=(
                notification_type
            ),
            incident_id=incident_id,
            history_path=history_path,
        )
    )

    components = (
        incident_evaluation.get(
            "unhealthy_components",
            [],
        )
    )

    return {
        "notification_id": (
            notification_id
        ),
        "schema_version": 1,
        "event_type": notification_type,
        "created_at_utc": (
            now.isoformat()
        ),
        "environment": (
            read_environment_value(
                "APP_ENV",
                default="development",
            )
            or "development"
        ),
        "project": "pearls-aqi",
        "health_run_id": health_run_id,
        "health_status": (
            health_report.get(
                "status"
            )
        ),
        "overall_component_status": (
            health_report.get(
                "overall_component_status"
            )
        ),
        "incident_id": incident_id,
        "incident_status": (
            incident.get(
                "status"
            )
        ),
        "opened_at_utc": (
            incident.get(
                "opened_at_utc"
            )
        ),
        "resolved_at_utc": (
            incident.get(
                "resolved_at_utc"
            )
        ),
        "occurrence_count": (
            incident.get(
                "occurrence_count"
            )
        ),
        "history_path": history_path,
        "components": (
            components
            if isinstance(
                components,
                list,
            )
            else []
        ),
        "recommendations": (
            health_report.get(
                "recommendations",
                [],
            )
        ),
    }


def enqueue_notification(
    *,
    repository: ArtifactRepository,
    event: dict[str, Any] | None,
    now: datetime,
) -> dict[str, Any]:
    """Add one event unless already pending or delivered."""

    outbox = load_outbox(
        repository
    )

    pending = list(
        outbox["pending"]
    )

    if event is None:
        return {
            "pending": pending,
            "enqueued": False,
            "notification_id": None,
        }

    notification_id = str(
        event["notification_id"]
    )

    receipt_path = (
        f"{NOTIFICATION_RECEIPT_PREFIX}/"
        f"{notification_id}.json"
    )

    already_pending = any(
        item.get(
            "notification_id"
        )
        == notification_id
        for item in pending
    )

    already_delivered = repository.exists(
        receipt_path
    )

    if (
        not already_pending
        and not already_delivered
    ):
        pending.append(event)

        save_outbox(
            repository=repository,
            pending=pending,
            now=now,
        )

        return {
            "pending": pending,
            "enqueued": True,
            "notification_id": (
                notification_id
            ),
        }

    return {
        "pending": pending,
        "enqueued": False,
        "notification_id": (
            notification_id
        ),
    }


def create_webhook_client() -> (
    JsonWebhookClient | None
):
    """Create the configured webhook client."""

    enabled = read_environment_bool(
        "PRODUCTION_HEALTH_WEBHOOK_ENABLED",
        default=False,
    )

    if not enabled:
        return None

    url = read_environment_value(
        "PRODUCTION_HEALTH_WEBHOOK_URL"
    )

    if url is None:
        raise HealthNotificationError(
            "PRODUCTION_HEALTH_WEBHOOK_URL is required "
            "when webhook delivery is enabled."
        )

    bearer_token = read_environment_value(
        "PRODUCTION_HEALTH_WEBHOOK_BEARER_TOKEN"
    )

    return JsonWebhookClient(
        url=url,
        timeout_seconds=(
            read_timeout_seconds()
        ),
        bearer_token=bearer_token,
    )


def deliver_pending_notifications(
    *,
    repository: ArtifactRepository,
    client: JsonWebhookClient | None,
    now: datetime,
) -> dict[str, Any]:
    """Deliver pending events and retain failed items."""

    outbox = load_outbox(
        repository
    )

    pending = list(
        outbox["pending"]
    )

    if client is None:
        return {
            "status": "WEBHOOK_DISABLED",
            "attempted_count": 0,
            "delivered_count": 0,
            "failed_count": 0,
            "pending_count": len(
                pending
            ),
            "delivered": [],
            "failures": [],
        }

    remaining: list[
        dict[str, Any]
    ] = []

    delivered: list[
        dict[str, Any]
    ] = []

    failures: list[
        dict[str, Any]
    ] = []

    for event in pending:
        notification_id = str(
            event.get(
                "notification_id",
                "",
            )
        )

        if not notification_id:
            failures.append(
                {
                    "notification_id": None,
                    "error_type": (
                        "HealthNotificationError"
                    ),
                    "error_message": (
                        "Pending notification has "
                        "no notification ID."
                    ),
                }
            )

            remaining.append(event)
            continue

        receipt_path = (
            f"{NOTIFICATION_RECEIPT_PREFIX}/"
            f"{notification_id}.json"
        )

        # A receipt may exist when delivery succeeded but the
        # process stopped before clearing the mutable outbox.
        if repository.exists(
            receipt_path
        ):
            delivered.append(
                {
                    "notification_id": (
                        notification_id
                    ),
                    "receipt_path": (
                        receipt_path
                    ),
                    "recovered_from_receipt": (
                        True
                    ),
                }
            )
            continue

        try:
            result = client.send(
                payload=event,
                idempotency_key=(
                    notification_id
                ),
            )

            receipt = {
                "notification_id": (
                    notification_id
                ),
                "event_type": event.get(
                    "event_type"
                ),
                "incident_id": event.get(
                    "incident_id"
                ),
                "delivered_at_utc": (
                    now.isoformat()
                ),
                "http_status_code": (
                    result.status_code
                ),
                "idempotency_key": (
                    result.idempotency_key
                ),
                "response_body": (
                    result.response_body[
                        :1000
                    ]
                ),
            }

            repository.upload_json(
                payload=receipt,
                destination_path=(
                    receipt_path
                ),
                overwrite=False,
            )

            delivered.append(
                {
                    "notification_id": (
                        notification_id
                    ),
                    "receipt_path": (
                        receipt_path
                    ),
                    "http_status_code": (
                        result.status_code
                    ),
                    "recovered_from_receipt": (
                        False
                    ),
                }
            )

        except Exception as error:
            remaining.append(event)

            failures.append(
                {
                    "notification_id": (
                        notification_id
                    ),
                    "error_type": (
                        type(error).__name__
                    ),
                    "error_message": str(
                        error
                    ),
                }
            )

    save_outbox(
        repository=repository,
        pending=remaining,
        now=now,
    )

    if failures:
        status = (
            "WEBHOOK_DELIVERY_FAILED"
        )

    elif delivered:
        status = (
            "WEBHOOK_DELIVERY_COMPLETED"
        )

    else:
        status = (
            "WEBHOOK_NOTHING_TO_DELIVER"
        )

    return {
        "status": status,
        "attempted_count": len(
            pending
        ),
        "delivered_count": len(
            delivered
        ),
        "failed_count": len(
            failures
        ),
        "pending_count": len(
            remaining
        ),
        "delivered": delivered,
        "failures": failures,
    }


def process_health_notifications(
    *,
    repository: ArtifactRepository,
    incident_evaluation: dict[str, Any],
    health_report: dict[str, Any],
    health_run_id: str,
    now: datetime,
) -> dict[str, Any]:
    """Enqueue the current event and process all pending events."""

    event = build_notification_event(
        incident_evaluation=(
            incident_evaluation
        ),
        health_report=health_report,
        health_run_id=health_run_id,
        now=now,
    )

    enqueue_result = (
        enqueue_notification(
            repository=repository,
            event=event,
            now=now,
        )
    )

    client = create_webhook_client()

    delivery = (
        deliver_pending_notifications(
            repository=repository,
            client=client,
            now=now,
        )
    )

    return {
        "event_created": (
            event is not None
        ),
        "notification_id": (
            event.get(
                "notification_id"
            )
            if event is not None
            else None
        ),
        "enqueued": (
            enqueue_result[
                "enqueued"
            ]
        ),
        **delivery,
    }