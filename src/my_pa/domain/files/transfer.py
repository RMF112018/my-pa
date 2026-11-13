"""Upload and download tickets: the pure rules (contract sections 1.4, 5, 7, 8, 10).

What is decided without a clock, a row or a file, stdlib and domain only:

- the ticket token (`gfwtk_` + 64 lowercase hex): `mint_ticket_token`,
  `ticket_token_digest` and `ticket_token_from_authorization`, over
  `domain.identity.secret_digests`; only the digest is ever stored;
- the opaque ids of the plane (`fwupl`, `fwdnl`, `fwver`, `fwtrs`, `fwrcp`),
  the `IdKind` members;
- `UploadDeclaration` (optional size and sha256, TTL) and `validate_ttl`;
- the upload offset arithmetic and the strict `Upload-Offset` and
  `Upload-Complete: sha256=<hex>, length=<n>` header grammars;
- the finalize comparison (`verify_staged`, `digest_mismatch`);
- the single-range `Range` grammar (`bytes=a-b`, `a-`, `-n`), with an
  unsatisfiable range distinguished from a malformed one;
- `write_intent_digest`, the idempotency intent of a write, which refuses a raw
  token among its arguments.

Every refusal names a field and a closed code and never the value; a token is
never in a refusal, a `repr` or any digest input other than its own.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.files.errors import (
    FilesArgumentError,
    FilesRefusal,
    RangeNotSatisfiableError,
)
from my_pa.domain.files.vocabulary import (
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_CHUNK_BYTES,
    TICKET_TTL_DEFAULT_SECONDS,
    TICKET_TTL_MAX_SECONDS,
    TICKET_TTL_MIN_SECONDS,
    FilesReason,
)
from my_pa.domain.identity.secret_digests import (
    digest_bytes,
    encode_opaque_token,
    issue_opaque_token,
)
from my_pa.domain.reports.content import canonical_json

__all__ = [
    "DOWNLOAD_ID_PREFIX",
    "RECEIPT_ID_PREFIX",
    "TICKET_TOKEN_PATTERN",
    "TICKET_TOKEN_PREFIX",
    "TRASH_ITEM_ID_PREFIX",
    "UPLOAD_ID_PREFIX",
    "VERSION_ID_PREFIX",
    "ByteRange",
    "UploadCompletion",
    "UploadDeclaration",
    "advance_upload_offset",
    "check_upload_offset",
    "mint_ticket_token",
    "parse_file_id",
    "parse_range",
    "parse_upload_complete",
    "parse_upload_offset",
    "ticket_token_digest",
    "ticket_token_from_authorization",
    "validate_sha256",
    "validate_ttl",
    "verify_staged",
    "write_intent_digest",
]

#: Section 1.4: a presented ticket token. A secret, never an `IdKind`.
TICKET_TOKEN_PREFIX: Final = "gfwtk"  # noqa: S105 - a prefix, not a secret
TICKET_TOKEN_PATTERN: Final = r"^gfwtk_[0-9a-f]{64}$"  # noqa: S105 - a pattern
_TICKET_TOKEN: Final = re.compile(r"\Agfwtk_([0-9a-f]{64})\Z")
_BEARER_PREFIX: Final = "Bearer "

#: Section 1.3 prefixes: the `IdKind` members (WP5); the shape is
#: `domain.common.identifiers`' (`<prefix>_` + 8-64 alphanumerics).
UPLOAD_ID_PREFIX: Final = IdKind.FILE_UPLOAD.value
DOWNLOAD_ID_PREFIX: Final = IdKind.FILE_DOWNLOAD.value
VERSION_ID_PREFIX: Final = IdKind.FILE_VERSION.value
TRASH_ITEM_ID_PREFIX: Final = IdKind.FILE_TRASH_ITEM.value
RECEIPT_ID_PREFIX: Final = IdKind.FILE_RECEIPT.value
_ID_PREFIXES: Final = frozenset(
    {
        UPLOAD_ID_PREFIX,
        DOWNLOAD_ID_PREFIX,
        VERSION_ID_PREFIX,
        TRASH_ITEM_ID_PREFIX,
        RECEIPT_ID_PREFIX,
    }
)
_ID_SUFFIX: Final = re.compile(r"\A[A-Za-z0-9]{8,64}\Z")

_SHA256_HEX: Final = re.compile(r"\A[0-9a-f]{64}\Z")
#: A decimal byte count: ASCII digits only (`int` would also take Unicode digits,
#: signs, underscores and whitespace), no leading zero, at most 19 digits.
_COUNT: Final = r"(?:0|[1-9][0-9]{0,18})"
_UPLOAD_OFFSET: Final = re.compile(rf"\A{_COUNT}\Z")
_UPLOAD_COMPLETE: Final = re.compile(rf"\Asha256=([0-9a-f]{{64}}), length=({_COUNT})\Z")
_RANGE: Final = re.compile(r"\Abytes=(?:([0-9]{1,19})-([0-9]{0,19})|-([0-9]{1,19}))\Z")


def _is_int(value: object) -> bool:
    return type(value) is int


# --- ticket tokens -------------------------------------------------------------


def mint_ticket_token() -> tuple[str, str]:
    """A fresh ticket token, `(presented, digest)`.

    `presented` is `gfwtk_` and 64 lowercase hex (32 CSPRNG bytes), returned
    once; `digest` is the SHA-256 hex of the raw bytes, the only stored form.
    `ticket_token_digest(presented) == digest`.
    """
    raw, digest = issue_opaque_token()
    return f"{TICKET_TOKEN_PREFIX}_{encode_opaque_token(raw)}", digest


def ticket_token_digest(presented: object) -> str | None:
    """The stored-form digest of a presented token, or `None` if it is not one.

    Never raises. The caller compares with `digests_match` (constant time).
    """
    if type(presented) is not str:
        return None
    match = _TICKET_TOKEN.match(presented)
    if match is None:
        return None
    return digest_bytes(bytes.fromhex(match.group(1)))


def ticket_token_from_authorization(header: object) -> str | None:
    """The token of an exact `Authorization: Bearer gfwtk_…` value, else `None`.

    One space, the scheme spelled `Bearer`, nothing before or after: any other
    shape is `None` (the route answers `ticket_invalid`). Never raises.
    """
    if type(header) is not str or not header.startswith(_BEARER_PREFIX):
        return None
    token = header[len(_BEARER_PREFIX) :]
    return token if _TICKET_TOKEN.match(token) is not None else None


def parse_file_id(value: object, prefix: str) -> str | None:
    """`value` if it is an id of the plane with exactly `prefix`, else `None`; never raises."""
    if prefix not in _ID_PREFIXES:
        raise ValueError("not a file workspace id prefix")
    if type(value) is not str or len(value) > len(prefix) + 1 + 64:
        return None
    head, separator, suffix = value.partition("_")
    if head != prefix or separator != "_" or _ID_SUFFIX.match(suffix) is None:
        return None
    return value


# --- declarations ----------------------------------------------------------------


def validate_sha256(value: object, field: str = "sha256") -> str:
    """64 lowercase hex characters, unchanged."""
    if type(value) is not str:
        raise FilesArgumentError(field, "type")
    if _SHA256_HEX.match(value) is None:
        raise FilesArgumentError(field, "pattern")
    return value


def validate_ttl(value: object, field: str = "ttl_seconds") -> int:
    """A ticket TTL in seconds: `None` is the default 3600, else 300..86400."""
    if value is None:
        return TICKET_TTL_DEFAULT_SECONDS
    if type(value) is not int:
        raise FilesArgumentError(field, "type")
    if not TICKET_TTL_MIN_SECONDS <= value <= TICKET_TTL_MAX_SECONDS:
        raise FilesArgumentError(field, "bounds")
    return value


def _validate_limit(max_upload_bytes: object) -> int:
    if type(max_upload_bytes) is not int:
        raise FilesArgumentError("max_upload_bytes", "type")
    if max_upload_bytes < 0:
        raise FilesArgumentError("max_upload_bytes", "bounds")
    return max_upload_bytes


@dataclass(frozen=True, slots=True)
class UploadDeclaration:
    """What `files.upload.begin` declares about the bytes to come.

    `size` and `sha256` are optional (`None` when not declared); a declared
    size is 0 (zero-byte files are valid) up to `max_upload_bytes`, beyond
    which it is `too_large`. `ttl_seconds` is resolved (`None` → 3600).
    """

    size: int | None
    sha256: str | None
    ttl_seconds: int

    @classmethod
    def of(
        cls,
        *,
        size: object = None,
        sha256: object = None,
        ttl_seconds: object = None,
        max_upload_bytes: object = MAX_UPLOAD_BYTES,
    ) -> UploadDeclaration:
        limit = _validate_limit(max_upload_bytes)
        declared_size: int | None = None
        if size is not None:
            if type(size) is not int:
                raise FilesArgumentError("size", "type")
            if size < 0:
                raise FilesArgumentError("size", "bounds")
            if size > limit:
                raise FilesRefusal("size", FilesReason.TOO_LARGE)
            declared_size = size
        declared_sha256 = None if sha256 is None else validate_sha256(sha256)
        return cls(
            size=declared_size,
            sha256=declared_sha256,
            ttl_seconds=validate_ttl(ttl_seconds),
        )


# --- offsets and the byte-route headers ---------------------------------------------


def parse_upload_offset(header: object) -> int:
    """The `Upload-Offset` header value: a strict decimal byte count."""
    if type(header) is not str:
        raise FilesArgumentError("Upload-Offset", "type")
    if _UPLOAD_OFFSET.match(header) is None:
        raise FilesArgumentError("Upload-Offset", "pattern")
    return int(header)


def check_upload_offset(presented: int, current: int) -> None:
    """Section 10: a PATCH must start at exactly the staged offset (`offset_mismatch`)."""
    if not (_is_int(presented) and _is_int(current)):
        raise FilesArgumentError("Upload-Offset", "type")
    if presented != current:
        raise FilesRefusal("Upload-Offset", FilesReason.OFFSET_MISMATCH)


def advance_upload_offset(
    current: int,
    chunk_bytes: int,
    *,
    declared_size: int | None,
    max_upload_bytes: int = MAX_UPLOAD_BYTES,
) -> int:
    """The staged offset after appending `chunk_bytes` at `current`.

    `too_large` when one request exceeds 32 MiB, or when the result would pass
    the declared size (it could never finalize) or the upload ceiling.
    """
    limit = _validate_limit(max_upload_bytes)
    if not (_is_int(current) and _is_int(chunk_bytes)):
        raise FilesArgumentError("Upload-Offset", "type")
    if current < 0 or chunk_bytes < 0:
        raise FilesArgumentError("Upload-Offset", "bounds")
    if chunk_bytes > MAX_UPLOAD_CHUNK_BYTES:
        raise FilesRefusal("body", FilesReason.TOO_LARGE)
    after = current + chunk_bytes
    if after > limit or (declared_size is not None and after > declared_size):
        raise FilesRefusal("body", FilesReason.TOO_LARGE)
    return after


@dataclass(frozen=True, slots=True)
class UploadCompletion:
    """What finalize asserts about the staged bytes: their length and SHA-256."""

    sha256: str
    length: int


def parse_upload_complete(header: object) -> UploadCompletion:
    """The closed `Upload-Complete: sha256=<64 lowercase hex>, length=<n>` grammar.

    Exactly that order, one comma and one space, no other parameter.
    """
    if type(header) is not str:
        raise FilesArgumentError("Upload-Complete", "type")
    match = _UPLOAD_COMPLETE.match(header)
    if match is None:
        raise FilesArgumentError("Upload-Complete", "pattern")
    return UploadCompletion(sha256=match.group(1), length=int(match.group(2)))


def verify_staged(
    completion: UploadCompletion,
    declaration: UploadDeclaration,
    *,
    staged_length: int,
    staged_sha256: str,
) -> None:
    """Section 5: finalize's arguments, the declaration and the staged bytes agree.

    Any disagreement is `digest_mismatch`, and the target is left untouched.
    """
    if completion.length != staged_length or completion.sha256 != staged_sha256:
        raise FilesRefusal("sha256", FilesReason.DIGEST_MISMATCH)
    if declaration.size is not None and declaration.size != staged_length:
        raise FilesRefusal("sha256", FilesReason.DIGEST_MISMATCH)
    if declaration.sha256 is not None and declaration.sha256 != staged_sha256:
        raise FilesRefusal("sha256", FilesReason.DIGEST_MISMATCH)


@dataclass(frozen=True, slots=True)
class ByteRange:
    """An inclusive, satisfiable byte range `start..end` of a file of `size` bytes."""

    start: int
    end: int
    size: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    @property
    def content_range(self) -> str:
        """The `Content-Range` value of a 206 response."""
        return f"bytes {self.start}-{self.end}/{self.size}"


def parse_range(header: object, size: int) -> ByteRange | None:
    """A single `Range: bytes=a-b | a- | -n` against a file of `size` bytes.

    `None` when there is no header (serve the whole file, 200). A malformed or
    multi-range value is `FilesArgumentError("Range", "pattern")`; a well-formed
    one the file cannot satisfy (a start at or past the end, `-0`, any range of
    an empty file) is `RangeNotSatisfiableError` (416). An end past the file is
    clamped; a suffix longer than the file is the whole file.
    """
    if not _is_int(size) or size < 0:
        raise FilesArgumentError("size", "bounds")
    if header is None:
        return None
    if type(header) is not str:
        raise FilesArgumentError("Range", "type")
    match = _RANGE.match(header)
    if match is None:
        raise FilesArgumentError("Range", "pattern")
    first, last, suffix = match.groups()
    if suffix is not None:
        count = int(suffix)
        if count == 0 or size == 0:
            raise RangeNotSatisfiableError
        return ByteRange(start=max(size - count, 0), end=size - 1, size=size)
    start = int(first)
    if last:
        end = int(last)
        if end < start:
            raise FilesArgumentError("Range", "pattern")
    else:
        end = size - 1
    if start >= size:
        raise RangeNotSatisfiableError
    return ByteRange(start=start, end=min(end, size - 1), size=size)


# --- idempotency intent ----------------------------------------------------------------


def write_intent_digest(capability: str, arguments: Mapping[str, object]) -> str:
    """SHA-256 hex of the canonical JSON of a write's capability and normalized arguments.

    The idempotency key itself is not part of the intent (it scopes the receipt).
    A key ending in `_token` is refused: an intent binds a token's digest
    (`ticket_token_digest`, under a `*_token_sha256` key), never the raw token.
    """
    if type(capability) is not str or not capability.startswith("files."):
        raise FilesArgumentError("capability", "pattern")
    if not isinstance(arguments, Mapping):
        raise FilesArgumentError("arguments", "type")
    for key in arguments:
        if type(key) is not str:
            raise FilesArgumentError("arguments", "type")
        if key == "idempotency_key" or key.endswith("_token"):
            raise FilesArgumentError("arguments", "pattern")
    try:
        document = canonical_json({"capability": capability, "arguments": dict(arguments)})
    except (TypeError, ValueError):
        raise FilesArgumentError("arguments", "type") from None
    return hashlib.sha256(document).hexdigest()
