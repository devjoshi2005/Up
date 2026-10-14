from rest_framework.throttling import SimpleRateThrottle


class TenantRateThrottle(SimpleRateThrottle):
    scope = "tenant"

    def get_cache_key(self, request, view):
        if not getattr(request.user, "is_authenticated", False):
            return None
        return f"throttle_tenant_{request.user.tenant.id}"
        