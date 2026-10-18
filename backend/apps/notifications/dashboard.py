import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def group_name_for_tenant(tenant_id) -> str:
    """Channel-layer group every dashboard connection for a tenant joins."""
    return f"dashboard.{tenant_id}"


def publish_dashboard_event(tenant_id, event: dict) -> None:
    """Best-effort fan-out of an event to dashboards watching this tenant.

    Dashboards are a live-view convenience, not part of the delivery guarantee,
    so this never raises — a broken channel layer must not fail the write path.
    """
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            group_name_for_tenant(tenant_id),
            {"type": "dashboard.message", "event": event},
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("dashboard fan-out failed")
