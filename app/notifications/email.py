"""Azure Communication Services email notification client."""

from __future__ import annotations

from dataclasses import dataclass

from azure.communication.email import (
    EmailClient,
)
from azure.identity import (
    DefaultAzureCredential,
)


class EmailNotificationError(
    RuntimeError
):
    """Raised when an alert email cannot be sent."""


@dataclass(frozen=True)
class EmailDeliveryResult:
    """Result of one email delivery."""

    message_id: str | None
    status: str


class AzureEmailClient:
    """Send operational email through Azure Communication Services."""

    def __init__(
        self,
        *,
        endpoint: str,
        sender_address: str,
        recipient_address: str,
        managed_identity_client_id: str | None = None,
    ) -> None:
        self.sender_address = (
            sender_address
        )

        self.recipient_address = (
            recipient_address
        )

        credential = (
            DefaultAzureCredential(
                managed_identity_client_id=(
                    managed_identity_client_id
                ),
                exclude_interactive_browser_credential=True,
            )
        )

        self.client = EmailClient(
            endpoint,
            credential,
        )

    def send(
        self,
        *,
        subject: str,
        plain_text: str,
        html: str | None = None,
    ) -> EmailDeliveryResult:
        """Send one alert email."""

        message = {
            "senderAddress": (
                self.sender_address
            ),
            "recipients": {
                "to": [
                    {
                        "address": (
                            self.recipient_address
                        )
                    }
                ]
            },
            "content": {
                "subject": subject,
                "plainText": (
                    plain_text
                ),
            },
        }

        if html:
            message[
                "content"
            ][
                "html"
            ] = html

        try:
            poller = (
                self.client.begin_send(
                    message
                )
            )

            result = poller.result()

        except Exception as error:
            raise EmailNotificationError(
                "Azure Communication Services "
                "email delivery failed."
            ) from error

        return EmailDeliveryResult(
            message_id=(
                result.get("id")
                if isinstance(
                    result,
                    dict,
                )
                else None
            ),
            status=(
                str(
                    result.get(
                        "status",
                        "SUCCEEDED",
                    )
                )
                if isinstance(
                    result,
                    dict,
                )
                else "SUCCEEDED"
            ),
        )
