from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.incidents.models import Incident
from apps.notifications.models import DeadLetter, DeliveryAttempt, Notification
from apps.notifications.tasks import (
    _backoff_seconds, deliver_notification, sweep_stuck_pending,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _notif(tenant, policy, recipient, channel="EMAIL", priority="default",
           created_offset_min=0, attempts=None):
    incident = Incident.objects.create(
        tenant=tenant, policy=policy, dedup_key=f"k-{timezone.now().timestamp()}",
        service_name="svc",
    )
    n = Notification.objects.create(
        tenant=tenant, incident=incident, recipient=recipient,
        channel=channel, priority=priority, escalation_step=policy.steps.first(),
        escalation_due_at=timezone.now(),
        subject="s", body_text="b",
    )
    if created_offset_min:
        Notification.objects.filter(id=n.id).update(
            created_at=timezone.now() - timedelta(minutes=created_offset_min),
        )
        n.refresh_from_db()
    if attempts:
        for _ in range(attempts):
            DeliveryAttempt.objects.create(
                tenant=tenant, notification=n, channel=channel, status="FAILED",
            )
    return n


# ---- Backoff ----

def test_backoff_is_jittered_and_capped():
    samples = [_backoff_seconds(0) for _ in range(50)]
    assert min(samples) >= 1.0
    assert max(samples) <= 3.0           # 1 + jitter(1.5) = 2.5 max
    assert len(set(samples)) > 10        # jitter creates variance


def test_backoff_caps_at_300():
    assert _backoff_seconds(20) <= 300


# ---- DLQ on exhausted retries ----

@patch("apps.notifications.channels.email_brevo._client")
def test_dlq_created_after_max_retries(mock_client, tenant, policy, recipient):
    from brevo.core.api_error import ApiError
    mock_client.return_value.transactional_emails.send_transac_email.side_effect = ApiError(
        status_code=500, body={"message": "boom"},
    )

    n = _notif(tenant, policy, recipient, channel="EMAIL")
    deliver_notification.apply(args=[str(n.id)])

    n.refresh_from_db()
    assert n.status == Notification.STATUS_FAILED
    assert DeadLetter.objects.filter(notification=n).exists()
    dl = DeadLetter.objects.get(notification=n)
    assert dl.reason.startswith("brevo_500")


# ---- Stuck sweeper: never started ----

def test_sweep_requeues_never_started(tenant, policy, recipient):
    n = _notif(tenant, policy, recipient, created_offset_min=5)   # 5 min old, no attempts
    result = sweep_stuck_pending()
    assert result["requeued"] == 1
    n.refresh_from_db()
    assert n.sweeper_requeue_count == 1


def test_sweep_ignores_recent_pending(tenant, policy, recipient):
    _notif(tenant, policy, recipient)   # created just now
    result = sweep_stuck_pending()
    assert result["requeued"] == 0


# ---- Stuck sweeper: stalled retry ----

def test_sweep_requeues_stalled_retry(tenant, policy, recipient):
    n = _notif(tenant, policy, recipient, attempts=1)
    Notification.objects.filter(id=n.id).update(
        updated_at=timezone.now() - timedelta(minutes=15),
    )
    result = sweep_stuck_pending()
    assert result["requeued"] == 1


# ---- Stuck sweeper: fuse ----

def test_sweep_dlq_after_max_requeues(tenant, policy, recipient):
    n = _notif(tenant, policy, recipient, created_offset_min=5)
    Notification.objects.filter(id=n.id).update(sweeper_requeue_count=3)

    result = sweep_stuck_pending()
    assert result["dlq"] == 1
    n.refresh_from_db()
    assert n.status == Notification.STATUS_FAILED
    assert DeadLetter.objects.filter(notification=n, reason="stuck_pending_max_requeues").exists()


# ---- DLQ endpoints (RBAC: dashboard JWT only; replay/discard = admins) ----

def test_dlq_list_returns_only_tenant(client, tenant, policy, recipient, member_admin, jwt_for):
    admin = member_admin
    n = _notif(tenant, policy, recipient)
    DeadLetter.objects.create(
        tenant=tenant, notification=n, reason="x", last_error="e",
    )
    r = client.get("/api/v1/dlq/", **jwt_for(admin))
    assert r.status_code == 200
    assert len(r.json()["results"]) == 1


def test_dlq_replay(client, tenant, policy, recipient, member_admin, jwt_for):
    admin = member_admin
    n = _notif(tenant, policy, recipient)
    n.status = Notification.STATUS_FAILED
    n.save()
    dl = DeadLetter.objects.create(
        tenant=tenant, notification=n, reason="test", last_error="e",
    )
    with patch("apps.api.views.deliver_notification.apply_async") as mp:
        r = client.post(f"/api/v1/dlq/{dl.id}/replay/", **jwt_for(admin))
    assert r.status_code == 200
    assert r.json()["status"] == "requeued"
    mp.assert_called_once()
    dl.refresh_from_db()
    n.refresh_from_db()
    assert dl.resolved is True
    assert n.status == Notification.STATUS_PENDING


def test_dlq_replay_rejects_already_resolved(client, tenant, policy, recipient, member_admin, jwt_for):
    admin = member_admin
    n = _notif(tenant, policy, recipient)
    dl = DeadLetter.objects.create(
        tenant=tenant, notification=n, reason="test", resolved=True,
        resolved_at=timezone.now(),
    )
    r = client.post(f"/api/v1/dlq/{dl.id}/replay/", **jwt_for(admin))
    assert r.status_code == 400


def test_dlq_discard(client, tenant, policy, recipient, member_admin, jwt_for):
    admin = member_admin
    n = _notif(tenant, policy, recipient)
    dl = DeadLetter.objects.create(tenant=tenant, notification=n, reason="x")
    r = client.post(
        f"/api/v1/dlq/{dl.id}/discard/", {"note": "customer cancelled"},
        content_type="application/json", **jwt_for(admin),
    )
    assert r.status_code == 200
    dl.refresh_from_db()
    assert dl.resolved is True
    assert dl.resolution_note == "customer cancelled"


# Producers authenticate with an API key and have no role — RBAC (by design)
# keeps them out of every dashboard surface, including read-only DLQ.
def test_dlq_producer_api_key_rejected(client, tenant, policy, recipient, api_key):
    n = _notif(tenant, policy, recipient)
    DeadLetter.objects.create(
        tenant=tenant, notification=n, reason="x", last_error="e",
    )
    r = client.get("/api/v1/dlq/", HTTP_X_API_KEY="sk_live_testkey0000000000000000000")
    assert r.status_code == 401
