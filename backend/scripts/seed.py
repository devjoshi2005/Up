from apps.tenants.models import Tenant, ApiKey, generate_api_key
from apps.accounts.models import User, Preference
from apps.incidents.models import EscalationPolicy, EscalationStep

tenant, _ = Tenant.objects.get_or_create(name="Up Corp")
print(f"Tenant: {tenant.id}")

key = generate_api_key()
raw_key, prefix, key_hash = key["raw_key"], key["prefix"], key["hash"]

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

# Both email and phone are unique per tenant, so key the second recipient on
# the phone we always own — that keeps reseeding idempotent even when
# BREVO_EMAIL points at a rotating real inbox.
asha, _ = User.objects.update_or_create(
    tenant=tenant, email="asha@acme.test",
    defaults={"name": "Asha", "phone": real_phone},
)
ravi, _ = User.objects.update_or_create(
    tenant=tenant, phone="+919900000002",
    defaults={"name": "Ravi", "email": real_email},
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

# --- Dashboard members (RBAC demo: admin / operator / viewer) ---
from django.contrib.auth import get_user_model
from apps.tenants.models import TenantMember

AUTH = get_user_model()
MEMBERS = [
    ("demo@up.test", "admin", "Demo Admin"),
    ("op@up.test", "operator", "On-Call Operator"),
    ("view@up.test", "viewer", "Exec Viewer"),
    ("producer@up.test", "producer", "Payments Service"),
    ("responder@up.test", "responder", "On-Call Responder"),
]
for email, role, name in MEMBERS:
    user, created = AUTH.objects.get_or_create(
        username=email,
        defaults={"email": email, "first_name": name},
    )
    if created:
        user.set_password("demo1234")
        user.save(update_fields=["password"])
    TenantMember.objects.update_or_create(
        user=user, defaults={"tenant": tenant, "role": role},
    )
    print(f"Dashboard member: {email}/{role} {'created' if created else 'updated'}")

print("\n=== PHASE 1 COMPLETE ===")