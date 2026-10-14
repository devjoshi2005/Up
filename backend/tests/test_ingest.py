import uuid

import pytest
from django.test import Client

from apps.incidents.models import Event, Incident
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db
client = Client()


def _payload(policy):
    return {
        "event_type": "error_rate_high",
        "service_name": "payments-service",
        "policy_id": str(policy.id),
        "payload": {"rate": 0.05},
    }


def test_missing_api_key_returns_401(policy):
    r = client.post("/api/v1/events/", _payload(policy), content_type="application/json")
    print(r.content)
    assert r.status_code == 401


def test_invalid_api_key_returns_401(policy):
    r = client.post(
        "/api/v1/events/", _payload(policy), content_type="application/json",
        HTTP_X_API_KEY="sk_live_boguskey0000000000000000",
    )
    print(r.content)
    assert r.status_code == 401


def test_missing_idempotency_key_returns_400(policy, api_key):
    r = client.post(
        "/api/v1/events/", _payload(policy), content_type="application/json",
        HTTP_X_API_KEY="sk_live_testkey0000000000000000000",
    )
    assert r.status_code == 400


def test_creates_incident_event_and_notification(policy, api_key):
    r = client.post(
        "/api/v1/events/", _payload(policy), content_type="application/json",
        HTTP_X_API_KEY="sk_live_testkey0000000000000000000",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert r.status_code == 202
    body = r.json()
    assert body["incident_created"] is True
    assert len(body["notification_ids"]) == 1
    assert Incident.objects.count() == 1
    assert Event.objects.count() == 1
    assert Notification.objects.count() == 1


def test_idempotency_key_returns_same_response(policy, api_key):
    key = str(uuid.uuid4())
    headers = {
        "HTTP_X_API_KEY": "sk_live_testkey0000000000000000000",
        "HTTP_IDEMPOTENCY_KEY": key,
    }
    r1 = client.post("/api/v1/events/", _payload(policy),
                     content_type="application/json", **headers)
    r2 = client.post("/api/v1/events/", _payload(policy),
                     content_type="application/json", **headers)

    assert r1.status_code == 202
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"
    assert r1.json()["event_id"] == r2.json()["event_id"]
    assert Event.objects.count() == 1


def test_dedup_key_groups_events_into_one_incident(policy, api_key):
    headers_base = {"HTTP_X_API_KEY": "sk_live_testkey0000000000000000000"}
    for _ in range(3):
        client.post(
            "/api/v1/events/", _payload(policy), content_type="application/json",
            **headers_base, HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
    assert Incident.objects.count() == 1
    assert Event.objects.count() == 3
    assert Notification.objects.count() == 1     # only step 1 fires on new incident


def test_celery_task_enqueued_on_new_incident(policy, api_key, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        client.post(
            "/api/v1/events/", _payload(policy), content_type="application/json",
            HTTP_X_API_KEY="sk_live_testkey0000000000000000000",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
    assert len(callbacks) == 1   # one on_commit → one task enqueue