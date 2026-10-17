import logging

from .base import BaseChannel

logger = logging.getLogger(__name__)


class MockEmailChannel(BaseChannel):
    """No-op EMAIL adapter for load/chaos tests — never calls Brevo.

    Selected when EMAIL_PROVIDER=mock. Mirrors MockSMSChannel so the rest of the
    delivery pipeline (attempts, status transitions, DLQ) behaves identically.
    """

    name = "EMAIL"

    def send(self, notification) -> dict:
        logger.info(
            "[MOCK EMAIL] to=%s subject=%s",
            notification.recipient.email,
            notification.subject,
        )
        return {"success": True, "provider_id": f"mock-{notification.id}", "error": None}
