import json
import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from rest_framework_simplejwt.exceptions import TokenError

from apps.accounts.models import User
from apps.notifications.auth import verify_ws_token
from apps.notifications.channels.websocket import group_name_for_recipient
from apps.notifications.models import Notification

logger = logging.getLogger(__name__)

REPLAY_LIMIT = 20


class NotificationConsumer(AsyncJsonWebsocketConsumer):

    async def connect(self):
        qs = parse_qs(self.scope["query_string"].decode())
        token = (qs.get("token") or [None])[0]
        last_seen_id = (qs.get("last_seen_id") or [None])[0]

        if not token:
            await self.close(code=4401)
            return
        try:
            claims = verify_ws_token(token)
        except TokenError:
            await self.close(code=4401)
            return
        except Exception as e:
            import traceback
            traceback.print_exc()
            await self.close(code=4401)
            return

        recipient = await self._get_recipient(claims["recipient_id"], claims["tenant_id"])
        if recipient is None:
            await self.close(code=4403)
            return

        self.recipient_id = str(recipient.id)
        self.group_name = group_name_for_recipient(self.recipient_id)

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Replay missed notifications
        replay = await self._fetch_replay(self.recipient_id, last_seen_id)
        for payload in replay:
            await self.send_json({"type": "replay", "payload": payload})

    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # ---- Channel-layer handler ----
    async def notify_message(self, event):
        await self.send_json({"type": "notification", "payload": event["payload"]})

    # ---- DB helpers ----
    @database_sync_to_async
    def _get_recipient(self, recipient_id, tenant_id):
        return User.objects.filter(id=recipient_id, tenant_id=tenant_id).first()

    @database_sync_to_async
    def _fetch_replay(self, recipient_id, last_seen_id):
        qs = Notification.objects.filter(recipient_id=recipient_id).order_by("-created_at")
        if last_seen_id:
            anchor = Notification.objects.filter(id=last_seen_id).only("created_at").first()
            if anchor:
                qs = qs.filter(created_at__gt=anchor.created_at)

        rows = list(qs[:REPLAY_LIMIT])
        rows.reverse()  # oldest first
        return [
            {
                "id": str(n.id),
                "incident_id": str(n.incident_id),
                "channel": n.channel,
                "subject": n.subject,
                "body": n.body_text,
                "created_at": n.created_at.isoformat(),
                "sent_at": int(n.created_at.timestamp() * 1000),
            }
            for n in rows
        ]