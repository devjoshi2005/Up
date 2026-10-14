import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .base import BaseChannel

logger = logging.getLogger(__name__)


def group_name_for_recipient(recipient_id) -> str:
    return f"recipient.{recipient_id}"


class WebSocketChannel(BaseChannel):
    name = "WEBSOCKET"

    def send(self, notification) -> dict:
        layer = get_channel_layer()
        if layer is None:
            return {"success": False, "provider_id": None, "error": "no_channel_layer"}

        group = group_name_for_recipient(notification.recipient_id)
        message = {
            "type": "notify.message",       # maps to consumer.notify_message
            "payload": {
                "id": str(notification.id),
                "incident_id": str(notification.incident_id),
                "channel": notification.channel,
                "subject": notification.subject,
                "body": notification.body_text,
                "created_at": notification.created_at.isoformat(),
                "sent_at": int(notification.created_at.timestamp() * 1000),
            },
        }
        try:
            async_to_sync(layer.group_send)(group, message)
            return {"success": True, "provider_id": f"ws:{notification.id}", "error": None}
        except Exception as exc:                       # pragma: no cover
            logger.exception("websocket send failed")
            return {"success": False, "provider_id": None, "error": str(exc)}