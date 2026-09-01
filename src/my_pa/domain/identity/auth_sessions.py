"""Opaque server-session records and idle/absolute expiry arithmetic.

Defaults match the current web runtime numbers (8h absolute, 30m idle) so WP04
can wire the cookie to this store without inventing a new policy. WP02 does not
replace the live cookie.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from my_pa.domain.common.time import ensure_utc

__all__ = [
    "AUTH_SESSION_ABSOLUTE_TTL",
    "AUTH_SESSION_IDLE_TTL",
    "AuthSession",
    "IssuedAuthSession",
    "capped_idle_expiry",
    "session_is_authoritative",
]

AUTH_SESSION_ABSOLUTE_TTL: Final = timedelta(hours=8)
AUTH_SESSION_IDLE_TTL: Final = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class AuthSession:
    """Server-owned session state. The raw SID is never a field on this record."""

    id: UUID
    token_hash: str
    principal_id: UUID
    created_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None = None
    revoke_reason: str | None = None
    rotated_from_id: UUID | None = None
    superseded_by_id: UUID | None = None

    def __post_init__(self) -> None:
        if len(self.token_hash) != 64:
            raise ValueError("token_hash is a SHA-256 hex digest")
        ensure_utc(self.created_at)
        ensure_utc(self.last_seen_at)
        ensure_utc(self.idle_expires_at)
        ensure_utc(self.absolute_expires_at)
        if self.absolute_expires_at <= self.created_at:
            raise ValueError("absolute_expires_at must be after created_at")
        if self.idle_expires_at <= self.created_at:
            raise ValueError("idle_expires_at must be after created_at")
        if self.revoked_at is not None:
            ensure_utc(self.revoked_at)


@dataclass(frozen=True, slots=True)
class IssuedAuthSession:
    """Raw SID returned once at create/rotate time, plus the durable record."""

    record: AuthSession
    raw_sid: str = field(repr=False)


def capped_idle_expiry(
    *,
    now: datetime,
    idle_ttl: timedelta,
    absolute_expires_at: datetime,
) -> datetime:
    """`now + idle_ttl`, never later than absolute expiry."""
    instant = ensure_utc(now)
    absolute = ensure_utc(absolute_expires_at)
    candidate = instant + idle_ttl
    return absolute if candidate > absolute else candidate


def session_is_authoritative(session: AuthSession, *, now: datetime) -> bool:
    """Whether this row may still authorize a Principal."""
    instant = ensure_utc(now)
    return (
        session.revoked_at is None
        and session.superseded_by_id is None
        and instant < session.idle_expires_at
        and instant < session.absolute_expires_at
    )
