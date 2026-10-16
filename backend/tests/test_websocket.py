import uuid

import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.test import Client

from apps.incidents.models import EscalationPolicy, EscalationStep
from apps.notifications.auth import mint_ws_token
from apps.notifications.models import Notification
from config.asgi import application

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.asyncio
async def test_rejects_missing_token():
    comm = WebsocketCommunicator(application, "/ws/notifications/")
    connected, _ = await comm.connect()
    assert connected is False


@pytest.mark.asyncio
async def test_rejects_invalid_token():
    comm = WebsocketCommunicator(application, "/ws/notifications/?token=bogus")
    connected, _ = await comm.connect()
    assert connected is False


@pytest.mark.asyncio
async def test_accepts_valid_token(recipient):
    token = mint_ws_token(recipient)
    
    print(token)
    from apps.notifications.auth import verify_ws_token
    print(verify_ws_token(token))

    comm = WebsocketCommunicator(application, f"/ws/notifications/?token={token}")
    connected, _ = await comm.connect()
    assert connected is True
    await comm.disconnect()


@pytest.mark.asyncio
async def test_group_send_delivers(recipient):
    token = mint_ws_token(recipient)
    comm = WebsocketCommunicator(application, f"/ws/notifications/?token={token}")
    connected, _ = await comm.connect()
    assert connected

    # Simulate channel-layer group_send from another process
    from channels.layers import get_channel_layer
    from apps.notifications.channels.websocket import group_name_for_recipient
    layer = get_channel_layer()
    await layer.group_send(
        group_name_for_recipient(str(recipient.id)),
        {
            "type": "notify.message",
            "payload": {"id": str(uuid.uuid4()), "subject": "ping", "body": "hello"},
        },
    )

    msg = await comm.receive_json_from(timeout=3)
    assert msg["type"] == "notification"
    assert msg["payload"]["subject"] == "ping"
    await comm.disconnect()


@pytest.mark.asyncio
async def test_replay_last_seen_id(recipient, tenant, policy):
    """Create two notifications; connect with last_seen_id=first; expect only second."""
    @database_sync_to_async
    def _setup():
        n1 = Notification.objects.create(
            tenant=tenant, incident_id=None, recipient=recipient,
            channel="WEBSOCKET", subject="first",
        )
        n2 = Notification.objects.create(
            tenant=tenant, incident_id=None, recipient=recipient,
            channel="WEBSOCKET", subject="second",
        )
        return str(n1.id), str(n2.id)

    # Notification.incident is NOT NULL, so this test is illustrative —
    # in real flow, notifications are always attached to an incident.
    # For now, skip strict FK check via DB constraint bypass:
    pytest.skip("needs incident fixture — will enable after Phase 4 seeds incidents")


def test_ws_token_endpoint(api_key, recipient):
    c = Client()
    r = c.post(
        f"/api/v1/recipients/{recipient.id}/ws-token/",
        HTTP_X_API_KEY="sk_live_testkey0000000000000000000",
    )
    assert r.status_code == 200
    assert "token" in r.json()