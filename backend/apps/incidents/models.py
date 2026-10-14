import uuid
from django.db import models


class EscalationPolicy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)

    class Meta:
        db_table = "escalation_policies"


class EscalationStep(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    policy = models.ForeignKey(EscalationPolicy, on_delete=models.CASCADE, related_name="steps")
    step_order = models.IntegerField()
    channel = models.CharField(max_length=50)
    delay_minutes = models.IntegerField()
    target_user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, null=True, blank=True
    )

    class Meta:
        db_table = "escalation_steps"
        ordering = ["step_order"]
        constraints = [
            models.UniqueConstraint(fields=["policy", "step_order"], name="unique_policy_step"),
        ]


class Incident(models.Model):
    STATUS_OPEN = "OPEN"
    STATUS_ACKED = "ACKED"
    STATUS_RESOLVED = "RESOLVED"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_ACKED, "Acknowledged"),
        (STATUS_RESOLVED, "Resolved"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    policy = models.ForeignKey(EscalationPolicy, on_delete=models.RESTRICT)
    dedup_key = models.CharField(max_length=255)
    service_name = models.CharField(max_length=255)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default=STATUS_OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    acked_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "incidents"
        indexes = [models.Index(fields=["tenant", "status"])]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "dedup_key"], name="unique_tenant_dedup"),
        ]


class Event(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="events")
    idempotency_key = models.CharField(max_length=255)
    payload = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "events"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"], name="unique_tenant_idempotency"
            ),
        ]