import json
import logging

from django.conf import settings
from pywebpush import WebPushException, webpush

from .base import BaseChannel

logger = logging.getLogger(__name__)


class WebPushChannel(BaseChannel):
    name = "WEBPUSH"

    def send(self, notification) -> dict:
        if not settings.VAPID_PRIVATE_KEY:
            return {"success": False, "provider_id": None, "error": "vapid_not_configured"}

        subs = notification.recipient.push_subscriptions.all()
        if not subs:
            return {"success": False, "provider_id": None, "error": "no_push_subscription"}

        payload = json.dumps({
            "id": str(notification.id),
            "incident_id": str(notification.incident_id),
            "title": notification.subject,
            "body": notification.body_text,
            "url": f"/incidents/{notification.incident_id}",
        })

        delivered = 0
        last_err = None
        for sub in subs:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                    },
                    data=payload,
                    vapid_private_key=settings.VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": f"mailto:{settings.VAPID_ADMIN_EMAIL}"},
                    timeout=10,
                )
                delivered += 1
            except WebPushException as exc:
                status = getattr(exc.response, "status_code", None)
                if status in (404, 410):
                    sub.delete()   # stale subscription — clean up
                last_err = str(exc)
                logger.warning("webpush failed endpoint=%s status=%s", sub.endpoint[:60], status)

        if delivered > 0:
            return {"success": True, "provider_id": f"webpush:{delivered}", "error": None}
        return {"success": False, "provider_id": None, "error": last_err or "no_delivery"}