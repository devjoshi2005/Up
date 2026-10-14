import uuid
from django.db import models


class User(models.Model):
    """Recipient — not the Django auth user. Dashboard login uses django.contrib.auth."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    name = models.CharField(max_length=255, blank=True)
    email = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "users"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "email"], name="unique_tenant_email"),
            models.UniqueConstraint(fields=["tenant", "phone"], name="unique_tenant_phone"),
        ]

    def __str__(self):
        return f"{self.name} <{self.email}>"


class Preference(models.Model):
    CHANNEL_CHOICES = [
        ("EMAIL", "Email"),
        ("WEBPUSH", "Web Push"),
        ("SMS", "SMS"),
        ("WEBSOCKET", "WebSocket"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    channel = models.CharField(max_length=50, choices=CHANNEL_CHOICES)
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
    timezone = models.CharField(max_length=50, default="UTC")
    is_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "preferences"
        constraints = [
            models.UniqueConstraint(fields=["user", "channel"], name="unique_user_channel"),
        ]