from .base import BaseChannel
from .email_brevo import BrevoEmailChannel
from .sms_mock import MockSMSChannel
from .sms_textlink import TextlinkSMSChannel
from .webpush import WebPushChannel
from .websocket import WebSocketChannel
from django.conf import settings

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
