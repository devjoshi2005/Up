import hashlib
import secrets
from apps.tenants.models import Tenant, ApiKey
from apps.accounts.models import User, Preference
from apps.incidents.models import EscalationPolicy, EscalationStep

tenant, _ = Tenant.objects.get_or_create(name="Up Corp")
print(f"Tenant: {tenant.id}")

raw_key = "sk_live_" + secrets.token_urlsafe(32)
prefix = raw_key[:8]
key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

ApiKey.objects.update_or_create(
    tenant=tenant, prefix=prefix,
    defaults={"hash": key_hash, "is_active": True},
)
print(f"API Key (save this): {raw_key}")

from django.conf import settings

# Real receivers from .env so escalation lands on a real inbox/phone:
#   step 2 (SMS)   -> Asha.phone
#   step 3 (EMAIL) -> Ravi.email
real_phone = getattr(settings, "TEXTLINK_DEST", "") or "+919900000001"
real_email = getattr(settings, "BREVO_EMAIL", "") or "ravi@acme.test"

asha, _ = User.objects.update_or_create(
    tenant=tenant, email="asha@acme.test",
    defaults={"name": "Asha", "phone": real_phone},
)
ravi, _ = User.objects.update_or_create(
    tenant=tenant, email=real_email,
    defaults={"name": "Ravi", "phone": "+919900000002"},
)
print(f"Users: {asha.id}, {ravi.id}")
print(f"  Asha.phone (SMS dest) = {asha.phone}")
print(f"  Ravi.email (EMAIL dest) = {ravi.email}")

# Preferences
for u in (asha, ravi):
    for ch in ("EMAIL", "WEBSOCKET", "SMS"):
        Preference.objects.get_or_create(user=u, channel=ch)

# --- Escalation Policy ---
policy, _ = EscalationPolicy.objects.get_or_create(tenant=tenant, name="Critical Alerts")

steps_data = [
    (1, "WEBSOCKET", 0,  asha),
    (2, "SMS",       5,  asha),
    (3, "EMAIL",     10, ravi),
]
for order, channel, delay, target in steps_data:
    EscalationStep.objects.update_or_create(
        policy=policy, step_order=order,
        defaults={"channel": channel, "delay_minutes": delay, "target_user": target},
    )
print(f"Policy: {policy.id} with {policy.steps.count()} steps")

print("\n=== PHASE 1 COMPLETE ===")