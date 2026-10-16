import logging

from brevo import Brevo
from brevo.core.api_error import ApiError
from brevo.transactional_emails import (
    SendTransacEmailRequestSender,
    SendTransacEmailRequestToItem,
)
from django.conf import settings

from .base import BaseChannel

logger = logging.getLogger(__name__)


def _client() -> Brevo:
    """Lazy client — settings must be loaded before instantiation."""
    return Brevo(api_key=settings.BREVO_API_KEY)


class BrevoEmailChannel(BaseChannel):
    name = "EMAIL"

    def send(self, notification) -> dict:
        if not settings.BREVO_API_KEY:
            return {"success": False, "provider_id": None, "error": "brevo_not_configured"}
        if not notification.recipient.email:
            return {"success": False, "provider_id": None, "error": "recipient_has_no_email"}

        try:
            response = _client().transactional_emails.send_transac_email(
                sender=SendTransacEmailRequestSender(
                    email=settings.BREVO_SENDER_EMAIL,
                    name=settings.BREVO_SENDER_NAME,
                ),
                to=[SendTransacEmailRequestToItem(
                    email=notification.recipient.email,
                    name=notification.recipient.name or "",
                )],
                subject=notification.subject or "(no subject)",
                html_content=notification.body_html or f"<p>{notification.body_text}</p>",
                text_content=notification.body_text or "",
            )
            return {
                "success": True,
                "provider_id": getattr(response, "message_id", None) or "",
                "error": None,
            }
        except ApiError as exc:
            logger.warning("brevo api error status=%s body=%s", exc.status_code, exc.body)
            return {"success": False, "provider_id": None,
                    "error": f"brevo_{exc.status_code}:{str(exc.body)[:200]}"}
        except Exception as exc:
            logger.exception("brevo unexpected error")
            return {"success": False, "provider_id": None, "error": str(exc)}