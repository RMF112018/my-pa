"""SHA-256 hex digests for high-entropy auth secrets.

Opaque session identifiers, WebAuthn challenge nonces, and recovery codes are
machine-generated. SHA-256 plus `hmac.compare_digest` is the same storage
pattern `domain.capture.client` uses for capture-client secrets: a password KDF
does not help a uniformly random 128- or 256-bit value.

Callers persist only the hex digest. Plaintext and raw bytes exist in the
return value of the issue helpers and nowhere in a stored record.
"""

from __future__ import annotations

import hmac
import secrets
from hashlib import sha256
from typing import Final

__all__ = [
    "DIGEST_HEX_LENGTH",
    "OPAQUE_TOKEN_BYTES",
    "AuthSecretError",
    "digest_bytes",
    "digest_text",
    "digests_match",
    "encode_opaque_token",
    "issue_opaque_token",
    "parse_opaque_token",
]

DIGEST_HEX_LENGTH: Final = 64
OPAQUE_TOKEN_BYTES: Final = 32

_ABSENT_DIGEST: Final = sha256(b"\x00no such auth secret").hexdigest()
_HEX_ALPHABET: Final = frozenset("0123456789abcdef")


class AuthSecretError(ValueError):
    """A presented secret cannot be digested. Fail closed."""


def digest_bytes(value: bytes) -> str:
    """Return the lowercase SHA-256 hex digest of `value`."""
    material = bytes(value)
    if not material:
        raise AuthSecretError("an auth secret is non-empty")
    return sha256(material).hexdigest()


def digest_text(value: str) -> str:
    """Digest the UTF-8 encoding of a non-empty string."""
    if value == "":
        raise AuthSecretError("an auth secret text is a non-empty string")
    return digest_bytes(value.encode("utf-8"))


def digests_match(presented_digest: str, stored_digest: str | None) -> bool:
    """Constant-time equality, including against an absent stored digest."""
    if len(presented_digest) != DIGEST_HEX_LENGTH:
        return False
    expected = stored_digest if isinstance(stored_digest, str) else _ABSENT_DIGEST
    if len(expected) != DIGEST_HEX_LENGTH:
        expected = _ABSENT_DIGEST
    return hmac.compare_digest(presented_digest, expected)


def issue_opaque_token() -> tuple[bytes, str]:
    """Mint one CSPRNG token and its digest together as `(raw, sha256-hex)`."""
    raw = secrets.token_bytes(OPAQUE_TOKEN_BYTES)
    return raw, digest_bytes(raw)


def encode_opaque_token(raw: bytes) -> str:
    """Present raw token bytes as lowercase hex. Never a stored form."""
    if len(raw) != OPAQUE_TOKEN_BYTES:
        raise AuthSecretError("an opaque token is 32 bytes")
    return bytes(raw).hex()


def parse_opaque_token(presented: str) -> bytes:
    """Decode a presented hex SID. Refuse anything that is not 32 bytes of hex."""
    candidate = presented.strip().lower()
    if len(candidate) != OPAQUE_TOKEN_BYTES * 2:
        raise AuthSecretError("an opaque token is 32 bytes of hex")
    if any(character not in _HEX_ALPHABET for character in candidate):
        raise AuthSecretError("an opaque token is 32 bytes of hex")
    return bytes.fromhex(candidate)
