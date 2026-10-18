from django.urls import re_path

from apps.notifications.consumers import DashboardConsumer, NotificationConsumer

websocket_urlpatterns = [
    re_path(r"^ws/notifications/$", NotificationConsumer.as_asgi()),
    re_path(r"^ws/dashboard/$", DashboardConsumer.as_asgi()),
]