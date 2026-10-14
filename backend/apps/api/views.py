from django.db import IntegrityError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.authentication import ApiKeyAuthentication
from apps.api.serializers import EventIngestSerializer
from apps.api.throttles import TenantRateThrottle
from apps.incidents.models import EscalationPolicy, Event
from apps.incidents.services import ingest_event
from apps.notifications.auth import mint_ws_token
from apps.accounts.models import User


class RecipientWsTokenView(APIView):
    """Server-to-server: SDK calls this with the API key to obtain a WS JWT for a recipient."""
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, recipient_id):
        tenant = request.user.tenant
        recipient = User.objects.filter(id=recipient_id, tenant=tenant).first()
        if not recipient:
            return Response({"detail": "Recipient not found."}, status=404)
        return Response({"token": mint_ws_token(recipient)})


class EventIngestView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [TenantRateThrottle]

    def post(self, request):
        serializer = EventIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return Response(
                {"detail": "Idempotency-Key header is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tenant = request.user.tenant

        policy = EscalationPolicy.objects.filter(
            id=data["policy_id"], tenant=tenant
        ).first()
        if not policy:
            return Response(
                {"detail": "Policy not found for this tenant."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            result = ingest_event(
                tenant=tenant,
                policy=policy,
                idempotency_key=idempotency_key,
                dedup_key=data["dedup_key"],
                service_name=data["service_name"],
                event_type=data["event_type"],
                payload=data["payload"],
            )
            return Response(result, status=status.HTTP_202_ACCEPTED)

        except IntegrityError:
            # Duplicate Idempotency-Key — return the original response.
            existing = Event.objects.select_related("incident").get(
                tenant=tenant, idempotency_key=idempotency_key
            )
            return Response(
                {
                    "status": "duplicate",
                    "event_id": str(existing.id),
                    "incident_id": str(existing.incident_id),
                },
                status=status.HTTP_200_OK,
            )