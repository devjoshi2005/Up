from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.api.views import (
    AckIncidentView, EventIngestView, RecipientWsTokenView,
    DeadLetterListView, DeadLetterReplayView, DeadLetterDiscardView,
    LoginView, MeView, IncidentListView, IncidentDetailView, AnalyticsView,
)

urlpatterns = [
    # Ingestion (API key)
    path("events/", EventIngestView.as_view(), name="event-ingest"),
    path("recipients/<uuid:recipient_id>/ws-token/",
         RecipientWsTokenView.as_view(), name="recipient-ws-token"),

    # Public ack
    path("ack/<str:token>/", AckIncidentView.as_view(), name="incident-ack"),

    # DLQ (API key)
    path("dlq/", DeadLetterListView.as_view(), name="dlq-list"),
    path("dlq/<uuid:pk>/replay/", DeadLetterReplayView.as_view(), name="dlq-replay"),
    path("dlq/<uuid:pk>/discard/", DeadLetterDiscardView.as_view(), name="dlq-discard"),

    # Dashboard (JWT)
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/me/", MeView.as_view(), name="me"),
    path("incidents/", IncidentListView.as_view(), name="incidents"),
    path("incidents/<uuid:pk>/", IncidentDetailView.as_view(), name="incident-detail"),
    path("analytics/", AnalyticsView.as_view(), name="analytics"),
]