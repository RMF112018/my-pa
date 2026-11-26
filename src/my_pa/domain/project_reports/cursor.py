"""The opaque, grant-bound project-reports cursor (WP4P design 2.8; ruling D4).

Pure, standard library only. A copy-adapt of the communications cursor, never
an import of it (the two slices may not import each other): the same token
envelope, the unpadded base64url of canonical JSON (ASCII, sorted keys, no
whitespace) of

``{"v": 1, "b": <binding>, "s": <scope>, "p": <position>}``

at most 2,048 characters. It carries **no authority**: no secret and no
signature; the server re-derives everything on every page. A FAST parity test
holds the envelope equal to the communications one.

* `b` binds the token to one request: the capability, the Principal, the
  normalized request without its cursor and limit, and the cursor version.
  Another Principal's token or a changed filter is `conflict` / `cursor`.
* `s` binds it to the caller's visibility **and to the versions it read**: the
  digest of its grants on the `project_reports.*` reads, the read generation,
  and the resolved version set (each `(series_id, version, derivation_id)`).
  A new export, a re-derivation or a binding correction between two pages
  changes `s`, and the read answers `scope_changed_restart_required` (ruling
  D4 (b)). The read checks `s` after resolving its versions, before reading a
  line.
* `p` is the last emitted item's key in the read's total order:
  - query: `[series_ordinal, "isnp_...", row_ordinal]`;
  - compare: `[section_rank, key]`.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Final

__all__ = [
    "CURSOR_VERSION",
    "MAX_CURSOR_CHARACTERS",
    "PROJECT_REPORTS_READS",
    "PROJECT_REPORTS_READ_GENERATION",
    "ComparePosition",
    "CursorMalformedError",
    "ProjectReportsCursor",
    "QueryPosition",
    "ResolvedVersion",
    "compare_position",
    "cursor_binding",
    "decode_cursor",
    "encode_cursor",
    "grant_digest",
    "query_position",
    "scope_digest",
]

#: The `v` of every token this module writes; any other is malformed.
CURSOR_VERSION: Final = 1
#: A token is at most this many characters (the communications bound).
MAX_CURSOR_CHARACTERS: Final = 2048
#: Raised when what a grant can see changes without a grant changing.
PROJECT_REPORTS_READ_GENERATION: Final = 1
#: The reads whose grants decide what a project-reports cursor may continue.
PROJECT_REPORTS_READS: Final = frozenset(
    {
        "project_reports.catalog",
        "project_reports.compare",
        "project_reports.coverage",
        "project_reports.query",
        "project_reports.record_history",
    }
)

_KEYS: Final = frozenset({"v", "b", "s", "p"})
_BASE64URL: Final = re.compile(r"\A[A-Za-z0-9_-]{1,2048}\Z")
_HEX_DIGEST: Final = re.compile(r"\A[0-9a-f]{64}\Z")
_SNAPSHOT_ID: Final = re.compile(r"\Aisnp_[A-Za-z0-9]{8,64}\Z")
_COMPARE_KEY: Final = re.compile(r"\A[\x20-\x7e]{1,512}\Z")
_MAX_ORDINAL: Final = 2**31 - 1
#: Compare sections: added, not observed, changed, lines.
_MAX_SECTION: Final = 3


class CursorMalformedError(ValueError):
    """The token's encoding, length, version, keys or position shape is wrong.

    The read answers `invalid_request` / `cursor`, before any binding check.
    """


@dataclass(frozen=True, slots=True, order=True)
class QueryPosition:
    """A query row's key: series ordinal, version, row ordinal (a total order)."""

    series_ordinal: int
    version: str
    row_ordinal: int


@dataclass(frozen=True, slots=True, order=True)
class ComparePosition:
    """A compare entry's key: its section rank, then its identity key or content digest."""

    section_rank: int
    key: str


@dataclass(frozen=True, slots=True)
class ResolvedVersion:
    """One version a page read, with the derivation it read it through."""

    series_id: str
    version: str
    derivation_id: str


@dataclass(frozen=True, slots=True)
class ProjectReportsCursor:
    binding: str
    scope: str
    position: QueryPosition | ComparePosition


def _canonical_bytes(document: object) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def _sha256(document: object) -> str:
    return hashlib.sha256(_canonical_bytes(document)).hexdigest()


def grant_digest(grants: Iterable[tuple[str, str | None]] | None) -> str | None:
    """SHA-256 over the caller's sorted grants on the `project_reports.*` reads.

    `(capability, purpose)` pairs as stored tokens (a capability-wide grant has
    purpose `None`). `None` for a local caller, which holds no grant set.
    """
    if grants is None:
        return None
    relevant = sorted(
        {(granted, purpose) for granted, purpose in grants if granted in PROJECT_REPORTS_READS},
        key=lambda pair: (pair[0], "" if pair[1] is None else pair[1], pair[1] is None),
    )
    return _sha256([[granted, purpose] for granted, purpose in relevant])


def scope_digest(
    grants_digest: str | None,
    resolved: Iterable[ResolvedVersion],
    *,
    generation: int = PROJECT_REPORTS_READ_GENERATION,
) -> str:
    """`s`: the grant digest, the read generation and the sorted resolved version set."""
    versions = sorted({(entry.series_id, entry.version, entry.derivation_id) for entry in resolved})
    return _sha256(
        {
            "generation": generation,
            "grant_digest": grants_digest,
            "versions": [list(entry) for entry in versions],
        }
    )


def cursor_binding(*, capability: str, principal_id: str, request: Mapping[str, object]) -> str:
    """`b`: the request (without its cursor and limit) for one Principal."""
    return _sha256(
        {
            "capability": capability,
            "cursor_version": CURSOR_VERSION,
            "principal_id": principal_id,
            "request": dict(request),
        }
    )


def _position_document(position: QueryPosition | ComparePosition) -> list[object]:
    if isinstance(position, QueryPosition):
        return [position.series_ordinal, position.version, position.row_ordinal]
    return [position.section_rank, position.key]


def encode_cursor(cursor: ProjectReportsCursor) -> str:
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
        raise ValueError("a project-reports cursor exceeds 2048 characters")
    return token


def _integer(value: object, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise CursorMalformedError("a cursor position number is malformed")
    return value


def query_position(document: object) -> QueryPosition:
    """`[series ordinal, version, row ordinal]`; `CursorMalformedError` otherwise."""
    if not isinstance(document, list) or len(document) != 3:
        raise CursorMalformedError("a query position is malformed")
    ordinal, version, row = document
    if not isinstance(version, str) or _SNAPSHOT_ID.fullmatch(version) is None:
        raise CursorMalformedError("a query position version is malformed")
    return QueryPosition(
        series_ordinal=_integer(ordinal, 0, _MAX_ORDINAL),
        version=version,
        row_ordinal=_integer(row, 1, _MAX_ORDINAL),
    )


def compare_position(document: object) -> ComparePosition:
    """`[section rank, key]`; `CursorMalformedError` otherwise."""
    if not isinstance(document, list) or len(document) != 2:
        raise CursorMalformedError("a compare position is malformed")
    rank, key = document
    if not isinstance(key, str) or _COMPARE_KEY.fullmatch(key) is None:
        raise CursorMalformedError("a compare position key is malformed")
    return ComparePosition(section_rank=_integer(rank, 0, _MAX_SECTION), key=key)


def decode_cursor(
    token: object, position: Callable[[object], QueryPosition | ComparePosition]
) -> ProjectReportsCursor:
    """Shape only: the decoded token, or `CursorMalformedError`.

    `position` is the read's own position parser (`query_position` or
    `compare_position`). Nothing is compared with a request, Principal, grant
    or version set.
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
    return ProjectReportsCursor(
        binding=decoded["b"], scope=decoded["s"], position=position(decoded["p"])
    )
