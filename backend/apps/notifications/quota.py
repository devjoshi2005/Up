from datetime import date

from django.conf import settings
from django.core.cache import cache


def _key(tenant_id) -> str:
    return f"brevo_quota:{tenant_id}:{date.today().isoformat()}"


def get_usage(tenant_id) -> int:
    return int(cache.get(_key(tenant_id)) or 0)


def try_consume(tenant_id, count: int = 1) -> bool:
    """Atomic-ish increment; returns False if quota exhausted."""
    key = _key(tenant_id)
    try:
        current = cache.incr(key, count)
    except ValueError:
        cache.add(key, count, timeout=86400)
        current = count
    if current > settings.BREVO_DAILY_QUOTA:
        cache.decr(key, count)   # roll back
        return False
    return True