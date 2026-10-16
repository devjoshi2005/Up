import logging

import textlink as tl
from django.conf import settings

from .base import BaseChannel

logger = logging.getLogger(__name__)


class TextlinkSMSChannel(BaseChannel):
    name = "SMS"
    MAX_LEN = 160

    def send(self, notification) -> dict:
        if not settings.TEXTLINK_API_KEY:
            return {"success": False, "provider_id": None, "error": "textlink_not_configured"}
        if not notification.recipient.phone:
            return {"success": False, "provider_id": None, "error": "recipient_has_no_phone"}

        message = (notification.body_text or notification.subject or "")[: self.MAX_LEN]

        try:
            tl.useKey(settings.TEXTLINK_API_KEY)
            result = tl.sendSMS(notification.recipient.phone, message)
        except Exception as exc:
            logger.exception("textlink send failed")
            return {"success": False, "provider_id": None, "error": str(exc)}

        # SDK returns SendMessageResult (object with .ok), older versions dict.
        if isinstance(result, dict):
            provider_id = str(result.get("id") or result.get("message_id") or "")
            status = str(result.get("status", "")).lower()
            success = bool(provider_id) or status in ("success", "sent", "queued")
            if success:
                return {"success": True, "provider_id": provider_id or "textlink:ok", "error": None}
            return {"success": False, "provider_id": None,
                    "error": result.get("error") or result.get("message") or "textlink_unknown_error"}

        ok = getattr(result, "ok", None)
        if ok is True:
            provider_id = str(getattr(result, "message", None) or getattr(result, "queued", None) or "textlink:ok")
            return {"success": True, "provider_id": provider_id, "error": None}
        err = str(getattr(result, "message", None) or result)
        return {"success": False, "provider_id": None, "error": err}