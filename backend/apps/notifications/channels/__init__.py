from .base import BaseChannel
from .email_brevo import BrevoEmailChannel
from .email_mock import MockEmailChannel
from .email_smtp import SmtpEmailChannel
from .sms_mock import MockSMSChannel
from .sms_textlink import TextlinkSMSChannel
from .webpush import WebPushChannel
from .websocket import WebSocketChannel
from django.conf import settings

# Adapters are chosen from settings so load/chaos runs can avoid real providers:
#   EMAIL_PROVIDER = brevo (default) | smtp (Mailpit) | mock
#   SMS_PROVIDER   = textlink (default) | mock
if settings.EMAIL_PROVIDER == "mock":
    _EMAIL = MockEmailChannel()
elif settings.EMAIL_PROVIDER == "smtp":
    _EMAIL = SmtpEmailChannel()
else:
    _EMAIL = BrevoEmailChannel()

_SMS = TextlinkSMSChannel() if settings.SMS_PROVIDER == "textlink" else MockSMSChannel()
_WS = WebSocketChannel()
_PUSH = WebPushChannel()

CHANNEL_REGISTRY = {
    "WEBSOCKET": _WS,
    "EMAIL": _EMAIL,
    "SMS": _SMS,
    "WEBPUSH": _PUSH,
}
