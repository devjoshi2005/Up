import logging

from django.conf import settings
from django.core.mail import send_mail

from .base import BaseChannel

logger = logging.getLogger(__name__)


class SmtpEmailChannel(BaseChannel):
    """EMAIL adapter that sends over SMTP (Django EMAIL_HOST/PORT).

    Used for local chaos/load runs pointed at Mailpit, so the full email path is
    exercised without touching Brevo's API or spending daily quota.
    """

    name = "EMAIL"

    def send(self, notification) -> dict:
        to = notification.recipient.email
        if not to:
            return {"success": False, "provider_id": None, "error": "recipient_has_no_email"}

        try:
            sent = send_mail(
                subject=notification.subject or "(no subject)",
                message=notification.body_text or "",
                html_message=notification.body_html or None,
                from_email=settings.BREVO_SENDER_EMAIL or "alerts@sysflow.test",
                recipient_list=[to],
                fail_silently=False,
            )
        except Exception as exc:  # smtp refused / timeout / etc.
            logger.warning("smtp send failed to=%s err=%s", to, exc)
            return {"success": False, "provider_id": None, "error": str(exc)[:200]}

        if not sent:
            return {"success": False, "provider_id": None, "error": "smtp_send_returned_0"}
        return {"success": True, "provider_id": f"smtp:{notification.id}", "error": None}
