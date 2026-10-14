from apps.api.views import EventIngestView, RecipientWsTokenView

urlpatterns = [
    path("events/", EventIngestView.as_view(), name="event-ingest"),
    path("recipients/<uuid:recipient_id>/ws-token/", RecipientWsTokenView.as_view(),
         name="recipient-ws-token"),
]