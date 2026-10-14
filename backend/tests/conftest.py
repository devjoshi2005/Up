import hashlib

import pytest

from apps.accounts.models import User
from apps.incidents.models import EscalationPolicy, EscalationStep
from apps.tenants.models import ApiKey, Tenant

RAW_KEY = "sk_live_testkey0000000000000000000"


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name="Test Co")


@pytest.fixture
def api_key(tenant):
    return ApiKey.objects.create(
        tenant=tenant,
        prefix=RAW_KEY[:8],
        hash=hashlib.sha256(RAW_KEY.encode()).hexdigest(),
        is_active=True,
    )


@pytest.fixture
def recipient(tenant):
    return User.objects.create(
        tenant=tenant, name="Asha", email="asha@test.io", phone="+919900000001"
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