"""WebAuthn credential and challenge records. Persistence only; no ceremony.

WP03 owns attestation/assertion verification, `navigator.credentials`, and
registration/authentication HTTP. This module names the durable records that
store will hold so WP03 can bind a ceremony to them later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final
from uuid import UUID

from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.secret_digests import digest_bytes

__all__ = [
    "WEBAUTHN_CHALLENGE_PURPOSE_VALUES",
    "WEBAUTHN_CHALLENGE_TTL",
    "IssuedWebAuthnChallenge",
    "WebAuthnChallenge",
    "WebAuthnChallengePurpose",
    "WebAuthnCredential",
]

WEBAUTHN_CHALLENGE_TTL: Final = timedelta(minutes=5)

#: Frozen independently of the StrEnum so a later member is an explicit
#: migration, not a silent CHECK widening. The Alembic revision copies the
#: same literals; it does not import this enum (`D-69`).
WEBAUTHN_CHALLENGE_PURPOSE_VALUES: Final[tuple[str, ...]] = (
    "registration",
    "authentication",
    "credential_administration",
    "recovery",
    "step_up",
)


class WebAuthnChallengePurpose(StrEnum):
    """Why one challenge nonce was issued. Closed set for WP02 persistence."""

    REGISTRATION = "registration"
    AUTHENTICATION = "authentication"
    CREDENTIAL_ADMINISTRATION = "credential_administration"
    RECOVERY = "recovery"
    STEP_UP = "step_up"


@dataclass(frozen=True, slots=True)
class WebAuthnCredential:
    """One stored authenticator public key bound to a Principal."""

    id: UUID
    principal_id: UUID
    credential_id: bytes
    public_key: bytes
    sign_count: int
    created_at: datetime
    user_handle: bytes | None = None
    label: str | None = None
    transports: str | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    revoke_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.credential_id:
            raise ValueError("a WebAuthn credential_id is non-empty")
        if not self.public_key:
            raise ValueError("a WebAuthn public_key is non-empty")
        if self.sign_count < 0:
            raise ValueError("sign_count is non-negative")
        ensure_utc(self.created_at)
        if self.last_used_at is not None:
            ensure_utc(self.last_used_at)
        if self.revoked_at is not None:
            ensure_utc(self.revoked_at)

    @property
    def active(self) -> bool:
        return self.revoked_at is None


@dataclass(frozen=True, slots=True)
class WebAuthnChallenge:
    """One purpose-bound, expiry-bounded, one-time challenge.

    `challenge_bytes` is the nonce WP03 will bind into the ceremony. It is not
    a password. Callers must not log it.
    """

    id: UUID
    challenge_digest: str
    purpose: WebAuthnChallengePurpose
    rp_id: str
    origin: str
    created_at: datetime
    expires_at: datetime
    challenge_bytes: bytes = field(repr=False)
    principal_id: UUID | None = None
    credential_record_id: UUID | None = None
    consumed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.challenge_bytes:
            raise ValueError("a WebAuthn challenge nonce is non-empty")
        if digest_bytes(self.challenge_bytes) != self.challenge_digest:
            raise ValueError("challenge_digest must be SHA-256 of challenge_bytes")
        if not self.rp_id.strip():
            raise ValueError("rp_id is required")
        if not self.origin.strip():
            raise ValueError("origin is required")
        ensure_utc(self.created_at)
        ensure_utc(self.expires_at)
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        if self.consumed_at is not None:
            ensure_utc(self.consumed_at)

    def is_valid(
        self, *, now: datetime, purpose: WebAuthnChallengePurpose, principal_id: UUID | None
    ) -> bool:
        instant = ensure_utc(now)
        return (
            self.consumed_at is None
            and instant < self.expires_at
            and self.purpose is purpose
            and self.principal_id == principal_id
        )


@dataclass(frozen=True, slots=True)
class IssuedWebAuthnChallenge:
    """Challenge bytes returned once at issue time, plus the durable record."""

    record: WebAuthnChallenge
    challenge_bytes: bytes = field(repr=False)
