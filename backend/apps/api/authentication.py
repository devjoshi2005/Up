import hashlib
import secrets

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from apps.tenants.models import ApiKey


class TenantPrincipal:
    """Lightweight stand-in for request.user — DRF only needs a truthy is_authenticated."""
    def __init__(self, tenant):
        self.tenant = tenant
        self.id = tenant.id
        self.is_authenticated = True
        self.is_anonymous = False
        self.is_active = True

    def __str__(self):
        return f"tenant:{self.tenant.id}"


class ApiKeyAuthentication(BaseAuthentication):
    keyword = "X-API-Key"
    REQUIRED_PREFIX = "sk_live_"

    def authenticate_header(self, request):
        # Non-None value → DRF returns 401 instead of 403 on auth failure
        return self.keyword

    def authenticate(self, request):
        raw_key = request.META.get("HTTP_X_API_KEY")
        if not raw_key:
            raise AuthenticationFailed("API key not provided.")
        if not raw_key.startswith(self.REQUIRED_PREFIX) or len(raw_key) < 16:
            raise AuthenticationFailed("Malformed API key.")

        prefix = raw_key[:8]
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        try:
            api_key = ApiKey.objects.select_related("tenant").get(
                prefix=prefix, is_active=True
            )
        except ApiKey.DoesNotExist:
            raise AuthenticationFailed("Invalid API key.")

        if not secrets.compare_digest(api_key.hash, key_hash):
            raise AuthenticationFailed("Invalid API key.")

        return (TenantPrincipal(api_key.tenant), api_key)
          