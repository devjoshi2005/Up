

import sys,os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   

import hashlib
import channels.layers
import pytest

from apps.accounts.models import User
from apps.incidents.models import EscalationPolicy, EscalationStep
from apps.tenants.models import ApiKey, Tenant


RAW_KEY = "sk_live_testkey0000000000000000000"


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name="Test Co")

@pytest.fixture(autouse=True)
def channel_layer(settings):
    settings.CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }   
    channels.layers._default=None
    # Celery eager — deliver_notification.apply() runs in-process,
    # no worker/beat needed. Don't propagate Retry so failure-path
    # tests can assert on DB state.
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = False
    # NOTE: quota cache intentionally left on real Redis (REDIS_URL from
    # .env) so try_consume/get_usage exercise the real backend.
    # Guarantee SMS registry uses Textlink channel regardless of env
    # SMS_PROVIDER, so real Textlink tests hit the real provider.
    from apps.notifications.channels.sms_textlink import TextlinkSMSChannel
    from apps.notifications.channels import CHANNEL_REGISTRY
    CHANNEL_REGISTRY["SMS"] = TextlinkSMSChannel()

@pytest.fixture
def api_key(tenant):
    return ApiKey.objects.create(
        tenant=tenant,
        prefix=RAW_KEY[:8],
        hash=hashlib.sha256(RAW_KEY.encode()).hexdigest(),
        is_active=True,
    )


@pytest.fixture
def recipient(tenant, settings):
    # Real receivers from .env — Brevo email + Textlink phone.
    # Falls back to dummy values only if env vars are missing.
    import os
    real_email = os.getenv("BREVO_EMAIL") or getattr(settings, "BREVO_EMAIL", "") or "asha@test.io"
    raw_phone = os.getenv("TEXTLINK_DEST") or getattr(settings, "TEXTLINK_DEST", "") or "+919900000001"
    real_phone = raw_phone.replace(" ", "").replace("-", "")
    return User.objects.create(
        tenant=tenant, name="Asha", email=real_email, phone=real_phone
    )


@pytest.fixture
def policy(tenant, recipient):
    policy = EscalationPolicy.objects.create(tenant=tenant, name="Critical")
    EscalationStep.objects.create(
        policy=policy, step_order=1, channel="WEBSOCKET",
        delay_minutes=0, target_user=recipient,
    )
    EscalationStep.objects.create(
        policy=policy, step_order=2, channel="SMS",
        delay_minutes=5, target_user=recipient,
    )
    return policy


@pytest.fixture
def auth_headers():
    return {"HTTP_X_API_KEY": RAW_KEY, "HTTP_IDEMPOTENCY_KEY": "idem-1"}