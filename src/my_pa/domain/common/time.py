"""UTC-aware time primitives.

All public timestamps are timezone-aware UTC and serialise as RFC 3339 with a
trailing `Z`. Naive datetimes are rejected rather than assumed to be UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["ensure_utc", "format_rfc3339", "utc_now"]


class NaiveDatetimeError(ValueError):
    """Raised when a datetime carries no timezone information."""


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Return `value` converted to UTC.

    A naive datetime is rejected: silently treating it as UTC would fabricate
    authority over an unknown offset.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise NaiveDatetimeError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def format_rfc3339(value: datetime) -> str:
    """Format `value` as RFC 3339 UTC with a `Z` suffix and microsecond precision."""
    return ensure_utc(value).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
