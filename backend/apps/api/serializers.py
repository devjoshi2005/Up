from rest_framework import serializers

from apps.notifications.models import DeadLetter
from apps.incidents.models import Incident
from apps.notifications.models import Notification, DeliveryAttempt
from apps.accounts.models import User

class EventIngestSerializer(serializers.Serializer):
    event_type = serializers.CharField(max_length=100)
    service_name = serializers.CharField(max_length=255)
    dedup_key = serializers.CharField(max_length=255, required=False, allow_blank=True)
    policy_id = serializers.UUIDField()
    payload = serializers.JSONField(required=False, default=dict)

    def validate(self, attrs):
        if not attrs.get("dedup_key"):
            attrs["dedup_key"] = f"{attrs['service_name']}:{attrs['event_type']}"
        return attrs


class DeadLetterSerializer(serializers.ModelSerializer):
    notification_channel = serializers.CharField(source="notification.channel", read_only=True)
    notification_subject = serializers.CharField(source="notification.subject", read_only=True)

    class Meta:
        model = DeadLetter
        fields = [
            "id", "notification", "notification_channel", "notification_subject",
            "reason", "last_error", "retry_count", "resolved", "resolution_note",
            "resolved_at", "created_at",
        ]




class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class UserMeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    tenant_id = serializers.UUIDField()
    tenant_name = serializers.CharField()
    role = serializers.CharField()


class IncidentListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Incident
        fields = ["id", "dedup_key", "service_name", "status",
                  "created_at", "acked_at", "resolved_at"]


class DeliveryAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryAttempt
        fields = ["id", "channel", "status", "provider_response",
                  "latency_ms", "attempted_at"]


class NotificationTraceSerializer(serializers.ModelSerializer):
    attempts = DeliveryAttemptSerializer(many=True, read_only=True)
    recipient_email = serializers.CharField(source="recipient.email", read_only=True)
    recipient_phone = serializers.CharField(source="recipient.phone", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id", "channel", "status", "priority",
            "recipient_id", "recipient_email", "recipient_phone",
            "subject", "escalation_due_at", "retry_count",
            "sweeper_requeue_count",
            "created_at", "updated_at", "attempts",
        ]


class IncidentDetailSerializer(serializers.ModelSerializer):
    notifications = NotificationTraceSerializer(many=True, read_only=True)
    policy_name = serializers.CharField(source="policy.name", read_only=True)

    class Meta:
        model = Incident
        fields = [
            "id", "dedup_key", "service_name", "status", "policy_name",
            "created_at", "acked_at", "resolved_at",
            "notifications",
        ]


class IncidentListWithRecipientSerializer(serializers.ModelSerializer):
    recipient_email = serializers.CharField(source="recipient.email", read_only=True)
    class Meta:
        model = Notification
        fields = ["id", "recipient_email", "channel", "status", "priority"]