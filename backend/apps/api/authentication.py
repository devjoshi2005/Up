import hashlib
import secrets

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from apps.tenants.models import API_KEY_PREFIX_LEN, ApiKey


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

        prefix = raw_key[:API_KEY_PREFIX_LEN]
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        # Try the unique lookup prefix first, then the legacy 8-char scheme
        # bucket (old keys stored just "sk_live_"). The prefix is only a lookup
        # handle — the sha256 hash comparison is the real check, and it's
        # constant-time. Never `.get()` here: a prefix bucket can hold >1 row.
        prefixes = [prefix]
        if self.REQUIRED_PREFIX not in prefixes:
            prefixes.append(self.REQUIRED_PREFIX)

        for p in prefixes:
            candidates = ApiKey.objects.select_related("tenant").filter(
                prefix=p, is_active=True
            )
            for api_key in candidates:
                if secrets.compare_digest(api_key.hash, key_hash):
                    return (TenantPrincipal(api_key.tenant), api_key)

        raise AuthenticationFailed("Invalid API key.")
          