import uuid
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.accounts.models import Preference, PushSubscription
from apps.incidents.models import Incident
from apps.notifications.channels import CHANNEL_REGISTRY
from apps.notifications.channels.sms_mock import MockSMSChannel
from apps.notifications.models import DeliveryAttempt, Notification
from apps.notifications.quota import get_usage, try_consume
from apps.notifications.tasks import deliver_notification
from brevo.core.api_error import ApiError


pytestmark = pytest.mark.django_db(transaction=True)


def _make_notification(tenant, policy, recipient, channel="EMAIL", priority="default"):
    # Unique dedup_key per test run — avoids collisions with --reuse-db.
    incident = Incident.objects.create(
        tenant=tenant, policy=policy, dedup_key=f"k-{channel}-{priority}-{uuid.uuid4().hex[:8]}",
        service_name="svc",
    )
    return Notification.objects.create(
        tenant=tenant, incident=incident, recipient=recipient,
        channel=channel, priority=priority, escalation_step=policy.steps.first(),
        escalation_due_at=timezone.now(),
        subject="Test Subject", body_text="Test body real-run", body_html="<p>Test body real-run</p>",
    )


def _assert_real_brevo_config(settings):
    assert settings.BREVO_API_KEY, "BREVO_API_KEY missing — check backend/.env"
    assert settings.BREVO_SENDER_EMAIL, "BREVO_SENDER_EMAIL missing — check backend/.env"


def _assert_real_textlink_config(settings):
    assert settings.TEXTLINK_API_KEY, "TEXTLINK_API_KEY missing — check backend/.env"


# ---- Brevo email (REAL API, REAL receiver from .env BREVO_EMAIL) ----

def test_brevo_email_success(tenant, policy, recipient, settings):
    """Real Brevo send to BREVO_EMAIL. Uses real BREVO_API_KEY from .env."""
    _assert_real_brevo_config(settings)
    assert recipient.email == settings.BREVO_EMAIL, (
        f"recipient.email={recipient.email!r} != BREVO_EMAIL={settings.BREVO_EMAIL!r}"
    )

    n = _make_notification(tenant, policy, recipient, channel="EMAIL")
    result = deliver_notification.apply(args=[str(n.id)]).get()

    assert result["status"] == "sent", f"real Brevo send failed: {result}"
    n.refresh_from_db()
    assert n.status == Notification.STATUS_SENT
    assert DeliveryAttempt.objects.filter(notification=n, status="SENT").exists()


@patch("apps.notifications.channels.email_brevo._client")
def test_brevo_email_api_error_triggers_failure(mock_client, tenant, policy, recipient, settings):
    """Failure injection only — simulates Brevo 500 without spending quota."""
    mock_client.return_value.transactional_emails.send_transac_email.side_effect = ApiError(
        status_code=500, body={"message": "server error"}
    )

    n = _make_notification(tenant, policy, recipient, channel="EMAIL")
    deliver_notification.apply(args=[str(n.id)])

    n.refresh_from_db()
    assert n.status in (Notification.STATUS_PENDING, Notification.STATUS_FAILED)
    assert DeliveryAttempt.objects.filter(notification=n, status="FAILED").exists()



# ---- Textlink SMS (REAL API, REAL receiver from .env TEXTLINK_DEST) ----

def test_textlink_sms_success(tenant, policy, recipient, settings):
    """Real Textlink send to TEXTLINK_DEST. Uses real TEXTLINK_API_KEY from .env."""
    _assert_real_textlink_config(settings)
    expected = settings.TEXTLINK_DEST.replace(" ", "").replace("-", "")
    assert recipient.phone == expected, (
        f"recipient.phone={recipient.phone!r} != TEXTLINK_DEST={settings.TEXTLINK_DEST!r}"
    )

    n = _make_notification(tenant, policy, recipient, channel="SMS", priority="critical")
    result = deliver_notification.apply(args=[str(n.id)]).get()

    assert result["status"] == "sent", f"real Textlink send failed: {result}"


# ---- Mock SMS fallback (no network) ----

def test_mock_sms_channel(tenant, policy, recipient, settings):
    adapter = MockSMSChannel()
    n = _make_notification(tenant, policy, recipient, channel="SMS")
    assert adapter.send(n)["success"] is True


# ---- Web Push ----

@patch("apps.notifications.channels.webpush.webpush")
def test_webpush_success(mock_push, tenant, policy, recipient, settings):
    # WebPush still mocked — no real browser subscription exists in tests.
    # VAPID keys come from real .env (not overridden).
    assert settings.VAPID_PRIVATE_KEY, "VAPID_PRIVATE_KEY missing — check backend/.env"
    PushSubscription.objects.create(
        user=recipient, endpoint="https://push.example/abc",
        p256dh="p", auth="a",
    )
    n = _make_notification(tenant, policy, recipient, channel="WEBPUSH", priority="critical")
    result = deliver_notification.apply(args=[str(n.id)]).get()
    assert result["status"] == "sent"
    mock_push.assert_called_once()


def test_webpush_no_subscription(tenant, policy, recipient, settings):
    assert settings.VAPID_PRIVATE_KEY, "VAPID_PRIVATE_KEY missing — check backend/.env"
    n = _make_notification(tenant, policy, recipient, channel="WEBPUSH", priority="critical")
    result = deliver_notification.apply(args=[str(n.id)]).get()
    assert result["status"] == "dlq"

@patch("apps.notifications.channels.sms_textlink.tl.sendSMS")
def test_textlink_sms_api_error(mock_send, tenant, policy, recipient, settings):
    """Failure injection only — simulates bad-number error without sending SMS."""
    mock_send.side_effect = Exception("bad number")

    n = _make_notification(tenant, policy, recipient, channel="SMS", priority="critical")
    deliver_notification.apply(args=[str(n.id)])
    n.refresh_from_db()
    assert n.status in (Notification.STATUS_PENDING, Notification.STATUS_FAILED)

# ---- Quota (REAL Redis backend from .env REDIS_URL) ----

def test_quota_consumes_and_blocks(tenant, settings):
    settings.BREVO_DAILY_QUOTA = 3
    assert try_consume(tenant.id) is True
    assert try_consume(tenant.id) is True
    assert try_consume(tenant.id) is True
    assert try_consume(tenant.id) is False
    assert get_usage(tenant.id) == 3


def test_critical_email_bypasses_quota(tenant, policy, recipient, settings):
    """Real Brevo send with quota=0 — critical priority must bypass quota."""
    _assert_real_brevo_config(settings)
    settings.BREVO_DAILY_QUOTA = 0
    n = _make_notification(tenant, policy, recipient, channel="EMAIL", priority="critical")
    result = deliver_notification.apply(args=[str(n.id)]).get()
    assert result["status"] == "sent", f"real Brevo critical send failed: {result}"


# ---- Registry sanity ----

def test_channel_registry_has_all_channels():
    for ch in ("WEBSOCKET", "EMAIL", "SMS", "WEBPUSH"):
        assert ch in CHANNEL_REGISTRY
