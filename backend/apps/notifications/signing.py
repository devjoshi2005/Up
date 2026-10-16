import base64
import hashlib
import hmac
import json
import time

from django.conf import settings


def _b64_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

def _b64_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign_ack_token(incident_id: str, ttl_seconds: int | None = None) -> str:
    ttl = ttl_seconds if ttl_seconds is not None else settings.ACK_TOKEN_TTL_SECONDS
    payload = {"iid": str(incident_id), "exp": int(time.time()) + ttl}
    payload_b64 = _b64_encode(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(settings.HMAC_SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64_encode(sig)}"


def verify_ack_token(token: str) -> str:
    try:
        payload_b64, sig_b64 = token.split(".")
    except ValueError:
        raise ValueError("malformed_token")

    expected = _b64_encode(
        hmac.new(settings.HMAC_SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(expected, sig_b64):
        raise ValueError("invalid_signature")

    payload = json.loads(_b64_decode(payload_b64))
    if payload["exp"] < time.time():
        raise ValueError("expired")
    return payload["iid"]


def ack_url_for(incident_id: str) -> str:
    return f"{settings.PUBLIC_BASE_URL}/api/v1/ack/{sign_ack_token(incident_id)}/"