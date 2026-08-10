"""Tests for durable health webhook delivery."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.artifacts.repository import (
    LocalArtifactRepository,
)
from app.notifications.webhook import (
    WebhookDeliveryResult,
)
from app.operations.health_notification_delivery import (
    NOTIFICATION_OUTBOX_PATH,
    build_notification_event,
    deliver_pending_email_notifications,
    deliver_pending_notifications,
    enqueue_notification,
)


NOW = datetime(
    2026,
    8,
    6,
    12,
    0,
    tzinfo=timezone.utc,
)


class SuccessfulClient:
    """Webhook client that always succeeds."""

    def send(
        self,
        *,
        payload,
        idempotency_key,
    ):
        return WebhookDeliveryResult(
            status_code=204,
            response_body="",
            idempotency_key=(
                idempotency_key
            ),
        )


class FailingClient:
    """Webhook client that always fails."""

    def send(
        self,
        *,
        payload,
        idempotency_key,
    ):
        raise RuntimeError(
            "Temporary webhook failure."
        )

class FakeEmailResult:
    """Successful fake email result."""

    message_id = "message-123"
    status = "Succeeded"


class FakeEmailClient:
    """Email client that always succeeds."""

    def send(
        self,
        *,
        subject: str,
        plain_text: str,
        html: str | None = None,
    ):
        assert (
            "[Pearls AQI Alert]"
            in subject
        )

        assert plain_text

        return FakeEmailResult()


class FailingEmailClient:
    """Email client that always fails."""

    def send(
        self,
        **kwargs,
    ):
        raise RuntimeError(
            "email unavailable"
        )

def build_incident_evaluation():
    """Build one opened-incident result."""

    return {
        "notification_required": True,
        "notification_type": (
            "INCIDENT_OPENED"
        ),
        "history_path": (
            "production-health/incidents/"
            "history/opened.json"
        ),
        "incident": {
            "incident_id": "incident-1",
            "status": "ACTIVE",
            "opened_at_utc": (
                NOW.isoformat()
            ),
            "occurrence_count": 1,
        },
        "unhealthy_components": [
            {
                "category": (
                    "feature_dataset",
                ),
                "name": "pm25",
                "status": "WARNING",
            }
        ],
    }


def build_health_report():
    """Build one warning health report."""

    return {
        "status": (
            "PRODUCTION_HEALTH_WARNING"
        ),
        "overall_component_status": (
            "WARNING"
        ),
        "recommendations": [
            "Inspect PM2.5 freshness."
        ],
    }


def test_event_is_enqueued_once(
    tmp_path: Path,
) -> None:
    repository = (
        LocalArtifactRepository(
            tmp_path
        )
    )

    event = build_notification_event(
        incident_evaluation=(
            build_incident_evaluation()
        ),
        health_report=(
            build_health_report()
        ),
        health_run_id="health-run-1",
        now=NOW,
    )

    assert event is not None

    first = enqueue_notification(
        repository=repository,
        event=event,
        now=NOW,
    )

    second = enqueue_notification(
        repository=repository,
        event=event,
        now=NOW,
    )

    assert first["enqueued"] is True
    assert second["enqueued"] is False

    outbox = repository.download_json(
        NOTIFICATION_OUTBOX_PATH
    )

    assert len(
        outbox["pending"]
    ) == 1


def test_success_creates_receipt_and_clears_outbox(
    tmp_path: Path,
) -> None:
    repository = (
        LocalArtifactRepository(
            tmp_path
        )
    )

    event = build_notification_event(
        incident_evaluation=(
            build_incident_evaluation()
        ),
        health_report=(
            build_health_report()
        ),
        health_run_id="health-run-1",
        now=NOW,
    )

    enqueue_notification(
        repository=repository,
        event=event,
        now=NOW,
    )

    result = (
        deliver_pending_notifications(
            repository=repository,
            client=SuccessfulClient(),
            now=NOW,
        )
    )

    assert (
        result["status"]
        == "WEBHOOK_DELIVERY_COMPLETED"
    )

    assert result["delivered_count"] == 1
    assert result["failed_count"] == 0
    assert result["pending_count"] == 0

    receipt_path = (
        result["delivered"][0][
            "receipt_path"
        ]
    )

    assert repository.exists(
        receipt_path
    )


def test_failure_remains_pending(
    tmp_path: Path,
) -> None:
    repository = (
        LocalArtifactRepository(
            tmp_path
        )
    )

    event = build_notification_event(
        incident_evaluation=(
            build_incident_evaluation()
        ),
        health_report=(
            build_health_report()
        ),
        health_run_id="health-run-1",
        now=NOW,
    )

    enqueue_notification(
        repository=repository,
        event=event,
        now=NOW,
    )

    result = (
        deliver_pending_notifications(
            repository=repository,
            client=FailingClient(),
            now=NOW,
        )
    )

    assert (
        result["status"]
        == "WEBHOOK_DELIVERY_FAILED"
    )

    assert result["delivered_count"] == 0
    assert result["failed_count"] == 1
    assert result["pending_count"] == 1

    outbox = repository.download_json(
        NOTIFICATION_OUTBOX_PATH
    )

    assert len(
        outbox["pending"]
    ) == 1


def test_disabled_webhook_keeps_pending(
    tmp_path: Path,
) -> None:
    repository = (
        LocalArtifactRepository(
            tmp_path
        )
    )

    event = build_notification_event(
        incident_evaluation=(
            build_incident_evaluation()
        ),
        health_report=(
            build_health_report()
        ),
        health_run_id="health-run-1",
        now=NOW,
    )

    enqueue_notification(
        repository=repository,
        event=event,
        now=NOW,
    )

    result = (
        deliver_pending_notifications(
            repository=repository,
            client=None,
            now=NOW,
        )
    )

    assert (
        result["status"]
        == "WEBHOOK_DISABLED"
    )

    assert result["pending_count"] == 1


def test_disabled_email_keeps_pending(
    tmp_path: Path,
) -> None:
    repository = (
        LocalArtifactRepository(
            tmp_path
        )
    )

    event = build_notification_event(
        incident_evaluation=(
            build_incident_evaluation()
        ),
        health_report=(
            build_health_report()
        ),
        health_run_id="health-run-1",
        now=NOW,
    )

    enqueue_notification(
        repository=repository,
        event=event,
        now=NOW,
    )

    result = (
        deliver_pending_email_notifications(
            repository=repository,
            client=None,
            now=NOW,
        )
    )

    assert (
        result["status"]
        == "EMAIL_DISABLED"
    )

    assert result["channel"] == "email"
    assert result["attempted_count"] == 0
    assert result["delivered_count"] == 0
    assert result["failed_count"] == 0
    assert result["pending_count"] == 1


def test_email_success_creates_receipt_and_clears_outbox(
    tmp_path: Path,
) -> None:
    repository = (
        LocalArtifactRepository(
            tmp_path
        )
    )

    event = build_notification_event(
        incident_evaluation=(
            build_incident_evaluation()
        ),
        health_report=(
            build_health_report()
        ),
        health_run_id="health-run-1",
        now=NOW,
    )

    enqueue_notification(
        repository=repository,
        event=event,
        now=NOW,
    )

    result = (
        deliver_pending_email_notifications(
            repository=repository,
            client=FakeEmailClient(),
            now=NOW,
        )
    )

    assert (
        result["status"]
        == "EMAIL_DELIVERY_COMPLETED"
    )

    assert result["channel"] == "email"
    assert result["delivered_count"] == 1
    assert result["failed_count"] == 0
    assert result["pending_count"] == 0

    delivered = (
        result[
            "delivered"
        ][0]
    )

    assert (
        delivered[
            "provider_message_id"
        ]
        == "message-123"
    )

    assert (
        delivered[
            "provider_status"
        ]
        == "Succeeded"
    )

    receipt_path = (
        delivered[
            "receipt_path"
        ]
    )

    assert repository.exists(
        receipt_path
    )

def test_email_failure_remains_pending(
    tmp_path: Path,
) -> None:
    repository = (
        LocalArtifactRepository(
            tmp_path
        )
    )

    event = build_notification_event(
        incident_evaluation=(
            build_incident_evaluation()
        ),
        health_report=(
            build_health_report()
        ),
        health_run_id="health-run-1",
        now=NOW,
    )

    enqueue_notification(
        repository=repository,
        event=event,
        now=NOW,
    )

    result = (
        deliver_pending_email_notifications(
            repository=repository,
            client=FailingEmailClient(),
            now=NOW,
        )
    )

    assert (
        result["status"]
        == "EMAIL_DELIVERY_FAILED"
    )

    assert result["channel"] == "email"
    assert result["delivered_count"] == 0
    assert result["failed_count"] == 1
    assert result["pending_count"] == 1

    outbox = repository.download_json(
        NOTIFICATION_OUTBOX_PATH
    )

    assert len(
        outbox["pending"]
    ) == 1


def test_existing_email_receipt_clears_pending_event(
    tmp_path: Path,
) -> None:
    repository = (
        LocalArtifactRepository(
            tmp_path
        )
    )

    event = build_notification_event(
        incident_evaluation=(
            build_incident_evaluation()
        ),
        health_report=(
            build_health_report()
        ),
        health_run_id="health-run-1",
        now=NOW,
    )

    assert event is not None

    enqueue_notification(
        repository=repository,
        event=event,
        now=NOW,
    )

    notification_id = str(
        event[
            "notification_id"
        ]
    )

    receipt_path = (
        "production-health/"
        "notifications/"
        "receipts/"
        f"{notification_id}.json"
    )

    repository.upload_json(
        payload={
            "notification_id": (
                notification_id
            ),
            "channel": "email",
            "provider_status": (
                "Succeeded"
            ),
        },
        destination_path=(
            receipt_path
        ),
        overwrite=False,
    )

    result = (
        deliver_pending_email_notifications(
            repository=repository,
            client=FakeEmailClient(),
            now=NOW,
        )
    )

    assert result["channel"] == "email"
    assert result["delivered_count"] == 1
    assert result["failed_count"] == 0
    assert result["pending_count"] == 0

    assert (
        result[
            "delivered"
        ][0][
            "recovered_from_receipt"
        ]
        is True
    )

    outbox = repository.download_json(
        NOTIFICATION_OUTBOX_PATH
    )

    assert (
        len(
            outbox["pending"]
        )
        == 0
    )