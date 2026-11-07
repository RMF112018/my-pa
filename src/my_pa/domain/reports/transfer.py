"""Bounded chunked content transfer: the pure rules (Reports Modernization WP06 B1).

A caller whose content does not fit one request uploads it in chunks to a
*transfer session* (`grxfr_`), then names the finalized session in a publish
or update. This module holds what is decided without a clock, a row or a
file, stdlib and domain only:

- the constants: the fixed chunk size (`TRANSFER_CHUNK_BYTES`, every chunk
  but the last exactly that many raw bytes, so at most `MAX_TRANSFER_CHUNKS`
  for the 16 MiB declaration bound), the session TTL bounds, the quotas;
- `TransferDeclaration`, what begin declares, validated, with its
  `intent_digest` (the begin idempotency intent);
- the chunk arithmetic: `chunk_count`, `expected_chunk_size`, `chunk_offset`;
- `client_ref_of`, the client binding of a session (`"<kind>:<creator id>"`);
- the one-use content token: `mint_content_token` and `content_token_digest`
  over `domain.identity.secret_digests` (only the digest is ever stored);
- `parse_transfer_reference`, the closed `{"transfer": {session_id,
  content_token}}` shape a publish/update content may take.

Every refusal is `ReportValidationError(field, rule)` and never carries the
value; a token never appears in a refusal, a `repr` or a digest input other
than its own.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

from my_pa.domain.common.identifiers import (
    IdKind,
    InvalidIdentifierError,
    validate_identifier,
)
from my_pa.domain.identity.secret_digests import (
    digest_bytes,
    encode_opaque_token,
    issue_opaque_token,
)
from my_pa.domain.reports.content import canonical_json
from my_pa.domain.reports.creator import ReportCreator
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.vocabulary import (
    MAX_ORIGINAL_CONTENT_BYTES,
    TRANSFER_CHUNK_MAX_BYTES,
    TRANSFER_MAX_TTL,
    ContentEncoding,
    ContentFormat,
)

__all__ = [
    "CLIENT_REF_PATTERN",
    "CONTENT_TOKEN_PATTERN",
    "CONTENT_TOKEN_PREFIX",
    "MAX_TRANSFER_BYTE_COUNT",
    "MAX_TRANSFER_CHUNKS",
    "TRANSFER_CHUNK_BYTES",
    "TRANSFER_DECLARED_BYTES_PER_OWNER",
    "TRANSFER_SESSIONS_PER_CLIENT",
    "TRANSFER_SESSIONS_PER_OWNER",
    "TRANSFER_TTL_DEFAULT_SECONDS",
    "TRANSFER_TTL_MAX_SECONDS",
    "TRANSFER_TTL_MIN_SECONDS",
    "TransferDeclaration",
    "TransferReference",
    "chunk_count",
    "chunk_offset",
    "client_ref_of",
    "content_token_digest",
    "expected_chunk_size",
    "mint_content_token",
    "parse_transfer_reference",
]

#: T2: the fixed raw size of every chunk but the last (256 KiB).
TRANSFER_CHUNK_BYTES: Final = TRANSFER_CHUNK_MAX_BYTES
#: T3: the most staged bytes one session may declare (16 MiB).
MAX_TRANSFER_BYTE_COUNT: Final = MAX_ORIGINAL_CONTENT_BYTES
#: T2: so a session has sequences 0..63.
MAX_TRANSFER_CHUNKS: Final = 64
#: T3: the session lifetime, in seconds.
TRANSFER_TTL_DEFAULT_SECONDS: Final = 3600
TRANSFER_TTL_MIN_SECONDS: Final = 300
TRANSFER_TTL_MAX_SECONDS: Final = 86400
#: T6: live sessions (open or finalized, unexpired) per (owner, client) and per
#: owner, and the sum of their declared bytes per owner (64 MiB).
TRANSFER_SESSIONS_PER_CLIENT: Final = 4
TRANSFER_SESSIONS_PER_OWNER: Final = 8
TRANSFER_DECLARED_BYTES_PER_OWNER: Final = 67_108_864

#: T4: the frozen client binding pattern; the schema restates it as a literal
#: (with the colon escaped for SQLAlchemy's bind parsing).
CLIENT_REF_PATTERN: Final = r"^(local_principal|remote_client):gcrt_[0-9a-f]{40}$"
#: T9: a presented content token. Not an `IdKind`: it is a secret, never an id.
CONTENT_TOKEN_PREFIX: Final = "grxtk"  # noqa: S105 - a prefix, not a secret
CONTENT_TOKEN_PATTERN: Final = r"^grxtk_[0-9a-f]{64}$"  # noqa: S105 - a pattern

_CONTENT_TOKEN: Final = re.compile(r"\Agrxtk_([0-9a-f]{64})\Z")
_SHA256_HEX: Final = re.compile(r"\A[0-9a-f]{64}\Z")
_REFERENCE_KEY: Final = "transfer"
_REFERENCE_INNER_KEYS: Final = frozenset({"session_id", "content_token"})

# The constants restate one another; a drift is a programming error.
if MAX_TRANSFER_CHUNKS * TRANSFER_CHUNK_BYTES != MAX_TRANSFER_BYTE_COUNT:  # pragma: no cover
    raise RuntimeError("the transfer chunk constants disagree")
if TRANSFER_MAX_TTL.total_seconds() != TRANSFER_TTL_MAX_SECONDS:  # pragma: no cover
    raise RuntimeError("the transfer TTL constants disagree")


def _is_int(value: object) -> bool:
    return type(value) is int


@dataclass(frozen=True, slots=True)
class TransferDeclaration:
    """What a begin declares: the staged bytes' format, encoding, size, digest, and the TTL.

    `byte_count` and `sha256` are of the STAGED (raw) bytes: the gzip member
    for `gzip+base64`, the content's text for `identity`. Validated at
    construction; `format` and `encoding` accept their string values.
    """

    format: ContentFormat
    encoding: ContentEncoding
    byte_count: int
    sha256: str
    ttl_seconds: int = TRANSFER_TTL_DEFAULT_SECONDS

    def __post_init__(self) -> None:
        raw_format: object = self.format
        raw_encoding: object = self.encoding
        if type(raw_format) is not str and not isinstance(raw_format, ContentFormat):
            raise ReportValidationError("format", "type")
        try:
            object.__setattr__(self, "format", ContentFormat(raw_format))
        except ValueError:
            raise ReportValidationError("format", "unknown") from None
        if type(raw_encoding) is not str and not isinstance(raw_encoding, ContentEncoding):
            raise ReportValidationError("encoding", "type")
        try:
            object.__setattr__(self, "encoding", ContentEncoding(raw_encoding))
        except ValueError:
            raise ReportValidationError("encoding", "unknown") from None
        if not _is_int(self.byte_count):
            raise ReportValidationError("byte_count", "type")
        if not 1 <= self.byte_count <= MAX_TRANSFER_BYTE_COUNT:
            raise ReportValidationError("byte_count", "bounds")
        digest: object = self.sha256
        if type(digest) is not str:
            raise ReportValidationError("sha256", "type")
        if not _SHA256_HEX.match(digest):
            raise ReportValidationError("sha256", "pattern")
        if not _is_int(self.ttl_seconds):
            raise ReportValidationError("ttl_seconds", "type")
        if not TRANSFER_TTL_MIN_SECONDS <= self.ttl_seconds <= TRANSFER_TTL_MAX_SECONDS:
            raise ReportValidationError("ttl_seconds", "bounds")

    @property
    def chunk_count(self) -> int:
        return chunk_count(self.byte_count)

    @property
    def intent_digest(self) -> str:
        """SHA-256 hex of the canonical JSON of the whole declaration, TTL included (T7)."""
        return hashlib.sha256(
            canonical_json(
                {
                    "format": self.format.value,
                    "encoding": self.encoding.value,
                    "byte_count": self.byte_count,
                    "sha256": self.sha256,
                    "ttl_seconds": self.ttl_seconds,
                }
            )
        ).hexdigest()


def chunk_count(byte_count: int) -> int:
    """How many chunks a declaration of `byte_count` staged bytes is sent in (1..64)."""
    if not _is_int(byte_count):
        raise ReportValidationError("byte_count", "type")
    if not 1 <= byte_count <= MAX_TRANSFER_BYTE_COUNT:
        raise ReportValidationError("byte_count", "bounds")
    return -(-byte_count // TRANSFER_CHUNK_BYTES)


def chunk_offset(sequence: int) -> int:
    """The byte offset chunk `sequence` (0..63) starts at."""
    if not _is_int(sequence):
        raise ReportValidationError("sequence", "type")
    if not 0 <= sequence < MAX_TRANSFER_CHUNKS:
        raise ReportValidationError("sequence", "bounds")
    return sequence * TRANSFER_CHUNK_BYTES


def expected_chunk_size(byte_count: int, sequence: int) -> int:
    """The exact raw size chunk `sequence` must have in a declaration of `byte_count`.

    Every chunk but the last is exactly `TRANSFER_CHUNK_BYTES`; the last is
    the remainder (1..`TRANSFER_CHUNK_BYTES`). A sequence past the last chunk
    is `ReportValidationError("sequence", "bounds")`.
    """
    count = chunk_count(byte_count)
    offset = chunk_offset(sequence)
    if sequence >= count:
        raise ReportValidationError("sequence", "bounds")
    return min(TRANSFER_CHUNK_BYTES, byte_count - offset)


def client_ref_of(creator: ReportCreator) -> str:
    """T4: the client a session is bound to, `"<creator kind>:<creator id>"`."""
    if not isinstance(creator, ReportCreator):
        raise ReportValidationError("creator", "type")
    return f"{creator.kind.value}:{creator.creator_id}"


def mint_content_token() -> tuple[str, str]:
    """T9: a fresh one-use content token, `(presented, digest)`.

    `presented` is `grxtk_` and 64 lowercase hex (32 CSPRNG bytes), returned
    to the caller once; `digest` is the SHA-256 hex of the raw bytes, the only
    form ever stored. `content_token_digest(presented) == digest`.
    """
    raw, digest = issue_opaque_token()
    return f"{CONTENT_TOKEN_PREFIX}_{encode_opaque_token(raw)}", digest


def content_token_digest(presented: object) -> str | None:
    """The stored-form digest of a presented token, or `None` if it is not one.

    `None` for anything but exactly `grxtk_` and 64 lowercase hex; never
    raises, and never with the value. The caller compares the digest with
    `digests_match` (constant time).
    """
    if type(presented) is not str:
        return None
    match = _CONTENT_TOKEN.match(presented)
    if match is None:
        return None
    return digest_bytes(bytes.fromhex(match.group(1)))


@dataclass(frozen=True, slots=True)
class TransferReference:
    """T10: a publish/update content that names a finalized transfer session.

    The token is kept out of `repr`.
    """

    session_id: str
    content_token: str = field(repr=False)


def _reference_session_id(value: object) -> str:
    if type(value) is not str:
        raise ReportValidationError("transfer.session_id", "type")
    try:
        return validate_identifier(value, IdKind.REPORT_TRANSFER_SESSION)
    except InvalidIdentifierError:
        raise ReportValidationError("transfer.session_id", "pattern") from None


def parse_transfer_reference(value: object) -> TransferReference | None:
    """The transfer reference `value` is, or `None` when it is not one at all.

    `None` when `value` is not a `dict` or has no `"transfer"` key (it is then
    inline content, validated as such). A `dict` with `"transfer"` must be
    exactly `{"transfer": {"session_id": "grxfr_…", "content_token":
    "grxtk_…"}}`: any other key at either level is `("transfer",
    "unknown_field")` (format and encoding come from the session, never the
    caller), a missing inner key `("transfer.<key>", "required")`, a
    malformed value `("transfer.<key>", "type" | "pattern")`.
    """
    if type(value) is not dict or _REFERENCE_KEY not in value:
        return None
    if set(value) != {_REFERENCE_KEY}:
        raise ReportValidationError(_REFERENCE_KEY, "unknown_field")
    inner = value[_REFERENCE_KEY]
    if type(inner) is not dict:
        raise ReportValidationError(_REFERENCE_KEY, "type")
    fields: Mapping[object, object] = inner
    if any(key not in _REFERENCE_INNER_KEYS for key in fields):
        raise ReportValidationError(_REFERENCE_KEY, "unknown_field")
    for key in ("session_id", "content_token"):
        if key not in fields:
            raise ReportValidationError(f"transfer.{key}", "required")
    session_id = _reference_session_id(fields["session_id"])
    token = fields["content_token"]
    if type(token) is not str:
        raise ReportValidationError("transfer.content_token", "type")
    if _CONTENT_TOKEN.match(token) is None:
        raise ReportValidationError("transfer.content_token", "pattern")
    return TransferReference(session_id=session_id, content_token=token)
