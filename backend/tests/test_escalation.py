import time
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.incidents.models import Incident
from apps.notifications.models import Notification
from apps.notifications.signing import sign_ack_token, verify_ack_token
from apps.notifications.tasks import sweep_escalations

pytestmark = pytest.mark.django_db(transaction=True)


# ---------- Signing ----------

def test_sign_and_verify_roundtrip():
    token = sign_ack_token("11111111-1111-1111-1111-111111111111")
    assert verify_ack_token(token) == "11111111-1111-1111-1111-111111111111"


def test_verify_rejects_expired():
    token = sign_ack_token("22222222-2222-2222-2222-222222222222", ttl_seconds=-1)
    with pytest.raises(ValueError, match="expired"):
        verify_ack_token(token)


def test_verify_rejects_tampered():
    token = sign_ack_token("33333333-3333-3333-3333-333333333333")
    bad = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(ValueError):
        verify_ack_token(bad)


# ---------- Ack endpoint ----------

def test_ack_endpoint_marks_incident(client, tenant, policy, recipient):
    incident = Incident.objects.create(
        tenant=tenant, policy=policy, dedup_key="k1", service_name="svc",
    )
    n = Notification.objects.create(
        tenant=tenant, incident=incident, recipient=recipient,
        channel="WEBSOCKET", escalation_step=policy.steps.first(),
        escalation_due_at=timezone.now() + timedelta(minutes=10),
        subject="s", body_text="b",
    )
    token = sign_ack_token(str(incident.id))
    r = client.get(f"/api/v1/ack/{token}/")
    assert r.status_code == 200
    assert r.json()["status"] == "acked"

    incident.refresh_from_db()
    n.refresh_from_db()
    assert incident.status == Incident.STATUS_ACKED
    assert incident.acked_at is not None
    assert n.status == Notification.STATUS_CANCELED


def test_ack_endpoint_rejects_bad_token(client):
    r = client.get("/api/v1/ack/garbage.garbage/")
    assert r.status_code == 400


# ---------- Sweeper ----------

def test_sweeper_advances_to_next_step(tenant, policy, recipient):
    incident = Incident.objects.create(
        tenant=tenant, policy=policy, dedup_key="k2", service_name="svc",
    )
    step1 = policy.steps.get(step_order=1)
    step2 = policy.steps.get(step_order=2)

    old = Notification.objects.create(
        tenant=tenant, incident=incident, recipient=recipient,
        channel=step1.channel, escalation_step=step1,
        escalation_due_at=timezone.now() - timedelta(seconds=5),
        subject="s", body_text="b",
    )

    result = sweep_escalations()
    assert result["advanced"] == 1

    old.refresh_from_db()
    assert old.status == Notification.STATUS_ESCALATED

    new = Notification.objects.exclude(id=old.id).get(incident=incident)
    assert new.escalation_step == step2
    assert new.status == Notification.STATUS_PENDING
    assert new.escalation_due_at > timezone.now()


def test_sweeper_cancels_when_incident_acked(tenant, policy, recipient):
    incident = Incident.objects.create(
        tenant=tenant, policy=policy, dedup_key="k3", service_name="svc",
        status=Incident.STATUS_ACKED, acked_at=timezone.now(),
    )
    n = Notification.objects.create(
        tenant=tenant, incident=incident, recipient=recipient,
        channel="WEBSOCKET", escalation_step=policy.steps.first(),
        escalation_due_at=timezone.now() - timedelta(seconds=5),
        subject="s", body_text="b",
    )
    result = sweep_escalations()
    assert result["canceled"] == 1
    n.refresh_from_db()
    assert n.status == Notification.STATUS_CANCELED


def test_sweeper_no_op_when_nothing_due(tenant, policy, recipient):
    incident = Incident.objects.create(
        tenant=tenant, policy=policy, dedup_key="k4", service_name="svc",
    )
    Notification.objects.create(
        tenant=tenant, incident=incident, recipient=recipient,
        channel="WEBSOCKET", escalation_step=policy.steps.first(),
        escalation_due_at=timezone.now() + timedelta(minutes=10),
        subject="s", body_text="b",
    )
    result = sweep_escalations()
    assert result == {"advanced": 0, "canceled": 0, "checked": 0}
    