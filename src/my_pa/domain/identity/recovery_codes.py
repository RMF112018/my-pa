"""Hashed one-time recovery codes. Plaintext is never a stored field."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final
from uuid import UUID

from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.secret_digests import digest_text

__all__ = [
    "RECOVERY_CODE_ENTROPY_BYTES",
    "IssuedRecoveryCodeSet",
    "RecoveryCode",
    "RecoveryCodeSet",
    "issue_recovery_code",
    "normalize_recovery_code",
]

RECOVERY_CODE_ENTROPY_BYTES: Final = 16
_HEX: Final = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class RecoveryCodeSet:
    """One generation of recovery material for a Principal."""

    id: UUID
    principal_id: UUID
    generation: int
    created_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.generation < 1:
            raise ValueError("recovery generation is >= 1")
        ensure_utc(self.created_at)
        if self.revoked_at is not None:
            ensure_utc(self.revoked_at)

    @property
    def active(self) -> bool:
        return self.revoked_at is None


@dataclass(frozen=True, slots=True)
class RecoveryCode:
    """One hashed recovery code. The digest is the only stored secret material."""

    id: UUID
    set_id: UUID
    code_hash: str
    created_at: datetime
    consumed_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if len(self.code_hash) != 64:
            raise ValueError("recovery code_hash is a SHA-256 hex digest")
        ensure_utc(self.created_at)
        if self.consumed_at is not None:
            ensure_utc(self.consumed_at)
        if self.revoked_at is not None:
            ensure_utc(self.revoked_at)


@dataclass(frozen=True, slots=True)
class IssuedRecoveryCodeSet:
    """Plaintext codes returned once; only hashes are persisted."""

    record: RecoveryCodeSet
    codes: tuple[str, ...] = field(repr=False)


def normalize_recovery_code(presented: str) -> str:
    """Strip grouping punctuation and case so hashing is stable."""
    return "".join(character for character in presented.strip().lower() if character in _HEX)


def issue_recovery_code() -> tuple[str, str]:
    """Mint one 128-bit grouped hex code and the digest of its normalized form."""
    raw = secrets.token_bytes(RECOVERY_CODE_ENTROPY_BYTES)
    hex_digits = raw.hex()
    grouped = "-".join(hex_digits[index : index + 4] for index in range(0, len(hex_digits), 4))
    return grouped, digest_text(normalize_recovery_code(grouped))
