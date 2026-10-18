from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.incidents.models import Event, Incident
from apps.notifications.models import Notification
from apps.notifications.dashboard import publish_dashboard_event
from apps.notifications.tasks import deliver_notification
from apps.notifications.signing import ack_url_for

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
            ack_link = ack_url_for(incident.id)
            body_text = (
                f"Incident {incident.id} opened for {event_type} on {service_name}.\n"
                f"Acknowledge: {ack_link}"
            )
            body_html = (
                f"<p>Incident <code>{incident.id}</code> opened for "
                f"<b>{event_type}</b> on <b>{service_name}</b>.</p>"
                f'<p><a href="{ack_link}">Acknowledge</a></p>'
            )
            first_step = policy.steps.order_by("step_order").first()
            if first_step and first_step.target_user:
                notif = Notification.objects.create(
                    body_text=body_text,
                    body_html=body_html,
                    tenant=tenant,
                    incident=incident,
                    recipient=first_step.target_user,
                    channel=first_step.channel,
                    priority=Notification.PRIORITY_CRITICAL,
                    escalation_step=first_step,
                    escalation_due_at=timezone.now()
                    + timedelta(minutes=first_step.delay_minutes),
                    subject=f"[{service_name}] {event_type}",
                )
                queue = "critical" if notif.priority == Notification.PRIORITY_CRITICAL else "default"
                notification_ids.append(str(notif.id))
                transaction.on_commit(
                    lambda nid=notif.id: deliver_notification.apply_async(
                        args=[str(nid)], queue=queue
                    )
                )

    # Fan out to dashboards only once the tx above has committed.
    if incident_created:
        publish_dashboard_event(
            tenant.id,
            {
                "kind": "incident.created",
                "incident": {
                    "id": str(incident.id),
                    "service_name": incident.service_name,
                    "dedup_key": incident.dedup_key,
                    "status": incident.status,
                    "created_at": incident.created_at.isoformat(),
                },
            },
        )

    return {
        "status": "created",
        "event_id": str(event.id),
        "incident_id": str(incident.id),
        "incident_created": incident_created,
        "notification_ids": notification_ids,
    }


def _incident_body(incident, event_type: str = "manual escalation") -> tuple[str, str, str]:
    """Text subject/body for a fresh notification, with the ack magic link."""
    ack_link = ack_url_for(incident.id)
    subject = f"[{incident.service_name}] {event_type}"
    body_text = (
        f"Incident {incident.id} opened for {event_type} on {incident.service_name}.\n"
        f"Acknowledge: {ack_link}"
    )
    body_html = (
        f"<p>Incident <code>{incident.id}</code> opened for "
        f"<b>{event_type}</b> on <b>{incident.service_name}</b>.</p>"
        f'<p><a href="{ack_link}">Acknowledge</a></p>'
    )
    return subject, body_text, body_html


def _dashboard_incident_payload(incident) -> dict:
    return {
        "id": str(incident.id),
        "service_name": incident.service_name,
        "dedup_key": incident.dedup_key,
        "status": incident.status,
        "acked_at": incident.acked_at.isoformat() if incident.acked_at else None,
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
    }


def _enqueue(notification) -> None:
    queue = "critical" if notification.priority == Notification.PRIORITY_CRITICAL else "default"
    transaction.on_commit(
        lambda nid=notification.id: deliver_notification.apply_async(
            args=[str(nid)], queue=queue
        )
    )


def escalate_incident(*, incident: Incident, event_type: str = "manual_escalation") -> dict:
    """
    Fire the NEXT policy step immediately, skipping its delay_minutes.

    Mirrors sweep_escalations: current pending notification (if any) becomes
    ESCALATED, then the following step is created PENDING with the delivery
    task enqueued via on_commit so nothing is lost on rollback.
    """
    if incident.status != Incident.STATUS_OPEN:
        return {
            "status": "skipped",
            "reason": f"incident_status_{incident.status.lower()}",
        }

    with transaction.atomic():
        # The furthest non-canceled step already dispatched for this incident.
        latest = (
            incident.notifications.select_related("escalation_step")
            .exclude(escalation_step__isnull=True)
            .order_by("-escalation_step__step_order")
            .first()
        )
        if latest is not None:
            current_step = latest.escalation_step
            subject, body_text, body_html = latest.subject, latest.body_text, latest.body_html
        else:
            current_step = None
            subject, body_text, body_html = _incident_body(incident, event_type)

        if current_step is not None:
            next_step = (
                current_step.policy.steps
                .filter(step_order__gt=current_step.step_order, target_user__isnull=False)
                .order_by("step_order")
                .first()
            )
        else:
            next_step = (
                incident.policy.steps.filter(target_user__isnull=False)
                .order_by("step_order")
                .first()
            )
        if next_step is None:
            return {
                "status": "skipped",
                "reason": "already_at_final_step",
            }

        # Everything still pending on this incident is superseded.
        pending = list(incident.notifications.filter(status=Notification.STATUS_PENDING))
        for notif in pending:
            notif.status = Notification.STATUS_ESCALATED if notif.escalation_step else Notification.STATUS_CANCELED
            notif.save(update_fields=["status", "updated_at"])

        new_notif = Notification.objects.create(
            tenant=incident.tenant,
            incident=incident,
            recipient=next_step.target_user,
            channel=next_step.channel,
            priority=Notification.PRIORITY_CRITICAL,
            escalation_step=next_step,
            # Manual trigger reaches the recorder NOW (it skips the previous
            # step's waiting window); the new step keeps its own normal
            # escalation clock so the 30s sweeper doesn't cascade it.
            escalation_due_at=timezone.now() + timedelta(minutes=next_step.delay_minutes),
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
        _enqueue(new_notif)

    publish_dashboard_event(
        incident.tenant_id,
        {
            "kind": "incident.escalated",
            "incident": _dashboard_incident_payload(incident),
            "notification": {
                "id": str(new_notif.id),
                "channel": new_notif.channel,
                "step_order": next_step.step_order,
            },
        },
    )
    return {
        "status": "escalated",
        "incident_id": str(incident.id),
        "notification_id": str(new_notif.id),
        "channel": new_notif.channel,
        "step_order": next_step.step_order,
    }


def resolve_incident(*, incident: Incident) -> dict:
    """
    The fire is out: RESOLVED, resolved_at stamped (MTTR), pending
    escalations canceled, dashboard fanned out.
    """
    if incident.status == Incident.STATUS_RESOLVED:
        return {
            "status": "skipped",
            "reason": "already_resolved",
        }

    with transaction.atomic():
        incident.status = Incident.STATUS_RESOLVED
        incident.resolved_at = timezone.now()
        incident.save(update_fields=["status", "resolved_at", "updated_at"])

        canceled = Notification.objects.filter(
            incident=incident, status=Notification.STATUS_PENDING
        ).update(status=Notification.STATUS_CANCELED, updated_at=timezone.now())

    publish_dashboard_event(
        incident.tenant_id,
        {
            "kind": "incident.resolved",
            "incident": _dashboard_incident_payload(incident),
            "canceled_notifications": canceled,
        },
    )
    return {
        "status": "resolved",
        "incident_id": str(incident.id),
        "canceled_notifications": canceled,
    }