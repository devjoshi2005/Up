import logging

from .base import BaseChannel

logger = logging.getLogger(__name__)


class MockSMSChannel(BaseChannel):
    name = "SMS"

    def send(self, notification) -> dict:
        msg = (notification.body_text or notification.subject or "")[:160]
        logger.info("[MOCK SMS] to=%s body=%s", notification.recipient.phone, msg)
        return {"success": True, "provider_id": f"mock-{notification.id}", "error": None}