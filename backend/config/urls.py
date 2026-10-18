from django.contrib import admin
from django.http import JsonResponse
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


def health(request):
    """Liveness probe — keeps the 30s uptime pollers from 404-ing in our logs."""
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("health", health, name="health"),
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("api/v1/", include("apps.api.urls")),
]
