from django.db import IntegrityError
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from datetime import timedelta

from django.contrib.auth import authenticate
from django.db.models import Count, Avg, ExpressionWrapper, F, DurationField, Q
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.api.serializers import (
    LoginSerializer, UserMeSerializer,
    IncidentListSerializer, IncidentDetailSerializer,
)
from apps.api.auth_jwt import TenantJWTAuthentication
from apps.incidents.models import Incident
from apps.notifications.models import Notification


from apps.api.authentication import ApiKeyAuthentication
from apps.api.serializers import DeadLetterSerializer, EventIngestSerializer
from apps.api.throttles import TenantRateThrottle
from apps.incidents.models import EscalationPolicy, Event,Incident
from apps.incidents.services import ingest_event
from apps.notifications.auth import mint_ws_token
from apps.accounts.models import User

from django.utils import timezone
from django.db import transaction
from rest_framework.permissions import AllowAny

from apps.notifications.models import DeadLetter, Notification
from apps.notifications.signing import verify_ack_token
from apps.notifications.tasks import deliver_notification


class AckIncidentView(APIView):
    """
    Public endpoint (no auth) — the HMAC signature IS the auth.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            incident_id = verify_ack_token(token)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            try:
                incident = Incident.objects.select_for_update().get(id=incident_id)
            except Incident.DoesNotExist:
                return Response({"detail": "not_found"}, status=status.HTTP_404_NOT_FOUND)

            if incident.status == Incident.STATUS_RESOLVED:
                return Response({"status": "already_resolved", "incident_id": str(incident.id)})

            if incident.status != Incident.STATUS_ACKED:
                incident.status = Incident.STATUS_ACKED
                incident.acked_at = timezone.now()
                incident.save(update_fields=["status", "acked_at", "updated_at"])

            Notification.objects.filter(
                incident=incident, status=Notification.STATUS_PENDING
            ).update(status=Notification.STATUS_CANCELED, updated_at=timezone.now())

        return Response({"status": "acked", "incident_id": str(incident.id)})

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


class DeadLetterListView(ListAPIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = DeadLetterSerializer

    def get_queryset(self):
        qs = DeadLetter.objects.filter(tenant=self.request.user.tenant)
        if self.request.query_params.get("resolved") == "false":
            qs = qs.filter(resolved=False)
        return qs.select_related("notification").order_by("-created_at")


class DeadLetterReplayView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            dl = DeadLetter.objects.select_related("notification").get(
                id=pk, tenant=request.user.tenant
            )
        except DeadLetter.DoesNotExist:
            return Response({"detail": "not_found"}, status=404)

        if dl.resolved:
            return Response({"detail": "already_resolved"}, status=400)

        notif = dl.notification
        if notif.status not in (Notification.STATUS_FAILED, Notification.STATUS_PENDING):
            return Response({"detail": f"cannot_replay_status_{notif.status}"}, status=400)

        notif.status = Notification.STATUS_PENDING
        notif.retry_count = 0
        notif.sweeper_requeue_count = 0
        notif.save(update_fields=["status", "retry_count", "sweeper_requeue_count", "updated_at"])

        deliver_notification.apply_async(args=[str(notif.id)], queue="default")

        dl.resolved = True
        dl.resolved_at = timezone.now()
        dl.resolution_note = "replayed"
        dl.save(update_fields=["resolved", "resolved_at", "resolution_note"])

        return Response({"status": "requeued", "notification_id": str(notif.id)})


class DeadLetterDiscardView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            dl = DeadLetter.objects.get(id=pk, tenant=request.user.tenant)
        except DeadLetter.DoesNotExist:
            return Response({"detail": "not_found"}, status=404)
        if dl.resolved:
            return Response({"detail": "already_resolved"}, status=400)

        dl.resolved = True
        dl.resolved_at = timezone.now()
        dl.resolution_note = request.data.get("note", "discarded")
        dl.save(update_fields=["resolved", "resolved_at", "resolution_note"])
        return Response({"status": "discarded"})



class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = authenticate(username=s.validated_data["email"],
                            password=s.validated_data["password"])
        if not user:
            return Response({"detail": "invalid_credentials"}, status=401)

        refresh = RefreshToken.for_user(user)
        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        })


class MeView(APIView):
    authentication_classes = [TenantJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserMeSerializer({
            "id": request.user.id,
            "email": request.user._user.email or request.user._user.username,
            "tenant_id": request.user.tenant.id,
            "tenant_name": request.user.tenant.name,
            "role": request.user.role,
        }).data)


class IncidentListView(APIView):
    authentication_classes = [TenantJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = request.user.tenant
        qs = Incident.objects.filter(tenant=tenant).order_by("-created_at")

        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        service = request.query_params.get("service")
        if service:
            qs = qs.filter(service_name=service)

        limit = min(int(request.query_params.get("limit", 50)), 200)
        qs = qs[:limit]
        return Response(IncidentListSerializer(qs, many=True).data)


class IncidentDetailView(APIView):
    authentication_classes = [TenantJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        tenant = request.user.tenant
        incident = (
            Incident.objects
            .filter(id=pk, tenant=tenant)
            .select_related("policy")
            .prefetch_related("notifications__attempts", "notifications__recipient")
            .first()
        )
        if not incident:
            return Response({"detail": "not_found"}, status=404)
        return Response(IncidentDetailSerializer(incident).data)


class AnalyticsView(APIView):
    authentication_classes = [TenantJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = request.user.tenant
        days = int(request.query_params.get("days", 7))
        since = timezone.now() - timedelta(days=days)

        incidents = Incident.objects.filter(tenant=tenant, created_at__gte=since)

        # MTTA / MTTR
        durations = incidents.aggregate(
            mtta=Avg(ExpressionWrapper(F("acked_at") - F("created_at"),
                                       output_field=DurationField())),
            mttr=Avg(ExpressionWrapper(F("resolved_at") - F("created_at"),
                                       output_field=DurationField())),
        )

        total = incidents.count()
        acked = incidents.filter(acked_at__isnull=False).count()
        ack_rate = round((acked / total) * 100, 1) if total else 0.0

        # Noisiest services
        noisy = list(
            incidents.values("service_name")
            .annotate(count=Count("id"))
            .order_by("-count")[:5]
        )

        # Channel breakdown (notification-level)
        channels = list(
            Notification.objects.filter(tenant=tenant, created_at__gte=since)
            .values("channel")
            .annotate(total=Count("id"),
                      sent=Count("id", filter=Q(status="SENT")),
                      failed=Count("id", filter=Q(status="FAILED")))
            .order_by("-total")
        )

        # Daily volume
        from django.db.models.functions import TruncDate
        daily = list(
            incidents.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(count=Count("id"))
            .order_by("day")
        )

        def fmt_duration(td):
            return int(td.total_seconds()) if td else None

        return Response({
            "window_days": days,
            "total_incidents": total,
            "acked_incidents": acked,
            "ack_rate": ack_rate,
            "mtta_seconds": fmt_duration(durations["mtta"]),
            "mttr_seconds": fmt_duration(durations["mttr"]),
            "noisiest_services": noisy,
            "channel_breakdown": channels,
            "daily_volume": [
                {"day": d["day"].isoformat(), "count": d["count"]} for d in daily
            ],
        })