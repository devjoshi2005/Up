

import sys,os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   

import hashlib
import channels.layers
import pytest

from apps.accounts.models import User
from apps.incidents.models import EscalationPolicy, EscalationStep
from apps.tenants.models import API_KEY_PREFIX_LEN, ApiKey, Tenant


RAW_KEY = "sk_live_testkey0000000000000000000"


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name="Test Co")


# ---------- Dashboard members (RBAC) ----------
#
# Dashboard calls authenticate via JWT → _JWPrincipal carries the TenantMember
# role; API-key producers carry no role and are shut out by the permission
# classes. Helpers below create an auth user + membership and mint a Bearer.

def _auth_member(tenant, role, email, password="pw12345!"):
    # get_user_model() needs live settings, so resolve lazily.
    from django.contrib.auth import get_user_model
    from apps.tenants.models import TenantMember

    user = get_user_model().objects.create_user(username=email, email=email,
                                                password=password)
    member = TenantMember.objects.create(user=user, tenant=tenant, role=role)
    return user, member


def _jwt_headers(user):
    from rest_framework_simplejwt.tokens import RefreshToken
    return {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(user).access_token}"}


@pytest.fixture
def make_member(tenant):
    """Creates an auth user (with TenantMember role) and returns the *user* —
    never the member row, since JWT must be minted for the auth user's pk."""
    def _make(role="admin", email=None, password="pw12345!"):
        user, _member = _auth_member(tenant, role, email or f"{role}@test.io", password)
        return user
    return _make


@pytest.fixture
def member_admin(make_member):
    return make_member(role="admin")


@pytest.fixture
def member_operator(make_member):
    return make_member(role="operator")


@pytest.fixture
def member_viewer(make_member):
    return make_member(role="viewer")


@pytest.fixture
def member_producer(make_member):
    return make_member(role="producer")


@pytest.fixture
def member_responder(make_member):
    return make_member(role="responder")


@pytest.fixture
def jwt_for():
    return _jwt_headers

@pytest.fixture(autouse=True)
def channel_layer(settings):
    settings.CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }   
    channels.layers._default=None
    # NOTE: Celery tasks invoked via .apply() execute in-process regardless.
    # Do NOT force task_always_eager here: sweep_escalations/sweep_stuck_pending
    # rely on apply_async NOT running inline (see test_escalation expectations).
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
        prefix=RAW_KEY[:API_KEY_PREFIX_LEN],
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