import uuid
from django.db import models


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
    prefix = models.CharField(max_length=8, db_index=True)
    hash = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "api_keys"

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
    role = models.CharField(max_length=32, default="admin")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tenant_members"

    def __str__(self):
        return f"{self.user_id}@{self.tenant_id}"