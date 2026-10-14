import time

from celery import shared_task

from apps.notifications.channels.base import BaseChannel
from apps.notifications.channels.websocket import WebSocketChannel
from apps.notifications.models import DeadLetter, DeliveryAttempt, Notification

# Registry — later phases add EMAIL, SMS, WEBPUSH
CHANNEL_REGISTRY: dict[str, BaseChannel] = {
    "WEBSOCKET": WebSocketChannel(),
}

MAX_RETRIES = 3


@shared_task(bind=True, max_retries=MAX_RETRIES)
def deliver_notification(self, notification_id: str):
    try:
        notification = Notification.objects.select_related("recipient").get(id=notification_id)
    except Notification.DoesNotExist:
        return {"status": "skipped", "reason": "not_found"}

    if notification.status != Notification.STATUS_PENDING:
        return {"status": "skipped", "reason": "not_pending"}

    adapter = CHANNEL_REGISTRY.get(notification.channel)
    if adapter is None:
        _dead_letter(notification, f"no_adapter_for_channel:{notification.channel}")
        return {"status": "dlq", "reason": "no_adapter"}

    started = time.monotonic()
    result = adapter.send(notification)
    latency_ms = int((time.monotonic() - started) * 1000)

    DeliveryAttempt.objects.create(
        tenant=notification.tenant,
        notification=notification,
        channel=notification.channel,
        status="SENT" if result["success"] else "FAILED",
        provider_response=result.get("provider_id") or result.get("error") or "",
        latency_ms=latency_ms,
    )

    if result["success"]:
        notification.status = Notification.STATUS_SENT
        notification.save(update_fields=["status", "updated_at"])
        return {"status": "sent", "notification_id": str(notification.id), "latency_ms": latency_ms}

    # Failure → retry with exponential backoff
    if self.request.retries >= MAX_RETRIES:
        _dead_letter(notification, result.get("error") or "unknown_error")
        notification.status = Notification.STATUS_FAILED
        notification.save(update_fields=["status", "updated_at"])
        return {"status": "dlq", "reason": result.get("error")}

    countdown = 2 ** self.request.retries + 0.5
    raise self.retry(countdown=countdown, exc=Exception(result.get("error")))


def _dead_letter(notification, reason: str):
    DeadLetter.objects.create(
        tenant=notification.tenant,
        notification=notification,
        reason=reason,
    )