import logging,random,time

from celery import shared_task
from django.utils import timezone

from apps.notifications.channels import CHANNEL_REGISTRY
from apps.notifications.dashboard import publish_dashboard_event
from apps.notifications.models import DeadLetter, DeliveryAttempt, Notification
from apps.notifications.quota import try_consume
from apps.notifications.quiet_hours import is_within_quiet_hours

from datetime import timedelta

from django.db import connection, models, transaction
from django.utils import timezone
from apps.incidents.models import Incident

SWEEPER_LIMIT=100

MAX_RETRIES = 3
CRITICAL_PRIORITIES = {Notification.PRIORITY_CRITICAL}

# ---------- Jittered backoff ----------
MAX_BACKOFF_SECONDS = 300      # cap at 5 minutes
JITTER_MAX = 1.5               # ± 1.5s random


def _backoff_seconds(retries: int) -> float:
    """Exponential backoff with jitter, capped. retries is 0-indexed."""
    raw = (2 ** retries) + random.uniform(0, JITTER_MAX)
    return min(raw, MAX_BACKOFF_SECONDS)


# ---------- Stuck-PENDING sweeper ----------
STUCK_NEVER_STARTED_MIN = 2      # no delivery attempts within 2 min
STUCK_RETRY_STALLED_MIN = 10     # has attempts but no movement in 10 min
STUCK_BATCH = 50
STUCK_MAX_REQUEUES = 3           # after 3 requeues → DLQ

logger = logging.getLogger(__name__)


def _dead_letter(notification, reason: str, error: str = "", retries: int = 0):
    DeadLetter.objects.create(
        tenant=notification.tenant,
        notification=notification,
        reason=reason,
        last_error=error[:2000],
        retry_count=retries,
    )


def _publish_notification(notification, latency_ms=None):
    publish_dashboard_event(
        notification.tenant_id,
        {
            "kind": "notification.updated",
            "notification": {
                "id": str(notification.id),
                "incident_id": str(notification.incident_id),
                "channel": notification.channel,
                "status": notification.status,
                "subject": notification.subject,
                "latency_ms": latency_ms,
            },
        },
    )


@shared_task(bind=True, max_retries=MAX_RETRIES)
def deliver_notification(self, notification_id: str):
    try:
        notification = (
            Notification.objects
            .select_related("recipient", "tenant")
            .get(id=notification_id)
        )
    except Notification.DoesNotExist:
        return {"status": "skipped", "reason": "not_found"}

    if notification.status != Notification.STATUS_PENDING:
        return {"status": "skipped", "reason": "not_pending"}

    adapter = CHANNEL_REGISTRY.get(notification.channel)
    if adapter is None:
        _dead_letter(notification, f"no_adapter_for_channel:{notification.channel}",
                     error="adapter_missing", retries=self.request.retries)
        notification.status = Notification.STATUS_FAILED
        notification.save(update_fields=["status", "updated_at"])
        return {"status": "dlq", "reason": "no_adapter"}

    # Quiet hours — non-critical only
    if notification.priority not in CRITICAL_PRIORITIES and is_within_quiet_hours(notification):
        if self.request.retries < MAX_RETRIES:
            raise self.retry(countdown=3600)
        _dead_letter(notification, "quiet_hours_persisted",
                     error="quiet_hours", retries=self.request.retries)
        notification.status = Notification.STATUS_FAILED
        notification.save(update_fields=["status", "updated_at"])
        return {"status": "dlq", "reason": "quiet_hours"}

    # Quota — non-critical email only
    if (notification.channel == "EMAIL"
            and notification.priority not in CRITICAL_PRIORITIES
            and not try_consume(notification.tenant_id)):
        _dead_letter(notification, "brevo_daily_quota_exceeded",
                     error="quota", retries=self.request.retries)
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
        notification.retry_count = self.request.retries
        notification.save(update_fields=["status", "retry_count", "updated_at"])
        _publish_notification(notification, latency_ms=latency_ms)
        return {"status": "sent", "channel": notification.channel, "latency_ms": latency_ms}

    # Failure path
    if self.request.retries >= MAX_RETRIES:
        _dead_letter(notification, result.get("error") or "unknown_error",
                     error=result.get("error") or "", retries=self.request.retries)
        notification.status = Notification.STATUS_FAILED
        notification.retry_count = self.request.retries
        notification.save(update_fields=["status", "retry_count", "updated_at"])
        _publish_notification(notification, latency_ms=latency_ms)
        return {"status": "dlq", "reason": result.get("error")}

    notification.retry_count = self.request.retries + 1
    notification.save(update_fields=["retry_count", "updated_at"])

    raise self.retry(countdown=_backoff_seconds(self.request.retries),
                     exc=Exception(result.get("error")))


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


@shared_task
def sweep_stuck_pending():
    """
    Recover PENDING notifications that were never picked up (on_commit lost,
    worker crash before dequeue) OR stalled mid-retry (worker died).
    Uses sweeper_requeue_count as a fuse to prevent infinite loops.
    """
    now = timezone.now()
    cutoff_never = now - timedelta(minutes=STUCK_NEVER_STARTED_MIN)
    cutoff_stalled = now - timedelta(minutes=STUCK_RETRY_STALLED_MIN)

    never_started = list(
        Notification.objects.filter(
            status=Notification.STATUS_PENDING,
            created_at__lt=cutoff_never,
            attempts__isnull=True,
            sweeper_requeue_count__lt=STUCK_MAX_REQUEUES,
        ).values_list("id", flat=True).distinct()[:STUCK_BATCH]
    )

    stalled = list(
        Notification.objects.filter(
            status=Notification.STATUS_PENDING,
            updated_at__lt=cutoff_stalled,
            attempts__isnull=False,
            sweeper_requeue_count__lt=STUCK_MAX_REQUEUES,
        ).values_list("id", flat=True).distinct()[:STUCK_BATCH]
    )

    requeued = 0
    dlq = 0

    for nid in never_started + stalled:
        # Atomic claim: only bump requeue_count if still PENDING
        updated = Notification.objects.filter(
            id=nid, status=Notification.STATUS_PENDING
        ).update(
            sweeper_requeue_count=models.F("sweeper_requeue_count") + 1,
            updated_at=now,
        )
        if updated == 0:
            continue   # someone else grabbed it

        notif = Notification.objects.get(id=nid)
        queue = "critical" if notif.priority == Notification.PRIORITY_CRITICAL else "default"
        deliver_notification.apply_async(args=[str(nid)], queue=queue)
        requeued += 1

    # Anything that exceeded the fuse → DLQ
    exhausted = Notification.objects.filter(
        status=Notification.STATUS_PENDING,
        sweeper_requeue_count__gte=STUCK_MAX_REQUEUES,
    )[:STUCK_BATCH]

    for notif in exhausted:
        _dead_letter(notif, "stuck_pending_max_requeues",
                     error="sweeper_exhausted", retries=notif.retry_count)
        notif.status = Notification.STATUS_FAILED
        notif.save(update_fields=["status", "updated_at"])
        dlq += 1

    return {
        "requeued": requeued,
        "dlq": dlq,
        "never_started": len(never_started),
        "stalled": len(stalled),
    }
