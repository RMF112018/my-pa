"""CPM Workbench S5b-2: the Schedule keyset cursor.

Contract: `docs/architecture/cpm-workbench-worker-capabilities-contract.md`
section 3.7 (R2 section 32.1), on the search-cursor precedent
(`my_pa.domain.search.query`): an unpadded base64url token of canonical JSON
`{"b": <binding>, "p": [<position>], "t": <issued epoch seconds>, "v": 1}`.

The binding `b` is the SHA-256 of everything that decides which rows a page
holds -- capability, Principal, purpose, the normalized request without its
cursor, the effective page size, the order and, for changes, the delta
algorithm version -- so a cursor replayed against any other request is
refused. The cursor is not a MAC and grants nothing: every page is
re-authorized, re-partitioned and re-checked for visibility, so a forged
position can only skip to rows the same query could already read. No position
carries a published Activity ID, a name or any other source text.

Every refusal -- malformed, too long, expired, issued in the future, or bound
to another request -- is the one `ScheduleCursorError`, and every check here is
pure, so a bad cursor never reaches the database (R7-F10).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.schedule.compare import DELTA_ALGORITHM_VERSION

__all__ = [
    "DEFAULT_SCHEDULE_PAGE_SIZE",
    "MAX_SCHEDULE_CURSOR_CHARACTERS",
    "MAX_SCHEDULE_PAGE_SIZE",
    "SCHEDULE_CURSOR_TTL_SECONDS",
    "SCHEDULE_CURSOR_VERSION",
    "ScheduleCursor",
    "ScheduleCursorError",
    "ScheduleCursorOrder",
    "SchedulePosition",
    "decode_schedule_cursor",
    "encode_schedule_cursor",
    "schedule_cursor_binding",
]

MAX_SCHEDULE_PAGE_SIZE: Final = 100
DEFAULT_SCHEDULE_PAGE_SIZE: Final = 25
MAX_SCHEDULE_CURSOR_CHARACTERS: Final = 512
SCHEDULE_CURSOR_TTL_SECONDS: Final = 300
SCHEDULE_CURSOR_VERSION: Final = 1
#: A cursor issued later than this past `now` is refused (clock skew allowance).
_FUTURE_ALLOWANCE_SECONDS: Final = 5

_TOKEN: Final = re.compile(r"[A-Za-z0-9_-]+")
_BINDING: Final = re.compile(r"[0-9a-f]{64}")
_INSTANT: Final = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z")
_DATE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
_INSTANT_FORMAT: Final = "%Y-%m-%dT%H:%M:%S.%fZ"


class ScheduleCursorOrder(StrEnum):
    """The 11 orders a Schedule cursor can continue, bound into its digest.

    The last 6 are the Schedule Scenarios S6-3 plane orders (schedule-scenarios
    contract section 15.6.2, S6-3-D08).
    """

    SERIES = "series_created_desc_id_desc"
    PUBLICATIONS = "publications_admitted_desc_id_desc"
    ACTIVITIES = "activities_row_ordinal_asc_row_id_asc"
    HISTORY = "history_data_date_asc_admitted_asc_id_asc"
    CHANGES = "changes_offset_in_published_id_kind_field_order"
    SCENARIOS = "scenarios_created_desc_id_desc"
    VERSIONS = "versions_no_desc"
    SCENARIO_CONTENT = "scenario_content_offset"
    OUTPUTS = "outputs_created_desc_id_desc"
    MATCH_DECISIONS = "match_decisions_created_desc_id_desc"
    BASELINES = "baselines_created_desc_id_desc"


#: A decoded position, typed: series `(created_at, series_id)`, publications
#: `(admitted_at, publication_id)`, activities `(row_ordinal, row_id)`,
#: history `(data_date, admitted_at, publication_id)`, changes `(offset,)`;
#: scenarios `(created_at, scenario_id)`, versions `(version_no,)`, scenario
#: content `(offset,)`, outputs `(created_at, output_id)`, match decisions
#: `(created_at, decision_id)`, baselines `(created_at, baseline_id)`.
type SchedulePosition = tuple[datetime | date | int | str, ...]


#: The identifier kind of the 4 plane `(created_at, identifier)` keyset orders.
_PLANE_KEYSET: Final[dict[ScheduleCursorOrder, IdKind]] = {
    ScheduleCursorOrder.SCENARIOS: IdKind.SCHEDULE_SCENARIO,
    ScheduleCursorOrder.OUTPUTS: IdKind.SCHEDULE_SCENARIO_OUTPUT,
    ScheduleCursorOrder.MATCH_DECISIONS: IdKind.SCHEDULE_SERIES_MATCH,
    ScheduleCursorOrder.BASELINES: IdKind.SCHEDULE_BASELINE,
}


class ScheduleCursorError(ValueError):
    """A Schedule cursor that cannot continue this request. Carries no content."""

    def __init__(self) -> None:
        super().__init__("the schedule cursor cannot continue this request")


@dataclass(frozen=True, slots=True)
class ScheduleCursor:
    """One decoded cursor: what it is bound to, where it resumes, when it was issued."""

    binding: str
    order: ScheduleCursorOrder
    position: SchedulePosition
    issued_at: int


def _canonical(document: object) -> bytes:
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def schedule_cursor_binding(
    *,
    capability: str,
    principal_id: str,
    purpose: str,
    request: Mapping[str, object],
    page_size: int,
    order: ScheduleCursorOrder,
) -> str:
    """The SHA-256 every cursor of this exact request carries (contract 3.7).

    `request` is the normalized command without its cursor; for the changes
    order the delta algorithm version is bound too, because offset semantics
    depend on it.
    """
    document: dict[str, object] = {
        "capability": capability,
        "cursor_version": SCHEDULE_CURSOR_VERSION,
        "principal_id": principal_id,
        "purpose": purpose,
        "request": dict(request),
        "page_size": page_size,
        "order": order.value,
    }
    if order is ScheduleCursorOrder.CHANGES:
        document["algorithm_version"] = DELTA_ALGORITHM_VERSION
    return hashlib.sha256(_canonical(document)).hexdigest()


def _instant(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("a cursor instant is timezone-aware")
    return value.astimezone(UTC).strftime(_INSTANT_FORMAT)


def _encode_position(order: ScheduleCursorOrder, position: SchedulePosition) -> list[object]:
    """The wire form of a position; `ValueError` on a shape this order does not take."""
    match order, position:
        case (
            (
                ScheduleCursorOrder.SERIES
                | ScheduleCursorOrder.PUBLICATIONS
                | ScheduleCursorOrder.SCENARIOS
                | ScheduleCursorOrder.OUTPUTS
                | ScheduleCursorOrder.MATCH_DECISIONS
                | ScheduleCursorOrder.BASELINES
            ),
            (
                datetime() as at,
                str() as identifier,
            ),
        ):
            return [_instant(at), identifier]
        case ScheduleCursorOrder.ACTIVITIES, (int() as ordinal, str() as row_id):
            return [ordinal, row_id]
        case ScheduleCursorOrder.HISTORY, (date() as day, datetime() as at, str() as identifier):
            if isinstance(day, datetime):
                raise ValueError("a history position starts with a date")
            return [day.isoformat(), _instant(at), identifier]
        case (
            (ScheduleCursorOrder.CHANGES | ScheduleCursorOrder.SCENARIO_CONTENT),
            (int() as offset,),
        ):
            return [offset]
        case ScheduleCursorOrder.VERSIONS, (int() as version_no,):
            return [version_no]
    raise ValueError("a position does not fit its order")


def encode_schedule_cursor(
    *,
    binding: str,
    order: ScheduleCursorOrder,
    position: SchedulePosition,
    issued_at: datetime,
) -> str:
    """One cursor token; over 512 characters is a programming error (`ValueError`)."""
    if _BINDING.fullmatch(binding) is None:
        raise ValueError("a cursor binding is 64 lowercase hex characters")
    document = {
        "b": binding,
        "p": _encode_position(order, position),
        "t": int(issued_at.timestamp()),
        "v": SCHEDULE_CURSOR_VERSION,
    }
    token = base64.urlsafe_b64encode(_canonical(document)).decode("ascii").rstrip("=")
    if len(token) > MAX_SCHEDULE_CURSOR_CHARACTERS:
        raise ValueError("a schedule cursor exceeds its bound")
    return token


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _identifier(value: object, kind: IdKind) -> str:
    if not isinstance(value, str):
        raise ScheduleCursorError()
    try:
        validate_identifier(value, kind)
    except ValueError:
        pass
    else:
        return value
    raise ScheduleCursorError()


def _read_instant(value: object) -> datetime:
    if isinstance(value, str) and _INSTANT.fullmatch(value) is not None:
        try:
            return datetime.strptime(value, _INSTANT_FORMAT).replace(tzinfo=UTC)
        except ValueError:
            pass
    raise ScheduleCursorError()


def _read_date(value: object) -> date:
    if isinstance(value, str) and _DATE.fullmatch(value) is not None:
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise ScheduleCursorError()


def _decode_position(order: ScheduleCursorOrder, raw: object) -> SchedulePosition:
    """Each element shape-checked for `order`; anything else is the one refusal."""
    if not isinstance(raw, list):
        raise ScheduleCursorError()
    match order, raw:
        case ScheduleCursorOrder.SERIES, [at, identifier]:
            return (_read_instant(at), _identifier(identifier, IdKind.SCHEDULE_SERIES))
        case ScheduleCursorOrder.PUBLICATIONS, [at, identifier]:
            return (_read_instant(at), _identifier(identifier, IdKind.SCHEDULE_PUBLICATION))
        case ScheduleCursorOrder.ACTIVITIES, [ordinal, row_id] if _is_int(ordinal) and ordinal >= 1:
            return (ordinal, _identifier(row_id, IdKind.SCHEDULE_ROW))
        case ScheduleCursorOrder.HISTORY, [day, at, identifier]:
            return (
                _read_date(day),
                _read_instant(at),
                _identifier(identifier, IdKind.SCHEDULE_PUBLICATION),
            )
        case ScheduleCursorOrder.CHANGES, [offset] if _is_int(offset) and offset >= 0:
            return (offset,)
        case ScheduleCursorOrder.SCENARIO_CONTENT, [offset] if _is_int(offset) and offset >= 0:
            return (offset,)
        case ScheduleCursorOrder.VERSIONS, [version_no] if _is_int(version_no) and version_no >= 1:
            return (version_no,)
    if order in _PLANE_KEYSET:
        match raw:
            case [at, identifier]:
                return (_read_instant(at), _identifier(identifier, _PLANE_KEYSET[order]))
    raise ScheduleCursorError()


def _document(token: str) -> object:
    padded = token + "=" * (-len(token) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        pass
    raise ScheduleCursorError()


def decode_schedule_cursor(
    token: str,
    *,
    binding: str,
    order: ScheduleCursorOrder,
    now: datetime,
) -> ScheduleCursor:
    """The position to resume at, or `ScheduleCursorError`.

    Order of checks: the length bound before any decoding; then the alphabet,
    the canonical document, its version, the binding, the issue time (not
    later than `now` + 5 s, not older than 300 s) and the position's shape.
    `t` is outside the binding, so the TTL is advisory against a caller who
    edits it -- the search-cursor precedent has the same property.
    """
    raw: object = token
    if not isinstance(raw, str) or len(raw) > MAX_SCHEDULE_CURSOR_CHARACTERS:
        raise ScheduleCursorError()
    if _TOKEN.fullmatch(token) is None:
        raise ScheduleCursorError()
    document = _document(token)
    if not isinstance(document, dict) or set(document) != {"b", "p", "t", "v"}:
        raise ScheduleCursorError()
    # Exactly the bytes this module would have issued: no padding, spacing or
    # key-order variant of a valid cursor is a second valid cursor.
    if base64.urlsafe_b64encode(_canonical(document)).decode("ascii").rstrip("=") != token:
        raise ScheduleCursorError()
    if document["v"] != SCHEDULE_CURSOR_VERSION or not _is_int(document["v"]):
        raise ScheduleCursorError()
    if document["b"] != binding:
        raise ScheduleCursorError()
    issued = document["t"]
    if not _is_int(issued):
        raise ScheduleCursorError()
    instant = int(now.timestamp())
    if (
        issued > instant + _FUTURE_ALLOWANCE_SECONDS
        or instant - issued > SCHEDULE_CURSOR_TTL_SECONDS
    ):
        raise ScheduleCursorError()
    position = _decode_position(order, document["p"])
    return ScheduleCursor(binding=binding, order=order, position=position, issued_at=issued)
