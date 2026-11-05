"""The report catalog: plane selector, filters, keyset cursor and search text (WP04).

`reports.list` and `reports.search` read the general report plane (and, in the
`all` plane, the caller's current Intelligence Artifacts beside it) through the
values here. Stdlib only, like the rest of the package.

**Filters are validated by publish's own rules.** A `type` is a publish type
token, each topic and tag a publish term, an `associated_with` reference the
shape publish requires of a `target_ref`. A refusal is the package's
`ReportValidationError`, naming the field and the rule, never the value.

**The cursor is bound, not signed** (the `domain.search.query.SearchCursor`
precedent). A token carries the digest of everything the page's meaning
depends on (`binding_digest`: operation, Principal, plane, normalized filters,
the query's fingerprint, page size, order) and the keyset position of the last
item. A token presented with a different request, or one that does not decode
to exactly the canonical shape, is one refusal (`CatalogCursorError`, field
`cursor`) that never echoes the token. There is no key: a forged position
carries no authority, because it is re-applied inside the re-authorized,
Principal-scoped query and so only skips rows the caller may already see. The
keyset is stable (`created_at` and the report id never change), so there is no
TTL.

**Search text** (`extract_search_text`) is the version's searchable projection
of its decoded, validated content: never the transport bytes and never Base64.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.reports.content import ReportContent
from my_pa.domain.reports.creator import validate_creator_id
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.publication import aware_timestamp, format_timestamp
from my_pa.domain.reports.values import (
    validate_association_ref,
    validate_tags,
    validate_topics,
    validate_type_token,
)
from my_pa.domain.reports.vocabulary import (
    MAX_SEARCH_TEXT_CHARACTERS,
    AssociationTargetKind,
    ContentFormat,
    LifecycleState,
)
from my_pa.domain.search.query import SearchQuery

__all__ = [
    "CATALOG_BINDING_VERSION",
    "DEFAULT_CATALOG_PAGE_SIZE",
    "DEFAULT_LIFECYCLE_STATES",
    "LIST_ORDER",
    "MAX_CATALOG_CURSOR_CHARACTERS",
    "MAX_CATALOG_PAGE_SIZE",
    "SEARCH_ORDER",
    "AssociationFilter",
    "CatalogCursor",
    "CatalogCursorError",
    "CatalogFilters",
    "CatalogOperation",
    "ReportPlane",
    "binding_digest",
    "extract_search_text",
    "validate_catalog_page_size",
]

#: Bumped when the binding's shape changes, so every older cursor stops matching.
CATALOG_BINDING_VERSION: Final = 1

DEFAULT_CATALOG_PAGE_SIZE: Final = 20
MAX_CATALOG_PAGE_SIZE: Final = 100

#: Longest token decoded: decoding an unbounded string is work an outsider sizes.
MAX_CATALOG_CURSOR_CHARACTERS: Final = 512

#: The two orders (contract C6), named so a cursor binds the order it was issued in.
#: `sort_time` is a standalone root's `created_at` or a legacy artifact's
#: `committed_at`; ids compare in code-point order (SQL `COLLATE "C"`).
LIST_ORDER: Final = "sort_time_desc_then_report_id_desc"
SEARCH_ORDER: Final = "rank_desc_then_sort_time_desc_then_report_id_desc"

DEFAULT_LIFECYCLE_STATES: Final = frozenset({LifecycleState.ACTIVE})

#: A rank is a PostgreSQL `bigint`.
_MAX_RANK: Final = 2**63 - 1

_TOKEN_ALPHABET: Final = re.compile(r"\A[A-Za-z0-9_-]+\Z")
_SHA256: Final = re.compile(r"\A[0-9a-f]{64}\Z")
_TIMESTAMP: Final = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z")


class ReportPlane(StrEnum):
    """Which plane a catalog request reads (contract C1/C2)."""

    INTELLIGENCE = "intelligence"
    STANDALONE = "standalone"
    ALL = "all"


class CatalogOperation(StrEnum):
    LIST = "list"
    SEARCH = "search"


class CatalogCursorError(ReportValidationError):
    """A cursor is unreadable or was issued for another request: one refusal.

    Always `cursor: invalid`, whatever the reason, and raised outside any
    handler, so neither the message nor `__context__` carries the token.
    """

    def __init__(self) -> None:
        super().__init__("cursor", "invalid")


# ---- filters ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssociationFilter:
    """Match a head version associated with `(target_kind, target_ref)` (shape only)."""

    target_kind: AssociationTargetKind
    target_ref: str

    def __post_init__(self) -> None:
        kind: object = self.target_kind
        if not isinstance(kind, str):
            raise ReportValidationError("associated_with", "type")
        try:
            object.__setattr__(self, "target_kind", AssociationTargetKind(kind))
        except ValueError:
            raise ReportValidationError("associated_with", "target_kind") from None
        validate_association_ref(self.target_ref, "associated_with")


def _terms(
    value: object, validate: Callable[[object], tuple[str, ...]], name: str
) -> tuple[str, ...]:
    accepted = validate(value)
    if not accepted:
        raise ReportValidationError(name, "too_short")
    return accepted


def _lifecycle_states(value: object) -> frozenset[LifecycleState]:
    if isinstance(value, frozenset | set):
        value = sorted(value)
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise ReportValidationError("lifecycle_states", "type")
    if not value:
        raise ReportValidationError("lifecycle_states", "too_short")
    states: set[LifecycleState] = set()
    for entry in value:
        if not isinstance(entry, str):
            raise ReportValidationError("lifecycle_states", "type")
        try:
            state = LifecycleState(entry)
        except ValueError:
            raise ReportValidationError("lifecycle_states", "unknown") from None
        if state in states:
            raise ReportValidationError("lifecycle_states", "duplicate")
        states.add(state)
    return frozenset(states)


def _plain_date(value: object, name: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ReportValidationError(name, "type")
    return value


@dataclass(frozen=True, slots=True)
class CatalogFilters:
    """The standalone/all catalog filters (contract C3), normalized on construction.

    Every field is optional. `topics`/`tags` must be non-empty when given
    (empty means absent); `lifecycle_states` defaults to `{active}`. Created
    bounds are half-open `[from, to)` with `from < to`; report-date bounds are
    inclusive with `from <= to`. `created_by` (WP05 A5) is a creator pseudonym
    (`gcrt_` + 40 hex), matched exactly against the root's creator; legacy
    Intelligence Artifacts never match it.
    """

    report_type: str | None = None
    topics: tuple[str, ...] | None = None
    tags: tuple[str, ...] | None = None
    associated_with: AssociationFilter | None = None
    lifecycle_states: frozenset[LifecycleState] = field(
        default_factory=lambda: DEFAULT_LIFECYCLE_STATES
    )
    created_from: datetime | None = None
    created_to: datetime | None = None
    report_date_from: date | None = None
    report_date_to: date | None = None
    created_by: str | None = None

    def __post_init__(self) -> None:
        def put(name: str, value: object) -> None:
            object.__setattr__(self, name, value)

        if self.report_type is not None:
            put("report_type", validate_type_token(self.report_type, "type"))
        if self.topics is not None:
            put("topics", _terms(self.topics, validate_topics, "topics"))
        if self.tags is not None:
            put("tags", _terms(self.tags, validate_tags, "tags"))
        if self.associated_with is not None and not isinstance(
            self.associated_with, AssociationFilter
        ):
            raise ReportValidationError("associated_with", "type")
        put("lifecycle_states", _lifecycle_states(self.lifecycle_states))
        start = aware_timestamp(self.created_from, "created_from")
        end = aware_timestamp(self.created_to, "created_to")
        if start is not None and end is not None and not start < end:
            raise ReportValidationError("created_range", "order")
        put("created_from", start)
        put("created_to", end)
        first = _plain_date(self.report_date_from, "report_date_from")
        last = _plain_date(self.report_date_to, "report_date_to")
        if first is not None and last is not None and first > last:
            raise ReportValidationError("report_date_range", "order")
        if self.created_by is not None:
            validate_creator_id(self.created_by, "created_by")

    def canonical(self) -> dict[str, object]:
        """The normalized filters as the binding names them: sorted, defaults explicit."""
        association = self.associated_with
        return {
            "type": self.report_type,
            "topics": None if self.topics is None else sorted(self.topics),
            "tags": None if self.tags is None else sorted(self.tags),
            "associated_with": None
            if association is None
            else {
                "target_kind": association.target_kind.value,
                "target_ref": association.target_ref,
            },
            "lifecycle_states": sorted(state.value for state in self.lifecycle_states),
            "created_from": None
            if self.created_from is None
            else format_timestamp(self.created_from),
            "created_to": None if self.created_to is None else format_timestamp(self.created_to),
            "report_date_from": None
            if self.report_date_from is None
            else self.report_date_from.isoformat(),
            "report_date_to": None
            if self.report_date_to is None
            else self.report_date_to.isoformat(),
            "created_by": self.created_by,
        }


def validate_catalog_page_size(value: object) -> int:
    """1..100, an exact `int`; refused (never clamped) outside it."""
    if type(value) is not int:
        raise ReportValidationError("page_size", "type")
    if not 1 <= value <= MAX_CATALOG_PAGE_SIZE:
        raise ReportValidationError("page_size", "out_of_range")
    return value


# ---- the cursor ----------------------------------------------------------------


def _order(operation: CatalogOperation) -> str:
    return SEARCH_ORDER if operation is CatalogOperation.SEARCH else LIST_ORDER


def binding_digest(
    *,
    operation: CatalogOperation,
    principal_id: str,
    plane: ReportPlane,
    filters: CatalogFilters,
    query: SearchQuery | None,
    page_size: int,
) -> str:
    """SHA-256 of the canonical JSON of everything a page's meaning depends on.

    The query enters as its fingerprint, never its text, so a cursor that is
    logged or handed back discloses no search text.
    """
    operation = CatalogOperation(operation)
    plane = ReportPlane(plane)
    validate_identifier(principal_id, IdKind.PRINCIPAL)
    if not isinstance(filters, CatalogFilters):
        raise ReportValidationError("filters", "type")
    if (query is None) != (operation is CatalogOperation.LIST) or (
        query is not None and not isinstance(query, SearchQuery)
    ):
        raise ReportValidationError("query", "type")
    payload = {
        "v": CATALOG_BINDING_VERSION,
        "op": operation.value,
        "principal_id": principal_id,
        "plane": plane.value,
        "filters": filters.canonical(),
        "query": None if query is None else query.fingerprint,
        "page_size": validate_catalog_page_size(page_size),
        "order": _order(operation),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _report_id(value: object, plane: ReportPlane) -> str:
    if not isinstance(value, str):
        raise CatalogCursorError
    kinds = (IdKind.REPORT, IdKind.INTELLIGENCE_ARTIFACT)
    for kind in kinds if plane is ReportPlane.ALL else kinds[:1]:
        try:
            return validate_identifier(value, kind)
        except InvalidIdentifierError:
            continue
    raise CatalogCursorError


@dataclass(frozen=True, slots=True)
class CatalogCursor:
    """The keyset position after the last item of a page, bound to its request.

    `rank` is the integer search rank (`floor(ts_rank * 1e6)`) for a search
    cursor and `None` for a list cursor. `sort_time` keeps microseconds; the
    token writes it as RFC 3339 UTC with six fractional digits.
    """

    binding: str
    sort_time: datetime
    report_id: str
    rank: int | None = None

    def __post_init__(self) -> None:
        # Typed as `object`: a transport hands these in unchecked.
        binding: object = self.binding
        sort_time: object = self.sort_time
        if not isinstance(binding, str) or not _SHA256.fullmatch(binding):
            raise CatalogCursorError
        if (
            not isinstance(sort_time, datetime)
            or self.sort_time.tzinfo is None
            or self.sort_time.tzinfo.utcoffset(self.sort_time) is None
        ):
            raise CatalogCursorError
        object.__setattr__(self, "sort_time", self.sort_time.astimezone(UTC))
        _report_id(self.report_id, ReportPlane.ALL)
        if self.rank is not None and (
            type(self.rank) is not int or not 0 <= self.rank <= _MAX_RANK
        ):
            raise CatalogCursorError

    @property
    def operation(self) -> CatalogOperation:
        return CatalogOperation.LIST if self.rank is None else CatalogOperation.SEARCH

    def encode(self) -> str:
        """base64url (no padding) of compact sorted JSON: `{b,t,i}` or `{b,r,t,i}`."""
        payload: dict[str, object] = {
            "b": self.binding,
            "t": format_timestamp(self.sort_time),
            "i": self.report_id,
        }
        if self.rank is not None:
            payload["r"] = self.rank
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return base64.urlsafe_b64encode(text.encode("ascii")).decode("ascii").rstrip("=")

    @classmethod
    def decode(
        cls,
        token: object,
        *,
        operation: CatalogOperation,
        plane: ReportPlane,
        binding: str,
    ) -> CatalogCursor:
        """The position `token` names for this request, or `CatalogCursorError`.

        Refused alike: a non-string or oversize token, any character outside
        the base64url alphabet, undecodable bytes, a payload that is not
        exactly the operation's key set with the right types, a malformed
        digest, time or id (an `rpt_` id outside the `all` plane), a negative
        or non-integer rank, a token that is not the canonical encoding of the
        position it decodes to, and a binding other than `binding`.
        """
        cursor = _decoded(token, CatalogOperation(operation), ReportPlane(plane))
        if cursor is None or cursor.binding != binding:
            raise CatalogCursorError
        return cursor


def _decoded(
    token: object, operation: CatalogOperation, plane: ReportPlane
) -> CatalogCursor | None:
    if (
        not isinstance(token, str)
        or len(token) > MAX_CATALOG_CURSOR_CHARACTERS
        or not _TOKEN_ALPHABET.fullmatch(token)
    ):
        return None
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    keys = {"b", "t", "i"} | ({"r"} if operation is CatalogOperation.SEARCH else set())
    if not isinstance(payload, dict) or set(payload) != keys:
        return None
    stamp = payload["t"]
    if not isinstance(stamp, str) or not _TIMESTAMP.fullmatch(stamp):
        return None
    rank = payload.get("r")
    if operation is CatalogOperation.SEARCH and type(rank) is not int:
        return None
    try:
        sort_time = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
        _report_id(payload["i"], plane)
        cursor = CatalogCursor(
            binding=payload["b"], sort_time=sort_time, report_id=payload["i"], rank=rank
        )
    except (ValueError, ReportValidationError):
        return None
    # Only the canonical spelling of a position is accepted: no alternative
    # padding bits, key order, whitespace or duplicate key decodes to a cursor.
    if cursor.encode() != token:
        return None
    return cursor


# ---- the search projection ------------------------------------------------------


def _strings(value: object) -> Iterator[str]:
    """Every JSON string value, depth-first: object members in sorted-key order."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key in sorted(value):
            yield from _strings(value[key])
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def extract_search_text(content: ReportContent) -> str:
    """The searchable text of a decoded, validated content value (contract C7).

    `markdown`/`text`: the body. `json`: every string *value* (never a key, a
    number, a boolean or null), depth-first, object members in sorted-key order
    and arrays in order, joined by `\\n`. `mixed`: the body, `\\n`, then the
    data's strings as for `json`. Then cut to `MAX_SEARCH_TEXT_CHARACTERS` code
    points: text beyond it is not searchable. Reads only the decoded body and
    data, never the transport bytes and never a Base64 original.
    """
    if not isinstance(content, ReportContent):
        raise ReportValidationError("content", "type")
    if not content.materialized:
        # WP05 C: facts only (a `managed_blob` read without its bytes). Its
        # search text is the stored one; never an empty body's.
        raise ReportValidationError("content", "not_materialized")
    body = content.body or ""
    if content.format in (ContentFormat.MARKDOWN, ContentFormat.TEXT):
        text = body
    elif content.format is ContentFormat.JSON:
        text = "\n".join(_strings(content.data))
    else:
        text = body + "\n" + "\n".join(_strings(content.data))
    return text[:MAX_SEARCH_TEXT_CHARACTERS]
