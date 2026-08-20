"""Alert severity rules, kept free of I/O so they stay cheap to test."""

import enum


class Severity(enum.StrEnum):
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


_ORDER = {Severity.WARNING: 10, Severity.ERROR: 20, Severity.CRITICAL: 30}
ICONS = {Severity.WARNING: "⚠️", Severity.ERROR: "🔴", Severity.CRITICAL: "🚨"}

#: Notify on these occurrence numbers inside the dedup window, then every
#: NOTIFY_EVERY. A ten-minute Zalo outage stays a handful of messages instead of
#: hundreds, while a worsening problem still surfaces.
NOTIFY_AT = (1, 10, 100)
NOTIFY_EVERY = 500


def coerce(value: str | Severity) -> Severity:
    try:
        return Severity(str(value).upper())
    except ValueError:
        return Severity.ERROR


def meets_threshold(severity: str | Severity, minimum: str | Severity) -> bool:
    return _ORDER[coerce(severity)] >= _ORDER[coerce(minimum)]


def should_notify(occurrence: int, *, notify_from: int = 1) -> bool:
    """Decide whether this occurrence deserves a message.

    ``notify_from`` stays silent until a problem has repeated that many times,
    which is how failed logins avoid alerting on a single typo.
    """
    if occurrence < notify_from:
        return False
    rank = occurrence - notify_from + 1
    return rank in NOTIFY_AT or rank % NOTIFY_EVERY == 0
