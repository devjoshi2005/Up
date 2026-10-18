import hashlib
import secrets
import uuid
from django.db import models

# API key scheme and lookup-prefix length.
# The raw key is `sk_live_` + random. We store a *unique* lookup prefix (scheme +
# random chars) so auth can find the row with a single indexed query. Legacy keys
# only stored the 8-char scheme ("sk_live_") — auth still falls back to that.
API_KEY_SCHEME = "sk_live_"
API_KEY_PREFIX_LEN = 20


def generate_api_key() -> dict:
    """Mint a new API key: {raw_key, prefix, hash}. The raw key is shown once."""
    raw_key = API_KEY_SCHEME + secrets.token_urlsafe(32)
    return {
        "raw_key": raw_key,
        "prefix": raw_key[:API_KEY_PREFIX_LEN],
        "hash": hashlib.sha256(raw_key.encode()).hexdigest(),
    }


class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tenants"

    def __str__(self):
        return self.name


class ApiKey(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    # Unique-per-key lookup handle (scheme + random). Auth also tolerates the
    # legacy "sk_live_"-only prefix so pre-existing keys keep working; the
    # partial unique constraint below enforces uniqueness for new-style keys
    # without choking on those duplicate legacy rows.
    prefix = models.CharField(max_length=API_KEY_PREFIX_LEN, db_index=True)
    hash = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "api_keys"
        constraints = [
            models.UniqueConstraint(
                fields=["prefix"],
                condition=~models.Q(prefix=API_KEY_SCHEME),
                name="uniq_apikey_prefix_nonlegacy",
            )
        ]

from django.conf import settings


class TenantMember(models.Model):
    """
    Links a Django auth.User (dashboard operator) to a Tenant.
    Recipient model is `apps.accounts.User`; this is a different identity.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tenant_member"
    )
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="members")
    # Dashboard (JWT) personas. `producer`/`responder` are demo-facing mirrors
    # of the stateless production roles (API key / HMAC magic link) — see
    # apps/api/permissions.py for what each may do.
    role = models.CharField(
        max_length=32,
        choices=[
            ("admin", "Admin"),
            ("operator", "Operator"),
            ("viewer", "Viewer"),
            ("producer", "Producer"),
            ("responder", "Responder"),
        ],
        default="admin",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tenant_members"

    def __str__(self):
        return f"{self.user_id}@{self.tenant_id}"