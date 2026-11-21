"""Content-integrity checks for stored communications content.

The producer's hash scope is "SHA-256 over the UTF-8 bytes of the content
exactly as stored in this record (no newline/whitespace normalization)", and its
byte count is the length of those same bytes. These functions check exactly
that and nothing more: no normalization, no decoding of entities.

A withheld body (content removed by a privacy screen) cannot be verified --
its declared digest describes content that is not here -- and that is
`NOT_VERIFIABLE_WITHHELD`, not a failure.
"""

from __future__ import annotations

import hashlib
import re
from typing import Final

from my_pa.domain.communications.model import IntegrityOutcome

__all__ = ["SHA256_HEX", "check_content", "check_text_digest", "is_sha256_hex"]

SHA256_HEX: Final = re.compile(r"[0-9a-f]{64}")


def is_sha256_hex(value: object) -> bool:
    """A lower-case 64-hex digest, the only digest form the contract declares."""
    return isinstance(value, str) and SHA256_HEX.fullmatch(value) is not None


def check_content(content: str | None, sha256: str, utf8_bytes: int) -> IntegrityOutcome:
    """Verify `content` against its declared digest and UTF-8 byte count.

    `content is None` means withheld. A string that cannot be encoded as UTF-8
    (a lone surrogate from a `\\ud800` escape) cannot match any declared digest.
    """
    if content is None:
        return IntegrityOutcome.NOT_VERIFIABLE_WITHHELD
    try:
        encoded = content.encode("utf-8")
    except UnicodeEncodeError:
        return IntegrityOutcome.MISMATCH
    if len(encoded) != utf8_bytes or hashlib.sha256(encoded).hexdigest() != sha256:
        return IntegrityOutcome.MISMATCH
    return IntegrityOutcome.VERIFIED


def check_text_digest(text: str | None, sha256: str | None) -> IntegrityOutcome:
    """Verify a derived text against an optional declared digest (no byte count declared)."""
    if text is None:
        return IntegrityOutcome.NOT_VERIFIABLE_WITHHELD
    if sha256 is None:
        return IntegrityOutcome.NOT_DECLARED
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError:
        return IntegrityOutcome.MISMATCH
    if hashlib.sha256(encoded).hexdigest() != sha256:
        return IntegrityOutcome.MISMATCH
    return IntegrityOutcome.VERIFIED
