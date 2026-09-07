"""Short-lived, one-time authorization grants for authentication ceremonies.

Raw grant material is returned once in `IssuedAuthGrant.raw_grant` and is never
a stored field. Callers must not log it. Persistence keeps only `grant_digest`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final
from uuid import UUID

from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.domain.identity.secret_digests import DIGEST_HEX_LENGTH

__all__ = [
    "AUTH_GRANT_MAX_TTL",
    "AUTH_GRANT_TTL",
    "AuthGrant",
    "AuthGrantPurpose",
    "IssuedAuthGrant",
]

AUTH_GRANT_TTL: Final = timedelta(minutes=10)
AUTH_GRANT_MAX_TTL: Final = timedelta(minutes=15)
_HEX: Final = frozenset("0123456789abcdef")


class AuthGrantPurpose(StrEnum):
    BOOTSTRAP = "bootstrap"
    OPERATOR_RECOVERY = "operator_recovery"
    CREDENTIAL_ADMINISTRATION = "credential_administration"


@dataclass(frozen=True, slots=True)
class AuthGrant:
    id: UUID
    grant_digest: str = field(repr=False)
    purpose: AuthGrantPurpose
    target_principal_id: UUID
    authorizing_session_id: UUID | None
    created_at: datetime
    expires_at: datetime
    exchanged_at: datetime | None = None
    consumed_at: datetime | None = None
    revoked_at: datetime | None = None
    revoke_reason: str | None = None

    def __post_init__(self) -> None:
        if len(self.grant_digest) != DIGEST_HEX_LENGTH or any(
            character not in _HEX for character in self.grant_digest
        ):
            raise ValueError("grant_digest is a lowercase SHA-256 hex digest")
        if self.target_principal_id != LOCAL_OPERATOR_UUID:
            raise ValueError("auth grants target LOCAL_OPERATOR_UUID")
        created = ensure_utc(self.created_at)
        expires = ensure_utc(self.expires_at)
        if not created < expires <= created + AUTH_GRANT_MAX_TTL:
            raise ValueError("auth grant expiry is positive and bounded")
        if (self.consumed_at is not None) and (self.revoked_at is not None):
            raise ValueError("an auth grant cannot be consumed and revoked")
        if (self.revoked_at is None) != (self.revoke_reason is None):
            raise ValueError("revoke_reason is present exactly when revoked")
        if self.revoke_reason is not None and not self.revoke_reason.strip():
            raise ValueError("revoke_reason is present exactly when revoked")
        exchanged = None if self.exchanged_at is None else ensure_utc(self.exchanged_at)
        consumed = None if self.consumed_at is None else ensure_utc(self.consumed_at)
        revoked = None if self.revoked_at is None else ensure_utc(self.revoked_at)
        if exchanged is not None and not (created <= exchanged < expires):
            raise ValueError("exchanged_at is at or after creation and before expiry")
        if consumed is not None and consumed < created:
            raise ValueError("consumed_at is at or after creation")
        if consumed is not None and exchanged is not None and consumed < exchanged:
            raise ValueError("consumed_at is at or after exchanged_at")
        if revoked is not None and revoked < created:
            raise ValueError("revoked_at is at or after creation")
        if revoked is not None and exchanged is not None and revoked < exchanged:
            raise ValueError("revoked_at is at or after exchanged_at")
        needs_session = self.purpose is AuthGrantPurpose.CREDENTIAL_ADMINISTRATION
        if needs_session != (self.authorizing_session_id is not None):
            raise ValueError("only credential-administration grants bind a session")

    def usable_at(self, now: datetime) -> bool:
        instant = ensure_utc(now)
        return self.consumed_at is None and self.revoked_at is None and instant < self.expires_at

    def can_exchange(self, now: datetime) -> bool:
        if self.purpose is AuthGrantPurpose.CREDENTIAL_ADMINISTRATION:
            return False
        instant = ensure_utc(now)
        return (
            self.consumed_at is None
            and self.revoked_at is None
            and self.exchanged_at is None
            and instant < self.expires_at
        )

    def can_consume(self, now: datetime) -> bool:
        instant = ensure_utc(now)
        if self.consumed_at is not None or self.revoked_at is not None:
            return False
        if instant >= self.expires_at:
            return False
        if self.purpose is AuthGrantPurpose.CREDENTIAL_ADMINISTRATION:
            return True
        return self.exchanged_at is not None

    def exchanged(self, now: datetime) -> AuthGrant:
        instant = ensure_utc(now)
        if not self.can_exchange(instant):
            raise ValueError("auth grant cannot be exchanged")
        return replace(self, exchanged_at=instant)

    def consumed(self, now: datetime) -> AuthGrant:
        instant = ensure_utc(now)
        if not self.can_consume(instant):
            raise ValueError("auth grant cannot be consumed")
        return replace(self, consumed_at=instant)

    def revoked(self, now: datetime, reason: str) -> AuthGrant:
        instant = ensure_utc(now)
        if self.consumed_at is not None or self.revoked_at is not None:
            raise ValueError("auth grant cannot be revoked")
        if not reason.strip():
            raise ValueError("revoke_reason is present exactly when revoked")
        return replace(self, revoked_at=instant, revoke_reason=reason)


@dataclass(frozen=True, slots=True)
class IssuedAuthGrant:
    record: AuthGrant
    raw_grant: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.raw_grant:
            raise ValueError("issued grants include the raw value once")
