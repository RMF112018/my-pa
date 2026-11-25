"""The communications reads: search, read (and thread view), coverage (WP4-S4).

Contract sections 9, 13, 14, 16 and 17; WP4 rulings D7-D9, D4-final, R6-R13.
This module is the service half. Its MCP wiring (capabilities, policy, the
`MY_PA_COMMUNICATIONS_ENABLED` switch, SafeDetail rendering, ChatLLM) is
WP4-S5; here every method takes the authenticated Principal's capture-plane
identifier (server-derived, section 17) and, for the cursors, the caller's
grant set (`None` for a local caller).

**Search** (`search`):

* the request is normalized and bounded exactly as section 16
  (`invalid_request` with one SafeDetail field token otherwise);
* every `identifiers[]` item must name exactly one identifier under the read
  version (ruling R11), and the identifiers found in the non-negated query
  text are merged into the requested set (R6), at most 20 in all;
* the text criterion is `websearch_to_tsquery('english', q)` over the stored
  `search_document`, plus, when the `english` query keeps fewer nodes than the
  `simple` one (a stop-word name), the on-the-fly `simple` match with the
  greater rank (ruling D4-final; the answer says `text_fallback:
  "simple_stopwords"`); quoted phrases are confirmed by exact substring;
* a query with no searchable term under either configuration drops the text
  criterion and says `query_state: "no_searchable_terms"`; no query and no
  identifiers is a browse by time (R8);
* the order is section 14 exactly (tier, rank, participant overlap, time, id);
  collapse by conversation keeps each conversation's best message and the
  keyset is applied after it (D9);
* each result carries its lanes with their verification (the `folder_role`
  filter is a lane claim, R7), and the answer carries the versions and the
  coverage of the queried range (D8, R13).

**Read** (`read`): up to 25 message ids, or one conversation's messages 25 per
page in time order with a cursor (R12). Unknown and foreign ids are both
`not_found`, indistinguishably (the reads are scoped to the Principal). Text is
the stored derived `search_text`, at most 20,000 characters per message and
200,000 per answer; a withheld or truncated body has none, and no raw body is
stored to return.

**Coverage** (`coverage`): section 9 for a range of at most 366 days, over
every communications source of the Principal or one named source.

Cursors are `my_pa.domain.communications.cursor` tokens: malformed is
`invalid_request` / `cursor`; another request's or Principal's is `conflict` /
`cursor`; a changed grant set answers `scope_changed_restart_required` with
nothing else.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from my_pa.application.communications_ingest import communications_source_ids, coverage_facts
from my_pa.application.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
)
from my_pa.contracts.ports import (
    CommunicationMessageRecord,
    CommunicationSearchQuery,
    CommunicationSearchRow,
    UnitOfWork,
)
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.common.time import format_rfc3339, utc_now
from my_pa.domain.communications.corpus import Interval
from my_pa.domain.communications.coverage import (
    CoverageSummary,
    RangeState,
    range_coverage,
    summarize_coverage,
)
from my_pa.domain.communications.cursor import (
    CommunicationsCursor,
    CursorMalformedError,
    SearchPosition,
    ThreadPosition,
    cursor_binding,
    decode_cursor,
    encode_cursor,
    grant_digest,
    instant_token,
    scope_digest,
    search_position,
    thread_position,
)
from my_pa.domain.communications.identifiers import (
    IDENTIFIER_VERSION,
    IdentifierKind,
    TechnicalIdentifier,
    extract_identifiers,
    normalize_identifier_query,
)
from my_pa.domain.communications.model import FolderRole
from my_pa.domain.communications.search_query import quoted_phrases, unnegated_text

__all__ = [
    "COLLAPSE_MODES",
    "COMMUNICATIONS_COVERAGE",
    "COMMUNICATIONS_READ",
    "COMMUNICATIONS_SEARCH",
    "DEFAULT_SEARCH_LIMIT",
    "FOLDER_ROLES",
    "MAX_ANSWER_TEXT_CHARACTERS",
    "MAX_CONVERSATION_ID_CHARACTERS",
    "MAX_COVERAGE_DAYS",
    "MAX_MESSAGE_TEXT_CHARACTERS",
    "MAX_QUERY_CHARACTERS",
    "MAX_READ_IDS",
    "MAX_SEARCH_LIMIT",
    "MAX_TERMS",
    "PARTICIPANT_MODES",
    "SCOPE_CHANGED_RESTART_REQUIRED",
    "SNIPPET_CHARACTERS",
    "TEXT_FALLBACK_SIMPLE_STOPWORDS",
    "THREAD_PAGE_SIZE",
    "CommunicationsReads",
    "CoverageAnswer",
    "CoverageRequest",
    "Lane",
    "LaneState",
    "MessageCoverage",
    "ParticipantView",
    "RangeCoverageView",
    "ReadAnswer",
    "ReadMessage",
    "ReadRequest",
    "SearchAnswer",
    "SearchRequest",
    "SearchResult",
    "Versions",
    "check_coverage_request",
    "check_read_request",
    "coverage_payload",
    "normalize_search",
    "read_payload",
    "search_payload",
]

COMMUNICATIONS_SEARCH: Final = "communications.search"
COMMUNICATIONS_READ: Final = "communications.read"
COMMUNICATIONS_COVERAGE: Final = "communications.coverage"

# --- section 16 bounds -------------------------------------------------------------------
MAX_QUERY_CHARACTERS: Final = 512
#: At most this many identifiers (requested plus found in the query) or participants.
MAX_TERMS: Final = 20
DEFAULT_SEARCH_LIMIT: Final = 20
MAX_SEARCH_LIMIT: Final = 50
SNIPPET_CHARACTERS: Final = 300
MAX_CONVERSATION_ID_CHARACTERS: Final = 2048
MAX_ADDRESS_CHARACTERS: Final = 320
MAX_READ_IDS: Final = 25
THREAD_PAGE_SIZE: Final = 25
MAX_MESSAGE_TEXT_CHARACTERS: Final = 20_000
MAX_ANSWER_TEXT_CHARACTERS: Final = 200_000
MAX_COVERAGE_DAYS: Final = 366
#: A coverage block lists at most this many gaps (and intervals), plus the totals.
MAX_COVERAGE_ITEMS: Final = 20

TEXT_FALLBACK_SIMPLE_STOPWORDS: Final = "simple_stopwords"
NO_SEARCHABLE_TERMS: Final = "no_searchable_terms"
SCOPE_CHANGED_RESTART_REQUIRED: Final = "scope_changed_restart_required"
#: Why a read message carries no text.
TEXT_NOT_REQUESTED: Final = "not_requested"
TEXT_NONE: Final = "no_text"
TEXT_ANSWER_CAP: Final = "answer_cap"
_NO_TEXT_BODY_STATES: Final = frozenset({"withheld", "truncated"})
PARTICIPANT_MODES: Final = ("any", "all")
COLLAPSE_MODES: Final = ("conversation", "none")
FOLDER_ROLES: Final = tuple(role.value for role in FolderRole)
_ADDRESS: Final = re.compile(r"\A[^\s@]+@[^\s@]+\Z")


# --- requests ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SearchRequest:
    query: str | None = None
    identifiers: Sequence[str] = ()
    participants: Sequence[str] = ()
    participant_mode: str = "any"
    from_utc: datetime | None = None
    to_utc: datetime | None = None
    folder_role: str | None = None
    conversation_id: str | None = None
    collapse: str = "conversation"
    limit: int = DEFAULT_SEARCH_LIMIT
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class ReadRequest:
    message_ids: Sequence[str] = ()
    conversation_id: str | None = None
    include_text: bool = True
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class CoverageRequest:
    from_utc: datetime
    to_utc: datetime
    source: str | None = None


# --- answers -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Lane:
    """An observed lane of a message; an unverified one is a claim (ADR-022 decision 6)."""

    folder_role: str
    lane_verification: str


@dataclass(frozen=True, slots=True)
class Flags:
    identity_conflict: bool
    participants_reconciled: bool
    participants_disagreed: bool
    source_unavailable: bool
    search_text_flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Versions:
    """D8: what the answer was derived and matched with."""

    search_text_versions: tuple[str, ...]
    identifier_version: str
    #: Messages whose identifier rows are not (yet) of `identifier_version`.
    identifier_version_pending: int


@dataclass(frozen=True, slots=True)
class LaneState:
    key_kind: str
    role: str
    lane: str
    latest_state: str
    latest_authorized: bool | None


@dataclass(frozen=True, slots=True)
class RangeCoverageView:
    """Coverage of a range (section 9); `start`/`end` `None` when nothing bounds it."""

    state: str
    start: datetime | None
    end: datetime | None
    intervals: tuple[Interval, ...]
    intervals_total: int
    gaps: tuple[Interval, ...]
    gaps_total: int
    freshness_seconds: int | None
    earliest_covered: datetime | None
    latest_covered: datetime | None
    snapshot_count: int
    lanes: tuple[LaneState, ...]


@dataclass(frozen=True, slots=True)
class SearchResult:
    message_id: str
    message_time: datetime
    subject: str | None
    sender_address: str | None
    conversation_id: str | None
    conversation_hits: int
    has_attachments: bool | None
    body_state: str
    tier: int
    rank: int
    participant_overlap: int
    matched_identifier_kinds: tuple[str, ...]
    snippet: str | None
    search_text_version: str
    flags: Flags
    lanes: tuple[Lane, ...]


@dataclass(frozen=True, slots=True)
class SearchAnswer:
    results: tuple[SearchResult, ...]
    next_cursor: str | None
    #: `scope_changed_restart_required` when the cursor's grants changed.
    cursor_state: str | None
    #: `no_searchable_terms` when the query has no term under either configuration.
    query_state: str | None
    #: `simple_stopwords` when the D4-final fallback applied.
    text_fallback: str | None
    #: The identifiers matched: requested and found in the query, normalized.
    identifiers: tuple[str, ...]
    versions: Versions
    coverage: RangeCoverageView


@dataclass(frozen=True, slots=True)
class ParticipantSource:
    observation_id: str
    folder_role: str
    lane_verification: str


@dataclass(frozen=True, slots=True)
class ParticipantView:
    field: str
    address: str
    #: Ruling M7: the observations (and their lanes) whose participants carry it.
    sources: tuple[ParticipantSource, ...]


@dataclass(frozen=True, slots=True)
class ObservationSummary:
    count: int
    by_classification: Mapping[str, int]
    by_folder_role: Mapping[str, int]
    by_lane_verification: Mapping[str, int]
    #: The times of the observation the text pointer names.
    selected_utc: datetime | None
    received_utc: datetime | None
    sent_utc: datetime | None


@dataclass(frozen=True, slots=True)
class MessageCoverage:
    """D8: the declared window and states of the message's text snapshot."""

    snapshot_id: str
    start: datetime | None
    end: datetime | None
    coverage_state: str | None
    lanes: tuple[Mapping[str, object], ...]


@dataclass(frozen=True, slots=True)
class ReadMessage:
    message_id: str
    message_time: datetime
    message_time_basis: str
    subject: str | None
    sender_address: str | None
    conversation_id: str | None
    has_attachments: bool | None
    body_state: str
    content_type: str
    body_utf8_bytes: int
    flags: Flags
    participants: tuple[ParticipantView, ...]
    observations: ObservationSummary
    text_snapshot_id: str
    text_record_ordinal: int
    first_snapshot_id: str
    latest_snapshot_id: str
    coverage: MessageCoverage
    identifiers: tuple[str, ...]
    search_text_version: str
    search_text: str | None
    truncated: bool
    text_omitted: str | None


@dataclass(frozen=True, slots=True)
class ReadAnswer:
    messages: tuple[ReadMessage, ...]
    not_found: tuple[str, ...]
    next_cursor: str | None
    cursor_state: str | None
    identifier_version: str


@dataclass(frozen=True, slots=True)
class CoverageAnswer:
    source: str | None
    coverage: RangeCoverageView


# --- normalization -----------------------------------------------------------------------


def _instant(value: object, detail: SafeDetail) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.microsecond:
        raise InvalidRequestError(detail)
    return value


def _choice(value: object, choices: Sequence[str], detail: SafeDetail) -> str:
    if not isinstance(value, str) or value not in choices:
        raise InvalidRequestError(detail, allowed_values={detail: choices})
    return value


def _strings(value: object, detail: SafeDetail) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise InvalidRequestError(detail)
    if len(value) > MAX_TERMS or not all(isinstance(item, str) for item in value):
        raise InvalidRequestError(detail)
    return tuple(value)


def _conversation_id(value: object) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > MAX_CONVERSATION_ID_CHARACTERS
    ):
        raise InvalidRequestError(SafeDetail.CONVERSATION_ID)
    return value


@dataclass(frozen=True, slots=True)
class _Search:
    query: str | None
    identifiers: tuple[TechnicalIdentifier, ...]
    participants: tuple[str, ...]
    participant_mode: str
    from_utc: datetime | None
    to_utc: datetime | None
    folder_role: str | None
    conversation_id: str | None
    collapse: str
    limit: int

    def document(self) -> dict[str, object]:
        """The request without cursor and limit, as the binding covers it."""
        return {
            "collapse": self.collapse,
            "conversation_id": self.conversation_id,
            "folder_role": self.folder_role,
            "from_utc": None if self.from_utc is None else instant_token(self.from_utc),
            "identifiers": [identifier.normalized for identifier in self.identifiers],
            "participant_mode": self.participant_mode,
            "participants": list(self.participants),
            "query": self.query,
            "to_utc": None if self.to_utc is None else instant_token(self.to_utc),
        }


def normalize_search(request: SearchRequest, identifier_version: str | None) -> _Search:
    """Section 16 bounds and the R6/R11 identifier rules; `invalid_request` otherwise.

    With `identifier_version` `None` (the command's shape check, before the
    configured read version is known) the identifier items are checked as
    strings only: none is normalized and nothing is merged from the query.
    """
    raw: object = request.query  # typed by the dataclass, checked as received
    query: str | None = None
    if raw is not None:
        if not isinstance(raw, str) or len(raw) > MAX_QUERY_CHARACTERS:
            raise InvalidRequestError(SafeDetail.QUERY)
        query = raw.strip() or None
    requested: set[TechnicalIdentifier] = set()
    for item in _strings(request.identifiers, SafeDetail.IDENTIFIERS):
        if identifier_version is None:
            continue
        identifier = normalize_identifier_query(item, version=identifier_version)
        if identifier is None:  # R11: zero or several identifiers
            raise InvalidRequestError(SafeDetail.IDENTIFIERS)
        requested.add(identifier)
    if query is not None and identifier_version is not None:  # R6: the query's, too
        requested.update(extract_identifiers(unnegated_text(query), version=identifier_version))
    if len(requested) > MAX_TERMS:
        raise InvalidRequestError(SafeDetail.IDENTIFIERS)
    participants: set[str] = set()
    for item in _strings(request.participants, SafeDetail.PARTICIPANTS):
        address = item.strip().lower()
        if len(address) > MAX_ADDRESS_CHARACTERS or _ADDRESS.fullmatch(address) is None:
            raise InvalidRequestError(SafeDetail.PARTICIPANTS)
        participants.add(address)
    mode = _choice(request.participant_mode, PARTICIPANT_MODES, SafeDetail.PARTICIPANT_MODE)
    from_utc = _instant(request.from_utc, SafeDetail.FROM_UTC)
    to_utc = _instant(request.to_utc, SafeDetail.TO_UTC)
    if from_utc is not None and to_utc is not None and from_utc > to_utc:
        raise InvalidRequestError(SafeDetail.TO_UTC)
    folder_role = None
    if request.folder_role is not None:
        folder_role = _choice(request.folder_role, FOLDER_ROLES, SafeDetail.FOLDER_ROLE)
    conversation_id = _conversation_id(request.conversation_id)
    collapse = _choice(request.collapse, COLLAPSE_MODES, SafeDetail.COLLAPSE)
    if conversation_id is not None:  # one conversation: nothing to collapse
        collapse = "none"
    limit = request.limit
    if type(limit) is not int or not 1 <= limit <= MAX_SEARCH_LIMIT:
        raise InvalidRequestError(SafeDetail.LIMIT)
    if request.cursor is not None and not isinstance(request.cursor, str):
        raise InvalidRequestError(SafeDetail.CURSOR)
    return _Search(
        query=query,
        identifiers=tuple(sorted(requested)),
        participants=tuple(sorted(participants)),
        participant_mode=mode,
        from_utc=from_utc,
        to_utc=to_utc,
        folder_role=folder_role,
        conversation_id=conversation_id,
        collapse=collapse,
        limit=limit,
    )


def check_read_request(request: ReadRequest) -> tuple[str | None, tuple[str, ...]]:
    """Section 16 shape of a read: the conversation, or the deduplicated ids.

    Exactly one of `message_ids` and `conversation_id`; a cursor only with a
    conversation; `invalid_request` with one SafeDetail field token otherwise.
    """
    if type(request.include_text) is not bool:
        raise InvalidRequestError(SafeDetail.INCLUDE_TEXT)
    conversation_id = _conversation_id(request.conversation_id)
    ids: object = request.message_ids
    has_ids = not (isinstance(ids, Sequence) and not isinstance(ids, str) and len(ids) == 0)
    if (conversation_id is None) == (not has_ids):  # exactly one of the two
        raise InvalidRequestError(
            SafeDetail.MESSAGE_IDS if conversation_id is None else SafeDetail.CONVERSATION_ID
        )
    if conversation_id is not None:
        if request.cursor is not None and not isinstance(request.cursor, str):
            raise InvalidRequestError(SafeDetail.CURSOR)
        return conversation_id, ()
    if request.cursor is not None:
        raise InvalidRequestError(SafeDetail.CURSOR)
    return None, _message_ids(request.message_ids)


def check_coverage_request(request: CoverageRequest) -> tuple[datetime, datetime, str | None]:
    """Section 16 shape of a coverage read: the range (at most 366 days) and the source."""
    start = _instant(request.from_utc, SafeDetail.FROM_UTC)
    end = _instant(request.to_utc, SafeDetail.TO_UTC)
    if start is None:
        raise InvalidRequestError(SafeDetail.FROM_UTC)
    if end is None or end < start or end - start > timedelta(days=MAX_COVERAGE_DAYS):
        raise InvalidRequestError(SafeDetail.TO_UTC)
    source = request.source
    if source is not None:
        try:
            validate_identifier(source, IdKind.INGEST_SOURCE)
        except InvalidIdentifierError:
            raise InvalidRequestError(SafeDetail.SOURCE) from None
    return start, end, source


def _message_ids(value: object) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise InvalidRequestError(SafeDetail.MESSAGE_IDS)
    if not 1 <= len(value) <= MAX_READ_IDS:
        raise InvalidRequestError(SafeDetail.MESSAGE_IDS)
    ids: list[str] = []
    for item in value:
        try:
            validate_identifier(item, IdKind.COMMUNICATION_MESSAGE)
        except InvalidIdentifierError:
            raise InvalidRequestError(SafeDetail.MESSAGE_IDS) from None
        if item not in ids:
            ids.append(item)
    return tuple(ids)


# --- coverage ----------------------------------------------------------------------------


def _lane_states(summary: CoverageSummary) -> tuple[LaneState, ...]:
    return tuple(
        LaneState(
            key_kind=lane.key_kind,
            role=lane.role,
            lane=lane.lane,
            latest_state=lane.latest_state,
            latest_authorized=lane.latest_authorized,
        )
        for lane in summary.lanes
    )


def range_view(
    summary: CoverageSummary, start: datetime | None, end: datetime | None
) -> RangeCoverageView:
    """`[start, end]` over the summary; a missing bound is the covered edge (R13)."""
    earliest = summary.intervals[0].start if summary.intervals else None
    start = start if start is not None else earliest
    end = end if end is not None else summary.latest_covered
    intervals: tuple[Interval, ...] = ()
    gaps: tuple[Interval, ...] = ()
    state = RangeState.NONE.value
    if start is not None and end is not None and start <= end:
        measured = range_coverage(summary.intervals, start=start, end=end)
        state, gaps = measured.state.value, measured.gaps
        intervals = tuple(
            Interval(max(i.start, measured.start), min(i.end, measured.end))
            for i in summary.intervals
            if i.end >= measured.start and i.start <= measured.end
        )
    return RangeCoverageView(
        state=state,
        start=start,
        end=end,
        intervals=intervals[:MAX_COVERAGE_ITEMS],
        intervals_total=len(intervals),
        gaps=gaps[:MAX_COVERAGE_ITEMS],
        gaps_total=len(gaps),
        freshness_seconds=summary.freshness_seconds,
        earliest_covered=earliest,
        latest_covered=summary.latest_covered,
        snapshot_count=summary.snapshots,
        lanes=_lane_states(summary),
    )


# --- the service -------------------------------------------------------------------------


class CommunicationsReads:
    """The three reads (module docstring)."""

    def __init__(
        self,
        *,
        unit_of_work: Callable[[], AbstractContextManager[UnitOfWork]],
        identifier_version: str = IDENTIFIER_VERSION,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._identifier_version = identifier_version
        self._clock = clock

    # --- cursors --------------------------------------------------------------------------

    def _cursor(
        self,
        token: str | None,
        *,
        parse: Callable[[object], SearchPosition | ThreadPosition],
        binding: str,
        scope: str,
    ) -> SearchPosition | ThreadPosition | bool | None:
        """The position after which to continue; `False` when the scope changed."""
        if token is None:
            return None
        try:
            cursor = decode_cursor(token, parse)
        except CursorMalformedError:
            raise InvalidRequestError(SafeDetail.CURSOR) from None
        if cursor.binding != binding:
            raise ConflictError(SafeDetail.CURSOR)
        if cursor.scope != scope:
            return False
        return cursor.position

    @staticmethod
    def _scope(grants: Iterable[tuple[str, str | None]] | None) -> str:
        return scope_digest(grant_digest(grants))

    def _coverage(self, unit: UnitOfWork, principal_id: str) -> CoverageSummary:
        sources = communications_source_ids(unit, principal_id)
        return summarize_coverage(coverage_facts(unit, principal_id, sources), now=self._clock())

    def _versions(self, unit: UnitOfWork, principal_id: str) -> Versions:
        repository = unit.communications
        return Versions(
            search_text_versions=repository.list_search_text_versions(principal_id),
            identifier_version=self._identifier_version,
            identifier_version_pending=repository.count_identifier_version_pending(
                principal_id, self._identifier_version
            ),
        )

    # --- search ---------------------------------------------------------------------------

    def search(
        self,
        principal_id: str,
        request: SearchRequest,
        *,
        grants: Iterable[tuple[str, str | None]] | None = None,
    ) -> SearchAnswer:
        normalized = normalize_search(request, self._identifier_version)
        binding = cursor_binding(
            capability=COMMUNICATIONS_SEARCH,
            principal_id=principal_id,
            request=normalized.document(),
            identifier_version=self._identifier_version,
        )
        scope = self._scope(grants)
        after = self._cursor(request.cursor, parse=search_position, binding=binding, scope=scope)
        with self._unit_of_work() as unit:
            repository = unit.communications
            versions = self._versions(unit, principal_id)
            coverage = range_view(
                self._coverage(unit, principal_id), normalized.from_utc, normalized.to_utc
            )
            identifiers = tuple(identifier.normalized for identifier in normalized.identifiers)
            if after is False:
                return SearchAnswer(
                    results=(),
                    next_cursor=None,
                    cursor_state=SCOPE_CHANGED_RESTART_REQUIRED,
                    query_state=None,
                    text_fallback=None,
                    identifiers=identifiers,
                    versions=versions,
                    coverage=coverage,
                )
            query, query_state, fallback, english_terms = normalized.query, None, False, False
            if query is not None:
                shape = repository.search_query_shape(query)
                if shape.simple_nodes == 0:  # R8: flag, do not refuse
                    query, query_state = None, NO_SEARCHABLE_TERMS
                else:
                    english_terms = shape.english_nodes > 0
                    # D4-final: `english` dropped a lexeme `simple` keeps.
                    fallback = shape.english_nodes < shape.simple_nodes
            position = after if isinstance(after, SearchPosition) else None
            rows = repository.search_messages(
                principal_id,
                CommunicationSearchQuery(
                    query=query,
                    english_terms=english_terms,
                    text_fallback=fallback,
                    phrases=quoted_phrases(query) if query is not None else (),
                    identifiers=tuple(
                        (identifier.kind.value, identifier.value)
                        for identifier in normalized.identifiers
                    ),
                    identifier_version=self._identifier_version,
                    participants=normalized.participants,
                    participants_all=normalized.participant_mode == "all",
                    from_utc=normalized.from_utc,
                    to_utc=normalized.to_utc,
                    folder_role=normalized.folder_role,
                    conversation_id=normalized.conversation_id,
                    collapse=normalized.collapse == "conversation",
                    after=None
                    if position is None
                    else (
                        position.tier,
                        position.rank,
                        position.overlap,
                        position.message_time,
                        position.message_id,
                    ),
                    limit=normalized.limit + 1,
                ),
            )
            page = rows[: normalized.limit]
            lanes = repository.list_message_lanes(principal_id, [row.message_id for row in page])
        next_cursor = None
        if len(rows) > normalized.limit and page:
            last = page[-1]
            next_cursor = encode_cursor(
                CommunicationsCursor(
                    binding=binding,
                    scope=scope,
                    position=SearchPosition(
                        last.tier, last.rank, last.overlap, last.message_time, last.message_id
                    ),
                )
            )
        return SearchAnswer(
            results=tuple(_result(row, lanes.get(row.message_id, ())) for row in page),
            next_cursor=next_cursor,
            cursor_state=None,
            query_state=query_state,
            text_fallback=TEXT_FALLBACK_SIMPLE_STOPWORDS if fallback else None,
            identifiers=identifiers,
            versions=versions,
            coverage=coverage,
        )

    # --- read -----------------------------------------------------------------------------

    def read(
        self,
        principal_id: str,
        request: ReadRequest,
        *,
        grants: Iterable[tuple[str, str | None]] | None = None,
    ) -> ReadAnswer:
        conversation_id, message_ids = check_read_request(request)
        if conversation_id is None:
            return self._read_ids(principal_id, message_ids, request)
        return self._read_thread(principal_id, conversation_id, request, grants)

    def _read_ids(
        self, principal_id: str, message_ids: tuple[str, ...], request: ReadRequest
    ) -> ReadAnswer:
        with self._unit_of_work() as unit:
            # Scoped to the Principal: a foreign id is absent exactly as an unknown one.
            found = {
                message.message_id: message
                for message in unit.communications.list_messages(principal_id, message_ids)
            }
            ordered = [found[message_id] for message_id in message_ids if message_id in found]
            messages = self._assemble(unit, principal_id, ordered, request.include_text)
        return ReadAnswer(
            messages=messages,
            not_found=tuple(message_id for message_id in message_ids if message_id not in found),
            next_cursor=None,
            cursor_state=None,
            identifier_version=self._identifier_version,
        )

    def _read_thread(
        self,
        principal_id: str,
        conversation_id: str,
        request: ReadRequest,
        grants: Iterable[tuple[str, str | None]] | None,
    ) -> ReadAnswer:
        binding = cursor_binding(
            capability=COMMUNICATIONS_READ,
            principal_id=principal_id,
            request={"conversation_id": conversation_id, "include_text": request.include_text},
            identifier_version=self._identifier_version,
        )
        scope = self._scope(grants)
        after = self._cursor(request.cursor, parse=thread_position, binding=binding, scope=scope)
        if after is False:
            return ReadAnswer(
                messages=(),
                not_found=(),
                next_cursor=None,
                cursor_state=SCOPE_CHANGED_RESTART_REQUIRED,
                identifier_version=self._identifier_version,
            )
        position = after if isinstance(after, ThreadPosition) else None
        with self._unit_of_work() as unit:
            rows = unit.communications.list_conversation_page(
                principal_id,
                conversation_id,
                after=None if position is None else (position.message_time, position.message_id),
                limit=THREAD_PAGE_SIZE + 1,
            )
            page = rows[:THREAD_PAGE_SIZE]
            messages = self._assemble(unit, principal_id, page, request.include_text)
        next_cursor = None
        if len(rows) > THREAD_PAGE_SIZE:
            last = page[-1]
            next_cursor = encode_cursor(
                CommunicationsCursor(
                    binding=binding,
                    scope=scope,
                    position=ThreadPosition(last.message_time, last.message_id),
                )
            )
        not_found = (conversation_id,) if not rows and position is None else ()
        return ReadAnswer(
            messages=messages,
            not_found=not_found,
            next_cursor=next_cursor,
            cursor_state=None,
            identifier_version=self._identifier_version,
        )

    def _assemble(
        self,
        unit: UnitOfWork,
        principal_id: str,
        messages: Sequence[CommunicationMessageRecord],
        include_text: bool,
    ) -> tuple[ReadMessage, ...]:
        repository = unit.communications
        windows: dict[str, MessageCoverage] = {}
        budget = MAX_ANSWER_TEXT_CHARACTERS
        assembled: list[ReadMessage] = []
        for message in messages:
            projection = message.projection
            observations = repository.list_observations(principal_id, message.message_id)
            participants = tuple(
                ParticipantView(
                    field=participant.field,
                    address=participant.address,
                    sources=tuple(
                        ParticipantSource(
                            observation.observation_id,
                            observation.folder_role,
                            observation.lane_verification,
                        )
                        for observation in observations
                        if participant.address
                        in observation.participants.get(participant.field, ())
                    ),
                )
                for participant in repository.list_participants(principal_id, message.message_id)
            )
            pointed = next(
                (
                    observation
                    for observation in observations
                    if (observation.snapshot_id, observation.record_ordinal)
                    == (projection.text_snapshot_id, projection.text_record_ordinal)
                ),
                None,
            )
            snapshot_id = projection.text_snapshot_id
            if snapshot_id not in windows:
                window = unit.ingestion.get_coverage_window(principal_id, snapshot_id)
                windows[snapshot_id] = MessageCoverage(
                    snapshot_id=snapshot_id,
                    start=None if window is None else window.start_utc,
                    end=None if window is None else window.end_utc,
                    coverage_state=None if window is None else window.coverage_state,
                    lanes=() if window is None else tuple(window.lane_states),
                )
            identifiers = tuple(
                sorted(
                    TechnicalIdentifier(IdentifierKind(row.kind), row.value).normalized
                    for row in repository.list_identifiers(principal_id, message.message_id)
                    if row.extractor_version == self._identifier_version
                )
            )
            text, truncated, omitted = None, False, None
            if not include_text:
                omitted = TEXT_NOT_REQUESTED
            elif projection.body_state in _NO_TEXT_BODY_STATES or projection.search_text is None:
                omitted = TEXT_NONE  # a withheld body is never returned (section 13)
            else:
                text = projection.search_text[:MAX_MESSAGE_TEXT_CHARACTERS]
                truncated = len(projection.search_text) > MAX_MESSAGE_TEXT_CHARACTERS
                if len(text) > budget:
                    text, truncated, omitted = None, False, TEXT_ANSWER_CAP
                else:
                    budget -= len(text)
            assembled.append(
                ReadMessage(
                    message_id=message.message_id,
                    message_time=message.message_time,
                    message_time_basis=message.message_time_basis,
                    subject=message.subject,
                    sender_address=message.sender_address,
                    conversation_id=message.conversation_id,
                    has_attachments=message.has_attachments,
                    body_state=projection.body_state,
                    content_type=projection.content_type,
                    body_utf8_bytes=projection.body_utf8_bytes,
                    flags=Flags(
                        identity_conflict=message.identity_conflict,
                        participants_reconciled=message.participants_reconciled,
                        participants_disagreed=message.participants_disagreed,
                        source_unavailable=message.source_unavailable,
                        search_text_flags=projection.search_text_flags,
                    ),
                    participants=participants,
                    observations=ObservationSummary(
                        count=len(observations),
                        by_classification=_counted(o.classification for o in observations),
                        by_folder_role=_counted(o.folder_role for o in observations),
                        by_lane_verification=_counted(o.lane_verification for o in observations),
                        selected_utc=None if pointed is None else pointed.selected_utc,
                        received_utc=None if pointed is None else pointed.received_utc,
                        sent_utc=None if pointed is None else pointed.sent_utc,
                    ),
                    text_snapshot_id=snapshot_id,
                    text_record_ordinal=projection.text_record_ordinal,
                    first_snapshot_id=message.first_snapshot_id,
                    latest_snapshot_id=message.latest_snapshot_id,
                    coverage=windows[snapshot_id],
                    identifiers=identifiers,
                    search_text_version=projection.search_text_version,
                    search_text=text,
                    truncated=truncated,
                    text_omitted=omitted,
                )
            )
        return tuple(assembled)

    # --- coverage -------------------------------------------------------------------------

    def coverage(self, principal_id: str, request: CoverageRequest) -> CoverageAnswer:
        start, end, source = check_coverage_request(request)
        with self._unit_of_work() as unit:
            sources = communications_source_ids(unit, principal_id)
            if source is not None:
                if source not in sources:  # unknown and foreign alike
                    raise NotFoundError(SafeDetail.SOURCE)
                sources = (source,)
            summary = summarize_coverage(
                coverage_facts(unit, principal_id, sources), now=self._clock()
            )
        return CoverageAnswer(source=source, coverage=range_view(summary, start, end))


def _counted(values: Iterable[str]) -> Mapping[str, int]:
    return dict(sorted(Counter(values).items()))


def _result(row: CommunicationSearchRow, lanes: Sequence[tuple[str, str]]) -> SearchResult:
    no_text = row.body_state in _NO_TEXT_BODY_STATES
    return SearchResult(
        message_id=row.message_id,
        message_time=row.message_time,
        subject=row.subject,
        sender_address=row.sender_address,
        conversation_id=row.conversation_id,
        conversation_hits=row.conversation_hits,
        has_attachments=row.has_attachments,
        body_state=row.body_state,
        tier=row.tier,
        rank=row.rank,
        participant_overlap=row.overlap,
        matched_identifier_kinds=row.matched_identifier_kinds,
        # A withheld or truncated body has no text; never a snippet of one.
        snippet=None if no_text or row.snippet is None else row.snippet[:SNIPPET_CHARACTERS],
        search_text_version=row.search_text_version,
        flags=Flags(
            identity_conflict=row.identity_conflict,
            participants_reconciled=row.participants_reconciled,
            participants_disagreed=row.participants_disagreed,
            source_unavailable=row.source_unavailable,
            search_text_flags=row.search_text_flags,
        ),
        lanes=tuple(Lane(role, verification) for role, verification in lanes),
    )


# --- answers as payloads (WP4-S5) ----------------------------------------------------------
#
# What the three capabilities answer on every transport. Instants are RFC 3339
# UTC; every answer states its versions and coverage (ruling D8), the cursor
# state (C2: `scope_changed_restart_required` is an answer, not a refusal) and,
# for a search, the D4-final `text_fallback` and the R8 `query_state`. Derived
# text only: a withheld or truncated body has `snippet`/`search_text` null and
# no raw body exists to render (R-OP-3).


def _when(value: datetime | None) -> str | None:
    return None if value is None else format_rfc3339(value)


def _interval(interval: Interval) -> dict[str, object]:
    return {"start": format_rfc3339(interval.start), "end": format_rfc3339(interval.end)}


def _flags(flags: Flags) -> dict[str, object]:
    return {
        "identity_conflict": flags.identity_conflict,
        "participants_reconciled": flags.participants_reconciled,
        "participants_disagreed": flags.participants_disagreed,
        "source_unavailable": flags.source_unavailable,
        "search_text_flags": list(flags.search_text_flags),
    }


def _range_coverage(view: RangeCoverageView) -> dict[str, object]:
    return {
        "state": view.state,
        "start": _when(view.start),
        "end": _when(view.end),
        "intervals": [_interval(interval) for interval in view.intervals],
        "intervals_total": view.intervals_total,
        "gaps": [_interval(gap) for gap in view.gaps],
        "gaps_total": view.gaps_total,
        "freshness_seconds": view.freshness_seconds,
        "earliest_covered": _when(view.earliest_covered),
        "latest_covered": _when(view.latest_covered),
        "snapshot_count": view.snapshot_count,
        "lanes": [
            {
                "key_kind": lane.key_kind,
                "role": lane.role,
                "lane": lane.lane,
                "latest_state": lane.latest_state,
                "latest_authorized": lane.latest_authorized,
            }
            for lane in view.lanes
        ],
    }


def search_payload(answer: SearchAnswer) -> dict[str, object]:
    """What `communications.search` answers."""
    return {
        "results": [
            {
                "message_id": result.message_id,
                "message_time": format_rfc3339(result.message_time),
                "subject": result.subject,
                "sender_address": result.sender_address,
                "conversation_id": result.conversation_id,
                "conversation_hits": result.conversation_hits,
                "has_attachments": result.has_attachments,
                "body_state": result.body_state,
                "tier": result.tier,
                "rank": result.rank,
                "participant_overlap": result.participant_overlap,
                "matched_identifier_kinds": list(result.matched_identifier_kinds),
                "snippet": result.snippet,
                "search_text_version": result.search_text_version,
                "flags": _flags(result.flags),
                "lanes": [
                    {"folder_role": lane.folder_role, "lane_verification": lane.lane_verification}
                    for lane in result.lanes
                ],
            }
            for result in answer.results
        ],
        "next_cursor": answer.next_cursor,
        "cursor_state": answer.cursor_state,
        "query_state": answer.query_state,
        "text_fallback": answer.text_fallback,
        "identifiers": list(answer.identifiers),
        "versions": {
            "search_text_versions": list(answer.versions.search_text_versions),
            "identifier_version": answer.versions.identifier_version,
            "identifier_version_pending": answer.versions.identifier_version_pending,
        },
        "coverage": _range_coverage(answer.coverage),
    }


def _read_message(message: ReadMessage) -> dict[str, object]:
    observations = message.observations
    coverage = message.coverage
    return {
        "message_id": message.message_id,
        "message_time": format_rfc3339(message.message_time),
        "message_time_basis": message.message_time_basis,
        "subject": message.subject,
        "sender_address": message.sender_address,
        "conversation_id": message.conversation_id,
        "has_attachments": message.has_attachments,
        "body_state": message.body_state,
        "content_type": message.content_type,
        "body_utf8_bytes": message.body_utf8_bytes,
        "flags": _flags(message.flags),
        "participants": [
            {
                "field": participant.field,
                "address": participant.address,
                "sources": [
                    {
                        "observation_id": source.observation_id,
                        "folder_role": source.folder_role,
                        "lane_verification": source.lane_verification,
                    }
                    for source in participant.sources
                ],
            }
            for participant in message.participants
        ],
        "observations": {
            "count": observations.count,
            "by_classification": dict(observations.by_classification),
            "by_folder_role": dict(observations.by_folder_role),
            "by_lane_verification": dict(observations.by_lane_verification),
            "selected_utc": _when(observations.selected_utc),
            "received_utc": _when(observations.received_utc),
            "sent_utc": _when(observations.sent_utc),
        },
        "source_pointer": {
            "text_snapshot_id": message.text_snapshot_id,
            "text_record_ordinal": message.text_record_ordinal,
            "first_snapshot_id": message.first_snapshot_id,
            "latest_snapshot_id": message.latest_snapshot_id,
        },
        "coverage": {
            "snapshot_id": coverage.snapshot_id,
            "start": _when(coverage.start),
            "end": _when(coverage.end),
            "coverage_state": coverage.coverage_state,
            "lanes": [dict(lane) for lane in coverage.lanes],
        },
        "identifiers": list(message.identifiers),
        "search_text_version": message.search_text_version,
        "search_text": message.search_text,
        "truncated": message.truncated,
        "text_omitted": message.text_omitted,
    }


def read_payload(answer: ReadAnswer) -> dict[str, object]:
    """What `communications.read` answers (a batch, or one conversation page)."""
    return {
        "messages": [_read_message(message) for message in answer.messages],
        "not_found": list(answer.not_found),
        "next_cursor": answer.next_cursor,
        "cursor_state": answer.cursor_state,
        "identifier_version": answer.identifier_version,
    }


def coverage_payload(answer: CoverageAnswer) -> dict[str, object]:
    """What `communications.coverage` answers."""
    return {"source": answer.source, "coverage": _range_coverage(answer.coverage)}
