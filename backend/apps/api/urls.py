from apps.api.views import EventIngestView, RecipientWsTokenView,AckIncidentView
from django.urls import path

urlpatterns = [
    path("events/", EventIngestView.as_view(), name="event-ingest"),
    path("recipients/<uuid:recipient_id>/ws-token/", RecipientWsTokenView.as_view(),
         name="recipient-ws-token"),
    path("ack/<str:token>/", AckIncidentView.as_view(), name="incident-ack")
]