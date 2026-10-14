from rest_framework import serializers


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
