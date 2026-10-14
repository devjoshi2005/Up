import uuid
from django.db import models
from django.db.models import Q


class Notification(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_SENT = "SENT"
    STATUS_DELIVERED = "DELIVERED"
    STATUS_FAILED = "FAILED"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SENT, "Sent"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_FAILED, "Failed"),
    ]
    PRIORITY_CRITICAL = "critical"
    PRIORITY_DEFAULT = "default"
    PRIORITY_DIGEST = "digest"
    PRIORITY_CHOICES = [
        (PRIORITY_CRITICAL, "Critical"),
        (PRIORITY_DEFAULT, "Default"),
        (PRIORITY_DIGEST, "Digest"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    incident = models.ForeignKey("incidents.Incident", on_delete=models.CASCADE)
    recipient = models.ForeignKey("accounts.User", on_delete=models.CASCADE)
    channel = models.CharField(max_length=50)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default=STATUS_PENDING)
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default=PRIORITY_DEFAULT)
    escalation_step = models.ForeignKey(
        "incidents.EscalationStep", on_delete=models.SET_NULL, null=True, blank=True
    )
    escalation_due_at = models.DateTimeField(null=True, blank=True)
    subject = models.CharField(max_length=255, blank=True)
    body_text = models.TextField(blank=True)
    body_html = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notifications"
        indexes = [
            models.Index(
                fields=["tenant", "status", "escalation_due_at"],
                name="idx_notifications_sweeper",
                condition=Q(status="PENDING"),
            ),
        ]


class DeliveryAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name="attempts")
    channel = models.CharField(max_length=50)
    status = models.CharField(max_length=50)
    provider_response = models.TextField(blank=True)
    latency_ms = models.IntegerField(null=True, blank=True)
    attempted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "delivery_attempts"


class DeadLetter(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE)
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dead_letters"