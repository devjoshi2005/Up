from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.incidents.models import Event, Incident
from apps.notifications.models import Notification
from apps.notifications.tasks import deliver_notification


def ingest_event(
    *,
    tenant,
    policy,
    idempotency_key: str,
    dedup_key: str,
    service_name: str,
    event_type: str,
    payload: dict,
) -> dict:
    """
    Transactional outbox: Event + Incident + Notification(PENDING) in one DB tx.
    Celery enqueue fires via transaction.on_commit — no lost tasks on rollback.
    """
    with transaction.atomic():
        incident, incident_created = Incident.objects.get_or_create(
            tenant=tenant,
            dedup_key=dedup_key,
            defaults={
                "policy": policy,
                "service_name": service_name,
                "status": Incident.STATUS_OPEN,
            },
        )

        event = Event.objects.create(
            tenant=tenant,
            incident=incident,
            idempotency_key=idempotency_key,
            payload={"event_type": event_type, **(payload or {})},
        )

        notification_ids: list[str] = []
        if incident_created:
            first_step = policy.steps.order_by("step_order").first()
            if first_step and first_step.target_user:
                notif = Notification.objects.create(
                    tenant=tenant,
                    incident=incident,
                    recipient=first_step.target_user,
                    channel=first_step.channel,
                    priority=Notification.PRIORITY_CRITICAL,
                    escalation_step=first_step,
                    escalation_due_at=timezone.now()
                    + timedelta(minutes=first_step.delay_minutes),
                    subject=f"[{service_name}] {event_type}",
                    body_text=f"Incident {incident.id} opened for {event_type} on {service_name}.",
                )
                notification_ids.append(str(notif.id))
                transaction.on_commit(
                    lambda nid=notif.id: deliver_notification.apply_async(
                        args=[str(nid)], queue="critical"
                    )
                )

        return {
            "status": "created",
            "event_id": str(event.id),
            "incident_id": str(incident.id),
            "incident_created": incident_created,
            "notification_ids": notification_ids,
        }