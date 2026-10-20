"""The opaque, grant-bound lineage cursor (record lineage S3 contract section 5).

Pure. One token format serves `records.lineage` and `issues.timeline`: the
unpadded base64url of canonical JSON (the `record_events.list` encoding: ASCII,
sorted keys, no whitespace) of

``{"v": 1, "b": <binding>, "s": <scope>, "k": <T_k>, "t": <T_v>, "n": <N>,
"r": <rcev_ or null>, "p": <position>}``

at most 2048 characters. It carries **no authority** (section 12, D-02): no
HMAC and no secret, because the server re-derives everything that grants
access on every page.

* `b` binds the token to one request: the capability, the Principal, the parsed
  request without its cursor, and the frozen cuts `k`, `t`, `n`, `r`. Another
  Principal's token or a changed filter re-derives another binding
  (`conflict` / `cursor`); an edited cut does too, because `b` covers it.
* `s` binds it to the caller's visibility: the digest of its grants on the
  lineage family reads and on the called capability, and the read generation
  `LINEAGE_READ_GENERATION`. A mismatch is not a client error but a revoked or
  changed grant: the read answers `scope_changed_restart_required`.
* `p` is the last emitted item's key, which neither `b` nor `s` covers; the
  read decides what an absent `p` means (section 7.2 step 7).

Instants are RFC 3339 UTC with microseconds (`2026-10-19T12:00:00.000000Z`),
the form every S3 answer reports a cut in, so a cut passed back reads exactly
the same facts.
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

from my_pa.domain.lineage.vocabulary import LINEAGE_FAMILY_READS, LINEAGE_READ_GENERATION

__all__ = [
    "CURSOR_VERSION",
    "MAX_CURSOR_CHARACTERS",
    "CursorMalformedError",
    "LineageCursor",
    "canonical_bytes",
    "cursor_binding",
    "decode_cursor",
    "encode_cursor",
    "grant_digest",
    "instant_token",
    "parse_instant_token",
    "scope_digest",
]

#: The `v` of every token this module writes; any other is malformed.
CURSOR_VERSION: Final = 1
#: Section 5: a token is at most this many characters.
MAX_CURSOR_CHARACTERS: Final = 2048

_KEYS: Final = frozenset({"v", "b", "s", "k", "t", "n", "r", "p"})
_BASE64URL: Final = re.compile(r"\A[A-Za-z0-9_-]{1,2048}\Z")
_HEX_DIGEST: Final = re.compile(r"\A[0-9a-f]{64}\Z")
_INSTANT: Final = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z")
_EVENT_ID: Final = re.compile(r"\Arcev_[A-Za-z0-9]{8,64}\Z")
_INSTANT_FORMAT: Final = "%Y-%m-%dT%H:%M:%S.%fZ"

#: Every read a remote grant digest covers besides the called capability.
_FAMILY_READS: Final = frozenset(read for reads in LINEAGE_FAMILY_READS.values() for read in reads)


class CursorMalformedError(ValueError):
    """The token's encoding, length, version, keys or one value's shape is wrong.

    The read answers `invalid_request` / `cursor`, before any binding check.
    """


@dataclass(frozen=True, slots=True)
class LineageCursor:
    """One decoded token. `position` is whatever the read's own validator admitted."""

    binding: str
    scope: str
    known_at: datetime | None
    lineage_valid_at: datetime | None
    native_cut_at: datetime | None
    record_event_watermark: str | None
    position: object


def canonical_bytes(document: object) -> bytes:
    """Canonical JSON: sorted keys, no whitespace, ASCII only."""
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def _sha256(document: object) -> str:
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def instant_token(value: datetime | None) -> str | None:
    """An instant as RFC 3339 UTC with every microsecond, or `None`."""
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("a lineage cut is an aware instant")
    return value.astimezone(UTC).strftime(_INSTANT_FORMAT)


def parse_instant_token(token: object) -> datetime | None:
    """The inverse of `instant_token`; `CursorMalformedError` for any other shape."""
    if token is None:
        return None
    if not isinstance(token, str) or _INSTANT.fullmatch(token) is None:
        raise CursorMalformedError("an instant is malformed")
    try:
        return datetime.strptime(token, _INSTANT_FORMAT).replace(tzinfo=UTC)
    except ValueError as error:
        raise CursorMalformedError("an instant is malformed") from error


def grant_digest(grants: Iterable[tuple[str, str | None]] | None, capability: str) -> str | None:
    """Section 6.4: SHA-256 over the caller's sorted grants that decide visibility.

    The `(capability, purpose)` pairs on the lineage family reads and on the
    called capability, as stored tokens (a capability-wide grant has purpose
    `None`). `None` for a local caller, which holds no grant set.
    """
    if grants is None:
        return None
    relevant = sorted(
        {
            (granted, purpose)
            for granted, purpose in grants
            if granted in _FAMILY_READS or granted == capability
        },
        key=lambda pair: (pair[0], "" if pair[1] is None else pair[1], pair[1] is None),
    )
    return _sha256([[granted, purpose] for granted, purpose in relevant])


def scope_digest(grants_digest: str | None, *, generation: int = LINEAGE_READ_GENERATION) -> str:
    """`s`: the grant digest and the read generation, together."""
    return _sha256({"generation": generation, "grant_digest": grants_digest})


def cursor_binding(
    *,
    capability: str,
    principal_id: str,
    request: Mapping[str, object],
    known_at: datetime | None,
    lineage_valid_at: datetime | None,
    native_cut_at: datetime | None,
    record_event_watermark: str | None,
) -> str:
    """`b`: the request (without its cursor) and its frozen cuts, for one Principal."""
    return _sha256(
        {
            "capability": capability,
            "cursor_version": CURSOR_VERSION,
            "known_at": instant_token(known_at),
            "native_cut_at": instant_token(native_cut_at),
            "principal_id": principal_id,
            "record_event_watermark": record_event_watermark,
            "request": dict(request),
            "valid_at": instant_token(lineage_valid_at),
        }
    )


def encode_cursor(cursor: LineageCursor) -> str:
    """The opaque token for `cursor`; `ValueError` if it would exceed 2048 characters."""
    payload = canonical_bytes(
        {
            "b": cursor.binding,
            "k": instant_token(cursor.known_at),
            "n": instant_token(cursor.native_cut_at),
            "p": cursor.position,
            "r": cursor.record_event_watermark,
            "s": cursor.scope,
            "t": instant_token(cursor.lineage_valid_at),
            "v": CURSOR_VERSION,
        }
    )
    token = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    if len(token) > MAX_CURSOR_CHARACTERS:
        raise ValueError("a lineage cursor exceeds 2048 characters")
    return token


def decode_cursor(token: object, position: Callable[[object], bool]) -> LineageCursor:
    """Shape only (section 7.2 step 7, first check): the decoded token, or malformed.

    `position` says whether `p` has the read's own shape and prefix; a wrong
    one is malformed too, checked with the shape. Nothing is compared with any
    request, Principal, grant or horizon here.
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
    watermark = decoded["r"]
    if watermark is not None and (
        not isinstance(watermark, str) or _EVENT_ID.fullmatch(watermark) is None
    ):
        raise CursorMalformedError("the cursor watermark is malformed")
    if not position(decoded["p"]):
        raise CursorMalformedError("the cursor position is malformed")
    return LineageCursor(
        binding=decoded["b"],
        scope=decoded["s"],
        known_at=parse_instant_token(decoded["k"]),
        lineage_valid_at=parse_instant_token(decoded["t"]),
        native_cut_at=parse_instant_token(decoded["n"]),
        record_event_watermark=watermark,
        position=decoded["p"],
    )
