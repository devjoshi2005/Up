import logging,time

from celery import shared_task
from django.utils import timezone

from apps.notifications.channels import CHANNEL_REGISTRY
from apps.notifications.models import DeadLetter, DeliveryAttempt, Notification
from apps.notifications.quota import try_consume
from apps.notifications.quiet_hours import is_within_quiet_hours

from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone
from apps.incidents.models import Incident

SWEEPER_LIMIT=100

MAX_RETRIES = 3
CRITICAL_PRIORITIES = {Notification.PRIORITY_CRITICAL}

# Permanent failures — retrying won't help, go straight to DLQ.
NON_RETRYABLE_ERRORS = {
    "no_push_subscription",
    "recipient_has_no_email",
    "recipient_has_no_phone",
    "brevo_not_configured",
    "textlink_not_configured",
    "vapid_not_configured",
}

logger = logging.getLogger(__name__)


def _dead_letter(notification, reason):
    DeadLetter.objects.create(
        tenant=notification.tenant, notification=notification, reason=reason
    )


@shared_task(bind=True, max_retries=MAX_RETRIES)
def deliver_notification(self, notification_id: str):
    try:
        notification = Notification.objects.select_related("recipient", "tenant").get(id=notification_id)
    except Notification.DoesNotExist:
        return {"status": "skipped", "reason": "not_found"}

    if notification.status != Notification.STATUS_PENDING:
        return {"status": "skipped", "reason": "not_pending"}

    adapter = CHANNEL_REGISTRY.get(notification.channel)
    if adapter is None:
        _dead_letter(notification, f"no_adapter_for_channel:{notification.channel}")
        notification.status = Notification.STATUS_FAILED
        notification.save(update_fields=["status", "updated_at"])
        return {"status": "dlq", "reason": "no_adapter"}

    # Quiet hours — only for non-critical. Defer by 1h (retry, don't fail).
    if notification.priority not in CRITICAL_PRIORITIES and is_within_quiet_hours(notification):
        if self.request.retries < MAX_RETRIES:
            raise self.retry(countdown=3600)
        _dead_letter(notification, "quiet_hours_persisted")
        notification.status = Notification.STATUS_FAILED
        notification.save(update_fields=["status", "updated_at"])
        return {"status": "dlq", "reason": "quiet_hours"}

    # Quota — non-critical email goes through the daily counter
    if (notification.channel == "EMAIL"
            and notification.priority not in CRITICAL_PRIORITIES
            and not try_consume(notification.tenant_id)):
        _dead_letter(notification, "brevo_daily_quota_exceeded")
        notification.status = Notification.STATUS_FAILED
        notification.save(update_fields=["status", "updated_at"])
        return {"status": "dlq", "reason": "quota_exceeded"}

    started = time.monotonic()
    result = adapter.send(notification)
    latency_ms = int((time.monotonic() - started) * 1000)

    DeliveryAttempt.objects.create(
        tenant=notification.tenant,
        notification=notification,
        channel=notification.channel,
        status="SENT" if result["success"] else "FAILED",
        provider_response=(result.get("provider_id") or result.get("error") or "")[:2000],
        latency_ms=latency_ms,
    )

    if result["success"]:
        notification.status = Notification.STATUS_SENT
        notification.save(update_fields=["status", "updated_at"])
        return {"status": "sent", "channel": notification.channel, "latency_ms": latency_ms}

    error = result.get("error") or "unknown_error"
    if error in NON_RETRYABLE_ERRORS:
        _dead_letter(notification, error)
        notification.status = Notification.STATUS_FAILED
        notification.save(update_fields=["status", "updated_at"])
        return {"status": "dlq", "reason": error}

    if self.request.retries >= MAX_RETRIES:
        _dead_letter(notification, result.get("error") or "unknown_error")
        notification.status = Notification.STATUS_FAILED
        notification.save(update_fields=["status", "updated_at"])
        return {"status": "dlq", "reason": result.get("error")}

    countdown = 2 ** self.request.retries + 0.5
    raise self.retry(countdown=countdown, exc=Exception(result.get("error")))


@shared_task
def sweep_escalations():
    """
    Advance unacked PENDING notifications to the next escalation step.
    Safe to run in parallel across workers via FOR UPDATE SKIP LOCKED.
    """
    now = timezone.now()
    advanced = canceled = 0

    with transaction.atomic():
        # Lock candidate rows atomically. Parallel sweepers skip locked rows.
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM notifications
                WHERE status = %s AND escalation_due_at <= %s
                ORDER BY escalation_due_at
                LIMIT %s
                FOR UPDATE SKIP LOCKED
                """,
                [Notification.STATUS_PENDING, now, SWEEPER_LIMIT],
            )
            ids = [row[0] for row in cur.fetchall()]

        if not ids:
            return {"advanced": 0, "canceled": 0, "checked": 0}

        notifs = (
            Notification.objects
            .select_related("incident", "escalation_step", "tenant", "recipient")
            .filter(id__in=ids)
        )

        for notif in notifs:
            incident = notif.incident

            # Incident already acked/resolved → cancel this pending one
            if incident.status != Incident.STATUS_OPEN:
                notif.status = Notification.STATUS_CANCELED
                notif.save(update_fields=["status", "updated_at"])
                canceled += 1
                continue

            current = notif.escalation_step
            if current is None:
                notif.status = Notification.STATUS_FAILED
                notif.save(update_fields=["status", "updated_at"])
                continue

            next_step = (
                current.policy.steps
                .filter(step_order__gt=current.step_order, target_user__isnull=False)
                .order_by("step_order")
                .first()
            )

            # Mark current as escalated (it was sent, but not acked in time)
            notif.status = Notification.STATUS_ESCALATED
            notif.save(update_fields=["status", "updated_at"])

            if next_step is None:
                continue

            new_notif = Notification.objects.create(
                tenant=notif.tenant,
                incident=incident,
                recipient=next_step.target_user,
                channel=next_step.channel,
                priority=Notification.PRIORITY_CRITICAL,
                escalation_step=next_step,
                escalation_due_at=timezone.now() + timedelta(minutes=next_step.delay_minutes),
                subject=notif.subject,
                body_text=notif.body_text,
                body_html=notif.body_html,
            )
            queue = "critical" if new_notif.priority == Notification.PRIORITY_CRITICAL else "default"
            transaction.on_commit(
                lambda nid=new_notif.id: deliver_notification.apply_async(
                    args=[str(nid)], queue=queue
                )
            )
            advanced += 1

    return {"advanced": advanced, "canceled": canceled, "checked": len(ids)}



