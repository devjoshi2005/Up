from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed

from apps.tenants.models import TenantMember


class TenantJWTAuthentication(JWTAuthentication):
    """JWT auth that returns a principal carrying the operator's tenant."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        try:
            member = TenantMember.objects.select_related("tenant").get(user=user)
        except TenantMember.DoesNotExist:
            raise AuthenticationFailed("User has no tenant membership")

        # Wrap in a principal so downstream code can do `request.user.tenant`
        principal = _JWPrincipal(user=user, tenant=member.tenant, role=member.role)
        return (principal, token)


class _JWPrincipal:
    def __init__(self, user, tenant, role):
        self._user = user
        self.tenant = tenant
        self.role = role
        self.id = user.id
        self.is_authenticated = True
        self.is_anonymous = False
        self.is_active = user.is_active

    def __getattr__(self, name):
        return getattr(self._user, name)

    def __str__(self):
        return f"operator:{self._user.username}@{self.tenant.id}"