"""The opaque, grant-bound communications cursor (contract sections 14 and 16; WP4 D7, D9, R12).

Pure, standard library only. One token format serves `communications.search`
and the `communications.read` thread view: the unpadded base64url of canonical
JSON (ASCII, sorted keys, no whitespace) of

``{"v": 1, "b": <binding>, "s": <scope>, "p": <position>}``

at most 2,048 characters. It carries **no authority**: no secret and no
signature, because the server re-derives everything that grants access on
every page (the record-lineage S3 precedent, `domain/lineage/cursor.py`).

* `b` binds the token to one request: the capability, the Principal, the
  normalized request without its cursor and limit, the identifier read version
  and the cursor version. Another Principal's token or a changed filter
  re-derives another binding: the read answers `conflict` / `cursor`.
* `s` binds it to the caller's visibility: the digest of its grants on the
  `communications.*` reads and `COMMUNICATIONS_READ_GENERATION`. A mismatch is
  a revoked or changed grant, not a client error: the read answers
  `scope_changed_restart_required`.
* `p` is the last emitted item's key in the read's total order:
  - search (section 14): `[tier, rank, overlap, "<instant>", "cmsg_..."]`;
  - thread view: `["<instant>", "cmsg_..."]`.
  Instants are RFC 3339 UTC with microseconds (`2026-11-17T12:00:00.000000Z`).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

__all__ = [
    "COMMUNICATIONS_READS",
    "COMMUNICATIONS_READ_GENERATION",
    "CURSOR_VERSION",
    "MAX_CURSOR_CHARACTERS",
    "CommunicationsCursor",
    "CursorMalformedError",
    "SearchPosition",
    "ThreadPosition",
    "cursor_binding",
    "decode_cursor",
    "encode_cursor",
    "grant_digest",
    "instant_token",
    "parse_instant_token",
    "scope_digest",
    "search_position",
    "thread_position",
]

#: The `v` of every token this module writes; any other is malformed.
CURSOR_VERSION: Final = 1
#: Section 16: a token is at most this many characters.
MAX_CURSOR_CHARACTERS: Final = 2048
#: Raised when what a grant can see changes without a grant changing (for
#: example a change to how the reads scope rows); every open cursor restarts.
COMMUNICATIONS_READ_GENERATION: Final = 1
#: The reads whose grants decide what a communications cursor may continue.
COMMUNICATIONS_READS: Final = frozenset(
    {"communications.coverage", "communications.read", "communications.search"}
)

_KEYS: Final = frozenset({"v", "b", "s", "p"})
_BASE64URL: Final = re.compile(r"\A[A-Za-z0-9_-]{1,2048}\Z")
_HEX_DIGEST: Final = re.compile(r"\A[0-9a-f]{64}\Z")
_INSTANT: Final = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z")
_MESSAGE_ID: Final = re.compile(r"\Acmsg_[A-Za-z0-9]{8,64}\Z")
_INSTANT_FORMAT: Final = "%Y-%m-%dT%H:%M:%S.%fZ"
#: A rank is `floor(ts_rank_cd * 1e6)`, a non-negative bigint.
_MAX_RANK: Final = 2**63 - 1


class CursorMalformedError(ValueError):
    """The token's encoding, length, version, keys or position shape is wrong.

    The read answers `invalid_request` / `cursor`, before any binding check.
    """


@dataclass(frozen=True, slots=True, order=True)
class SearchPosition:
    """A search result's key in the section 14 order (tier, rank, overlap, time, id)."""

    tier: int
    rank: int
    overlap: int
    message_time: datetime
    message_id: str


@dataclass(frozen=True, slots=True, order=True)
class ThreadPosition:
    """A thread-view message's key: `(message_time, message_id)` ascending."""

    message_time: datetime
    message_id: str


@dataclass(frozen=True, slots=True)
class CommunicationsCursor:
    binding: str
    scope: str
    position: SearchPosition | ThreadPosition


def _canonical_bytes(document: object) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def _sha256(document: object) -> str:
    return hashlib.sha256(_canonical_bytes(document)).hexdigest()


def instant_token(value: datetime) -> str:
    """An aware instant as RFC 3339 UTC with every microsecond."""
    if value.tzinfo is None:
        raise ValueError("a cursor instant is aware")
    return value.astimezone(UTC).strftime(_INSTANT_FORMAT)


def parse_instant_token(token: object) -> datetime:
    """The inverse of `instant_token`; `CursorMalformedError` for any other shape."""
    if not isinstance(token, str) or _INSTANT.fullmatch(token) is None:
        raise CursorMalformedError("an instant is malformed")
    try:
        return datetime.strptime(token, _INSTANT_FORMAT).replace(tzinfo=UTC)
    except ValueError as error:
        raise CursorMalformedError("an instant is malformed") from error


def grant_digest(grants: Iterable[tuple[str, str | None]] | None) -> str | None:
    """SHA-256 over the caller's sorted grants on the `communications.*` reads.

    `(capability, purpose)` pairs as stored tokens (a capability-wide grant has
    purpose `None`). `None` for a local caller, which holds no grant set.
    """
    if grants is None:
        return None
    relevant = sorted(
        {(granted, purpose) for granted, purpose in grants if granted in COMMUNICATIONS_READS},
        key=lambda pair: (pair[0], "" if pair[1] is None else pair[1], pair[1] is None),
    )
    return _sha256([[granted, purpose] for granted, purpose in relevant])


def scope_digest(
    grants_digest: str | None, *, generation: int = COMMUNICATIONS_READ_GENERATION
) -> str:
    """`s`: the grant digest and the read generation, together."""
    return _sha256({"generation": generation, "grant_digest": grants_digest})


def cursor_binding(
    *,
    capability: str,
    principal_id: str,
    request: Mapping[str, object],
    identifier_version: str,
) -> str:
    """`b`: the request (without its cursor and limit) for one Principal and read version."""
    return _sha256(
        {
            "capability": capability,
            "cursor_version": CURSOR_VERSION,
            "identifier_version": identifier_version,
            "principal_id": principal_id,
            "request": dict(request),
        }
    )


def _position_document(position: SearchPosition | ThreadPosition) -> list[object]:
    if isinstance(position, SearchPosition):
        return [
            position.tier,
            position.rank,
            position.overlap,
            instant_token(position.message_time),
            position.message_id,
        ]
    return [instant_token(position.message_time), position.message_id]


def encode_cursor(cursor: CommunicationsCursor) -> str:
    """The opaque token for `cursor`; `ValueError` if it would exceed 2,048 characters."""
    payload = _canonical_bytes(
        {
            "b": cursor.binding,
            "p": _position_document(cursor.position),
            "s": cursor.scope,
            "v": CURSOR_VERSION,
        }
    )
    token = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    if len(token) > MAX_CURSOR_CHARACTERS:
        raise ValueError("a communications cursor exceeds 2048 characters")
    return token


def _integer(value: object, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise CursorMalformedError("a cursor position number is malformed")
    return value


def _message_id(value: object) -> str:
    if not isinstance(value, str) or _MESSAGE_ID.fullmatch(value) is None:
        raise CursorMalformedError("a cursor position id is malformed")
    return value


def search_position(document: object) -> SearchPosition:
    """`[tier, rank, overlap, instant, message id]`; `CursorMalformedError` otherwise."""
    if not isinstance(document, list) or len(document) != 5:
        raise CursorMalformedError("a search position is malformed")
    tier, rank, overlap, instant, message_id = document
    return SearchPosition(
        tier=_integer(tier, 1, 3),
        rank=_integer(rank, 0, _MAX_RANK),
        overlap=_integer(overlap, 0, 1_000),
        message_time=parse_instant_token(instant),
        message_id=_message_id(message_id),
    )


def thread_position(document: object) -> ThreadPosition:
    """`[instant, message id]`; `CursorMalformedError` otherwise."""
    if not isinstance(document, list) or len(document) != 2:
        raise CursorMalformedError("a thread position is malformed")
    instant, message_id = document
    return ThreadPosition(
        message_time=parse_instant_token(instant), message_id=_message_id(message_id)
    )


def decode_cursor(
    token: object, position: Callable[[object], SearchPosition | ThreadPosition]
) -> CommunicationsCursor:
    """Shape only: the decoded token, or `CursorMalformedError`.

    `position` is the read's own position parser (`search_position` or
    `thread_position`). Nothing is compared with a request, Principal or grant.
    """
    if (
        not isinstance(token, str)
        or len(token) > MAX_CURSOR_CHARACTERS
        or _BASE64URL.fullmatch(token) is None
    ):
        raise CursorMalformedError("the cursor is not base64url")
    padded = token + "=" * (-len(token) % 4)
    try:
        raw = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
        decoded = json.loads(raw.decode("ascii"))
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise CursorMalformedError("the cursor does not decode") from error
    if not isinstance(decoded, dict) or set(decoded) != _KEYS:
        raise CursorMalformedError("the cursor has the wrong keys")
    version = decoded["v"]
    if type(version) is not int or version != CURSOR_VERSION:
        raise CursorMalformedError("the cursor version is unknown")
    for key in ("b", "s"):
        value = decoded[key]
        if not isinstance(value, str) or _HEX_DIGEST.fullmatch(value) is None:
            raise CursorMalformedError("a cursor digest is malformed")
    return CommunicationsCursor(
        binding=decoded["b"], scope=decoded["s"], position=position(decoded["p"])
    )
