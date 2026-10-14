from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User


def mint_ws_token(user: User) -> str:
    token = AccessToken()
    token["token_type"] = "ws"
    token["recipient_id"] = str(user.id)
    token["tenant_id"] = str(user.tenant_id)
    return str(token)


def verify_ws_token(raw: str) -> dict:
    """Returns {'recipient_id': ..., 'tenant_id': ...} or raises TokenError."""
    token = AccessToken(raw)
    if token.get("token_type") != "ws":
        raise TokenError("Wrong token type")
    return {
        "recipient_id": token["recipient_id"],
        "tenant_id": token["tenant_id"],
    }