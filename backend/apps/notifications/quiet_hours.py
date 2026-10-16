from datetime import datetime, time
from zoneinfo import ZoneInfo

from apps.accounts.models import Preference


def is_within_quiet_hours(notification) -> bool:
    try:
        pref = Preference.objects.get(
            user=notification.recipient, channel=notification.channel
        )
    except Preference.DoesNotExist:
        return False

    if not pref.is_enabled:
        return True
    if not pref.quiet_hours_start or not pref.quiet_hours_end:
        return False

    tz = ZoneInfo(pref.timezone or "UTC")
    now_local: time = datetime.now(tz).time()

    start, end = pref.quiet_hours_start, pref.quiet_hours_end
    if start <= end:
        return start <= now_local <= end
    # overnight window (e.g., 22:00 → 06:00)
    return now_local >= start or now_local <= end