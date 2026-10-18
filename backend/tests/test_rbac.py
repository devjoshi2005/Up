import uuid

import pytest
from django.test import Client
from django.utils import timezone

from apps.incidents.models import Incident
from apps.notifications.models import DeadLetter, Notification

pytestmark = pytest.mark.django_db

client = Client()


def _incident(tenant, policy, service="payments-service", status="OPEN"):
    return Incident.objects.create(
        tenant=tenant, policy=policy, dedup_key=f"rbac-{uuid.uuid4().hex[:8]}",
        service_name=service, status=status,
    )


def _notif(incident, policy, recipient, step_order=1, status="PENDING"):
    from datetime import timedelta

    return Notification.objects.create(
        tenant=incident.tenant, incident=incident, recipient=recipient,
        channel="WEBSOCKET", status=status,
        escalation_step=policy.steps.get(step_order=step_order),
        escalation_due_at=timezone.now() + timedelta(minutes=10),
        subject=f"[{incident.service_name}] boom", body_text="b",
    )


# ---------- 1. Producer (X-API-Key) —— only POST /events/ ----------

def test_producer_cannot_read_dashboard(  # valid producer key → still no role → 401s
        tenant, policy, recipient, api_key,
):
    inc = _incident(tenant, policy)
    for method, path in [
        ("get", "/api/v1/incidents/"),
        ("get", f"/api/v1/incidents/{inc.id}/"),
        ("get", "/api/v1/analytics/?days=7"),
        ("get", "/api/v1/dlq/"),
    ]:
        r = getattr(client, method)(path, HTTP_X_API_KEY="sk_live_testkey0000000000000000000")
        assert r.status_code == 401, f"{method.upper()} {path} → {r.status_code}"

    # and it certainly can't act on incidents
    r = client.post(f"/api/v1/incidents/{inc.id}/resolve/",
                    HTTP_X_API_KEY="sk_live_testkey0000000000000000000")
    assert r.status_code == 401
    r = client.post(f"/api/v1/incidents/{inc.id}/escalate/",
                    HTTP_X_API_KEY="sk_live_testkey0000000000000000000")
    assert r.status_code == 401


def test_producer_can_still_ack_via_magic_link(tenant, policy, recipient):
    from apps.notifications.signing import sign_ack_token

    inc = _incident(tenant, policy)
    _notif(inc, policy, recipient)
    r = client.get(f"/api/v1/ack/{sign_ack_token(str(inc.id))}/")
    assert r.status_code == 200
    assert r.json()["status"] == "acked"


# ---------- 2. Responder — HMAC magic link needs no login ----------

def test_magic_link_is_stateless_and_cancels_pending(tenant, policy, recipient):
    from apps.notifications.signing import sign_ack_token

    inc = _incident(tenant, policy)
    n1 = _notif(inc, policy, recipient, step_order=1)
    r = client.get(f"/api/v1/ack/{sign_ack_token(str(inc.id))}/")
    assert r.status_code == 200

    inc.refresh_from_db()
    n1.refresh_from_db()
    assert inc.status == Incident.STATUS_ACKED
    assert inc.acked_at is not None
    assert n1.status == Notification.STATUS_CANCELED


def test_magic_link_rejects_spoofed_token(tenant, policy, recipient):
    from apps.notifications.signing import sign_ack_token

    _incident(tenant, policy)
    token = sign_ack_token("44444444-4444-4444-4444-444444444444")
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    r = client.get(f"/api/v1/ack/{tampered}/")
    assert r.status_code in (400, 404)


# ---------- 3. JWT roles (admin / operator) ----------

def test_me_reports_role(tenant, member_operator, jwt_for):
    operator = member_operator
    r = client.get("/api/v1/auth/me/", **jwt_for(operator))
    assert r.status_code == 200
    assert r.json()["role"] == "operator"


def test_expired_or_garbage_jwt_rejected():
    r = client.get("/api/v1/incidents/", HTTP_AUTHORIZATION="Bearer not.a.jwt")
    assert r.status_code == 401


# ---------- 4. Resolve ----------

def test_resolve_sets_status_and_mttr_fields(tenant, policy, recipient, member_operator, jwt_for):
    operator = member_operator
    inc = _incident(tenant, policy, status="ACKED")
    inc.acked_at = timezone.now()
    inc.save()

    _notif(inc, policy, recipient, step_order=2)

    r = client.post(f"/api/v1/incidents/{inc.id}/resolve/", **jwt_for(operator))
    assert r.status_code == 200
    assert r.json()["status"] == "resolved"

    inc.refresh_from_db()
    assert inc.status == Incident.STATUS_RESOLVED
    assert inc.resolved_at is not None
    # outstanding escalations stop with the incident
    assert not inc.notifications.filter(status=Notification.STATUS_PENDING).exists()


def test_resolve_is_idempotent(tenant, policy, recipient, member_admin, jwt_for):
    admin = member_admin
    inc = _incident(tenant, policy, status="RESOLVED")
    r = client.post(f"/api/v1/incidents/{inc.id}/resolve/", **jwt_for(admin))
    assert r.status_code == 200
    assert r.json()["status"] == "skipped"


def test_resolve_unknown_incident_404s(tenant, member_admin, jwt_for):
    admin = member_admin
    r = client.post(
        f"/api/v1/incidents/{uuid.uuid4()}/resolve/", **jwt_for(admin),
    )
    assert r.status_code == 404


# ---------- 5. Manual escalation ----------

def test_escalate_fires_next_step_immediately(tenant, policy, recipient, member_admin, jwt_for):
    admin = member_admin
    inc = _incident(tenant, policy, service="ws-rbac")
    first = _notif(inc, policy, recipient, step_order=1, status="PENDING")

    r = client.post(f"/api/v1/incidents/{inc.id}/escalate/", **jwt_for(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "escalated"
    assert body["channel"] == "SMS"          # step 2, not step 1 again
    assert body["step_order"] == 2

    first.refresh_from_db()
    assert first.status == Notification.STATUS_ESCALATED

    new = inc.notifications.get(id=body["notification_id"])
    assert new.status == Notification.STATUS_PENDING
    assert new.escalation_step.step_order == 2
    # clock starts now — the 30s sweeper must not cascade it again
    assert new.escalation_due_at > timezone.now()


def test_escalate_keeps_delivered_page_in_trace(tenant, policy, recipient, member_admin, jwt_for):
    """A step that was already SENT stays SENT; escalation only supersedes pending."""
    admin = member_admin
    inc = _incident(tenant, policy, service="ws-rbac")
    delivered = _notif(inc, policy, recipient, step_order=1, status="SENT")

    r = client.post(f"/api/v1/incidents/{inc.id}/escalate/", **jwt_for(admin))
    assert r.status_code == 200
    assert r.json()["status"] == "escalated"

    delivered.refresh_from_db()
    assert delivered.status == Notification.STATUS_SENT
    assert inc.notifications.filter(status=Notification.STATUS_PENDING,
                                    escalation_step__step_order=2).exists()


def test_escalate_at_final_step_returns_400(tenant, policy, recipient, member_admin, jwt_for):
    admin = member_admin
    inc = _incident(tenant, policy)
    _notif(inc, policy, recipient, step_order=2, status="SENT")
    r = client.post(f"/api/v1/incidents/{inc.id}/escalate/", **jwt_for(admin))
    assert r.status_code == 400
    assert r.json()["detail"] == "already_at_final_step"


def test_escalate_non_open_incident_returns_400(tenant, policy, recipient, member_operator, jwt_for):
    operator = member_operator
    inc = _incident(tenant, policy, status="RESOLVED")
    r = client.post(f"/api/v1/incidents/{inc.id}/escalate/", **jwt_for(operator))
    assert r.status_code == 400


def test_resolve_requires_dashboard_jwt(tenant, policy, recipient, member_viewer, jwt_for):
    viewer = member_viewer
    inc = _incident(tenant, policy)
    r = client.post(f"/api/v1/incidents/{inc.id}/resolve/", **jwt_for(viewer))
    assert r.status_code == 403
    inc.refresh_from_db()
    assert inc.status == Incident.STATUS_OPEN


# ---------- 6. DLQ is admin-only to act, members to read ----------

def test_dlq_actions_need_admin_role(tenant, policy, recipient, member_operator, jwt_for):
    operator = member_operator
    inc = _incident(tenant, policy)
    n = _notif(inc, policy, recipient)
    dl = DeadLetter.objects.create(tenant=tenant, notification=n, reason="brevo down")

    r = client.post(f"/api/v1/dlq/{dl.id}/replay/", **jwt_for(operator))
    assert r.status_code == 403
    r = client.post(f"/api/v1/dlq/{dl.id}/discard/", **jwt_for(operator))
    assert r.status_code == 403
    # but operators still see the queue
    r = client.get("/api/v1/dlq/", **jwt_for(operator))
    assert r.status_code == 200


def test_login_logs_operator_in_with_role(tenant, member_operator):
    operator = member_operator
    operator.set_password("op-pass-123")
    operator.save(update_fields=["password"])
    r = client.post(
        "/api/v1/auth/login/", {"email": operator.username, "password": "op-pass-123"},
        content_type="application/json",
    )
    assert r.status_code == 200
    assert "access" in r.json()


# ---------- 7. Demo console personas (producer / responder logins) ----------

def test_producer_console_and_emit(tenant, policy, recipient, member_producer, jwt_for):
    producer = member_producer
    assert client.get("/api/v1/demo/producer/", **jwt_for(producer)).status_code == 200

    r = client.post(
        "/api/v1/demo/produce/",
        {"service_name": "payments-service", "event_type": "payment_failed",
         "policy_id": str(policy.id)},
        content_type="application/json", **jwt_for(producer),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["incident_created"] is True
    inc = Incident.objects.get(id=body["incident_id"])
    assert inc.status == Incident.STATUS_OPEN
    assert inc.notifications.count() == 1


def test_demo_produce_dedupes_second_event(tenant, policy, recipient, member_producer, jwt_for):
    producer = member_producer
    payload = {"service_name": "svc", "event_type": "boom", "dedup_key": "k1",
               "policy_id": str(policy.id)}
    first = client.post("/api/v1/demo/produce/", payload,
                        content_type="application/json", **jwt_for(producer))
    second = client.post("/api/v1/demo/produce/", payload,
                         content_type="application/json", **jwt_for(producer))
    assert first.json()["incident_id"] == second.json()["incident_id"]
    assert second.json()["incident_created"] is False
    assert Incident.objects.count() == 1


def test_responder_inbox_lists_pending_and_ack_magic_link_works(
        tenant, policy, recipient, member_responder, jwt_for):
    responder = member_responder
    inc = _incident(tenant, policy)
    _notif(inc, policy, recipient, step_order=1)

    r = client.get("/api/v1/demo/inbox/", **jwt_for(responder))
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["incident_id"] == str(inc.id)
    assert rows[0]["pending"][0]["channel"] == "WEBSOCKET"

    ack = client.get(f"/api/v1/ack/{rows[0]['ack_token']}/")
    assert ack.status_code == 200
    inc.refresh_from_db()
    assert inc.status == Incident.STATUS_ACKED


def test_responder_can_escalate_but_not_resolve(tenant, policy, recipient, member_responder, jwt_for):
    responder = member_responder
    inc = _incident(tenant, policy)
    _notif(inc, policy, recipient, step_order=1)

    r = client.post(f"/api/v1/incidents/{inc.id}/escalate/", **jwt_for(responder))
    assert r.status_code == 200
    assert r.json()["step_order"] == 2

    # closing the incident stays an operator/admin action
    r = client.post(f"/api/v1/incidents/{inc.id}/resolve/", **jwt_for(responder))
    assert r.status_code == 403


def test_personas_are_shut_out_of_each_others_consoles(
        tenant, policy, recipient, member_producer, member_responder, jwt_for):
    producer, responder = member_producer, member_responder
    assert client.get("/api/v1/demo/inbox/", **jwt_for(producer)).status_code == 403
    assert client.get("/api/v1/demo/producer/", **jwt_for(responder)).status_code == 403
    assert client.post("/api/v1/demo/produce/", {}, content_type="application/json",
                       **jwt_for(responder)).status_code == 403


def test_viewer_has_no_console(tenant, policy, recipient, member_viewer, jwt_for):
    viewer = member_viewer
    assert client.get("/api/v1/demo/producer/", **jwt_for(viewer)).status_code == 403
    assert client.get("/api/v1/demo/inbox/", **jwt_for(viewer)).status_code == 403


def test_demo_console_needs_a_jwt(tenant, policy, recipient, api_key):
    assert client.get("/api/v1/demo/producer/").status_code == 401
    assert client.get("/api/v1/demo/inbox/").status_code == 401
