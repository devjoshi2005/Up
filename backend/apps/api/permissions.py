from rest_framework.permissions import BasePermission


# Role tiers. Producers/responders authenticate differently in production
# (API key / HMAC magic link), but a demo console logs them in with a JWT so a
# reviewer can drive each persona from a browser. The tiers below are what
# actually gate the endpoints.

DASHBOARD_ROLES = ("admin", "operator", "viewer")
PRODUCER_ROLES = ("producer", "operator", "admin")
RESPONDER_ROLES = ("responder", "operator", "admin")
OPERATOR_ROLES = ("operator", "admin")


def role_of(user) -> str | None:
    """The active role of the caller, or None for producers/anonymous users.

    Dashboard JWT principals (`_JWPrincipal`) always carry a `role` lifted from
    TenantMember. API-key principals (`TenantPrincipal`) never do — so any
    `role`-gated permission here automatically shuts API-key callers out of
    every role-gated surface.
    """
    role = getattr(user, "role", None)
    return role if isinstance(role, str) else None


class IsTenantAdmin(BasePermission):
    """Only tenant admins may pass (e.g. DLQ replay/discard)."""

    def has_permission(self, request, view):
        return role_of(request.user) == "admin"


class IsTenantOperator(BasePermission):
    """Admins and operators — resolving incidents."""

    def has_permission(self, request, view):
        return role_of(request.user) in OPERATOR_ROLES


class IsTenantResponder(BasePermission):
    """Responders plus operators/admins — acknowledge/escalate a fire."""

    def has_permission(self, request, view):
        return role_of(request.user) in RESPONDER_ROLES


class IsTenantProducer(BasePermission):
    """Producers plus operators/admins — emit alerts into the pipeline."""

    def has_permission(self, request, view):
        return role_of(request.user) in PRODUCER_ROLES


class IsTenantMember(BasePermission):
    """Dashboard members (admin/operator/viewer) — read-only dashboard data."""

    def has_permission(self, request, view):
        return role_of(request.user) in DASHBOARD_ROLES
