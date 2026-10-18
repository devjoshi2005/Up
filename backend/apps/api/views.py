from django.db import IntegrityError
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from datetime import timedelta
import uuid

from django.contrib.auth import authenticate
from django.db.models import Count, Avg, ExpressionWrapper, F, DurationField, Q
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.api.serializers import (
    LoginSerializer, UserMeSerializer,
    IncidentListSerializer, IncidentDetailSerializer,
)
from apps.api.auth_jwt import TenantJWTAuthentication
from apps.api.permissions import (
    IsTenantAdmin, IsTenantMember, IsTenantOperator, IsTenantProducer, IsTenantResponder,
)
from apps.incidents.models import Incident
from apps.notifications.models import Notification


from apps.api.authentication import ApiKeyAuthentication
from apps.api.serializers import DeadLetterSerializer, EventIngestSerializer
from apps.api.throttles import TenantRateThrottle
from apps.incidents.models import EscalationPolicy, Event,Incident
from apps.incidents.services import escalate_incident, ingest_event, resolve_incident
from apps.notifications.auth import mint_ws_token
from apps.accounts.models import User

from django.utils import timezone
from django.db import transaction
from rest_framework.permissions import AllowAny

from apps.notifications.dashboard import publish_dashboard_event
from apps.notifications.models import DeadLetter, Notification
from apps.notifications.signing import sign_ack_token, verify_ack_token
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

        publish_dashboard_event(
            incident.tenant_id,
            {
                "kind": "incident.acked",
                "incident": {
                    "id": str(incident.id),
                    "service_name": incident.service_name,
                    "dedup_key": incident.dedup_key,
                    "status": incident.status,
                    "acked_at": incident.acked_at.isoformat() if incident.acked_at else None,
                },
            },
        )
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
    """Dashboard only — producers (API key) have no role and cannot enumerate DLQ."""
    authentication_classes = [TenantJWTAuthentication]
    permission_classes = [IsAuthenticated, IsTenantMember]
    serializer_class = DeadLetterSerializer

    def get_queryset(self):
        qs = DeadLetter.objects.filter(tenant=self.request.user.tenant)
        if self.request.query_params.get("resolved") == "false":
            qs = qs.filter(resolved=False)
        return qs.select_related("notification").order_by("-created_at")


class DeadLetterReplayView(APIView):
    """Sensitive config-ish action → admins only."""
    authentication_classes = [TenantJWTAuthentication]
    permission_classes = [IsAuthenticated, IsTenantAdmin]

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
    """Same sensitivity as replay → admins only."""
    authentication_classes = [TenantJWTAuthentication]
    permission_classes = [IsAuthenticated, IsTenantAdmin]

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
    permission_classes = [IsAuthenticated, IsTenantMember]

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
    permission_classes = [IsAuthenticated, IsTenantMember]

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


class ManualEscalateView(APIView):
    """Responder/operator clicked "Escalate" — next policy step fires immediately."""
    authentication_classes = [TenantJWTAuthentication]
    permission_classes = [IsAuthenticated, IsTenantResponder]

    def post(self, request, pk):
        incident = Incident.objects.filter(id=pk, tenant=request.user.tenant).first()
        if not incident:
            return Response({"detail": "not_found"}, status=404)

        result = escalate_incident(incident=incident)
        if result["status"] == "skipped":
            return Response({"detail": result["reason"]}, status=400)
        return Response(result)


class ResolveIncidentView(APIView):
    """Operator marked the fire out — RESOLVED + resolve_at (MTTR) + cancel pending."""
    authentication_classes = [TenantJWTAuthentication]
    permission_classes = [IsAuthenticated, IsTenantOperator]

    def post(self, request, pk):
        incident = Incident.objects.filter(id=pk, tenant=request.user.tenant).first()
        if not incident:
            return Response({"detail": "not_found"}, status=404)

        result = resolve_incident(incident=incident)
        # Idempotent: resolving twice just replies "already resolved".
        return Response(result)


# ---------------------------------------------------------------------------
# Demo console — lets a reviewer drive each RBAC persona from the browser.
# These are JWT endpoints for convenience; production producers still use
# `POST /api/v1/events/` with an `X-API-Key` (see DemoProducerView for the
# snippet). The responder path still acks through the *real* HMAC magic link,
# so that transport is exercised end to end.
# ---------------------------------------------------------------------------


class DemoProducerView(APIView):
    """Producer console: the policies this tenant can fire against."""
    authentication_classes = [TenantJWTAuthentication]
    permission_classes = [IsAuthenticated, IsTenantProducer]

    def get(self, request):
        policies = EscalationPolicy.objects.filter(tenant=request.user.tenant).order_by("name")
        return Response({
            "policies": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "steps": [
                        {
                            "step_order": s.step_order,
                            "channel": s.channel,
                            "delay_minutes": s.delay_minutes,
                            "target": (s.target_user.email or s.target_user.name)
                            if s.target_user else None,
                        }
                        for s in p.steps.order_by("step_order")
                    ],
                }
                for p in policies
            ],
            # The raw key is shown only once at creation, so we surface the real
            # integration shape rather than a key we no longer hold.
            "example_curl": (
                "curl -X POST http://localhost:8000/api/v1/events/ \\\n"
                "  -H 'X-API-Key: $SYSFLOW_API_KEY' \\\n"
                "  -H 'Idempotency-Key: $(uuidgen)' \\\n"
                "  -H 'Content-Type: application/json' \\\n"
                "  -d '{\"service_name\":\"payments-service\","
                "\"event_type\":\"payment_failed\",\"policy_id\":\"<policy-id>\"}'"
            ),
        })


class DemoProduceView(APIView):
    """Producer console: emit an event into the exact same pipeline as /events/."""
    authentication_classes = [TenantJWTAuthentication]
    permission_classes = [IsAuthenticated, IsTenantProducer]

    def post(self, request):
        tenant = request.user.tenant
        service_name = (request.data.get("service_name") or "").strip()
        event_type = (request.data.get("event_type") or "").strip()
        if not service_name or not event_type:
            return Response(
                {"detail": "service_name and event_type are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        policy_id = request.data.get("policy_id")
        policies = EscalationPolicy.objects.filter(tenant=tenant)
        policy = policies.filter(id=policy_id).first() if policy_id else policies.first()
        if not policy:
            return Response(
                {"detail": "No escalation policy for this tenant."},
                status=status.HTTP_404_NOT_FOUND,
            )

        dedup_key = (request.data.get("dedup_key") or "").strip() or f"{service_name}:{event_type}"

        try:
            result = ingest_event(
                tenant=tenant,
                policy=policy,
                idempotency_key=str(uuid.uuid4()),
                dedup_key=dedup_key,
                service_name=service_name,
                event_type=event_type,
                payload={"event_type": event_type, "source": "demo-console"},
            )
        except IntegrityError:
            return Response({"detail": "duplicate_event"}, status=status.HTTP_409_CONFLICT)

        return Response(
            {**result, "policy_name": policy.name},
            status=status.HTTP_201_CREATED,
        )


class DemoInboxView(APIView):
    """Responder console: open fires awaiting an ack, with the real magic link."""
    authentication_classes = [TenantJWTAuthentication]
    permission_classes = [IsAuthenticated, IsTenantResponder]

    def get(self, request):
        tenant = request.user.tenant
        incidents = (
            Incident.objects.filter(tenant=tenant, status=Incident.STATUS_OPEN)
            .select_related("policy")
            .prefetch_related("notifications__recipient", "notifications__escalation_step")
            .order_by("-created_at")[:50]
        )

        rows = []
        for inc in incidents:
            pending = [n for n in inc.notifications.all() if n.status == Notification.STATUS_PENDING]
            rows.append({
                "incident_id": str(inc.id),
                "service_name": inc.service_name,
                "dedup_key": inc.dedup_key,
                "status": inc.status,
                "policy_name": inc.policy.name,
                "created_at": inc.created_at.isoformat(),
                "ack_token": sign_ack_token(str(inc.id)),
                "pending": [
                    {
                        "id": str(n.id),
                        "channel": n.channel,
                        "step_order": n.escalation_step.step_order if n.escalation_step else None,
                        "recipient": (n.recipient.email or n.recipient.name) if n.recipient else None,
                        "escalation_due_at": n.escalation_due_at.isoformat() if n.escalation_due_at else None,
                    }
                    for n in pending
                ],
            })
        return Response(rows)


class AnalyticsView(APIView):
    authentication_classes = [TenantJWTAuthentication]
    permission_classes = [IsAuthenticated, IsTenantMember]

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