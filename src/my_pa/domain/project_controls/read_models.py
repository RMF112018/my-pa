"""The Constraint read plane's value types: what a reader is shown, and asks for.

PC-CM-IMP-WP03. Every type here is a *projection*, not an aggregate. That
distinction is the reason this module exists at all: `constraint.py`'s
`ProjectConstraint` enforces the invariants a write must satisfy, and a legally
persisted legacy workbook row does not satisfy them — the DDL's four
`legacy_incomplete` relaxations permit a closed record with no public code, no
`published_at`, and no completion date. Handing such a row to the write
constructor would raise, so `PersistedConstraintRecord` is a faithful picture of
a row instead: its nullability matches the stored columns rather than the write
rules, and it validates no cross-field relationship whatsoever. The aggregate
stays strict; the read plane stays able to show what is actually there.

Nothing here carries a `principal_id` except `PersistedConstraintRecord`, which
is the repository's internal hand-off to the read service and never leaves it.
No view type names one, no party reference contains a raw `prn_` value, and no
history digest, idempotency key, client context, correlation identifier,
evidence payload, workbook locator or sync digest is projected. The read plane
can only disclose what it has a field for, so the fields are the boundary.

`ConstraintListQuery` is bounded on construction, in the shape
`domain.search.query.SearchRequest` established: every limit is checked where
the request is built, so no code path holds an unbounded one and checks it
later. `ConstraintListCursor` follows `domain.search.query.SearchCursor`
exactly — compact sorted-key JSON, base64url, opaque and unsigned, with a
sha-256 `binding` over everything that gives a page its meaning, so a cursor
reused under a different Principal, Project, filter or sort cannot validate.

Sorting, paging and the SQL that answers a query are the persistence adapter's;
what lives here is the vocabulary both sides agree on.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Final

from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.project_controls.category import ConstraintCategoryState
from my_pa.domain.project_controls.constraint import (
    ConstraintAttention,
    ConstraintAttentionReason,
    ConstraintFieldKey,
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintRecordQuality,
)
from my_pa.domain.project_controls.history import (
    ConstraintMutationActor,
    ConstraintMutationOperation,
    ConstraintMutationOutcome,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef

__all__ = [
    "DEFAULT_LIST_LIMIT",
    "LIST_CURSOR_VERSION",
    "MAX_CURSOR_CHARACTERS",
    "MAX_LIST_LIMIT",
    "MAX_SEARCH_CHARACTERS",
    "MIN_SEARCH_CHARACTERS",
    "PRINCIPAL_DISPLAY_LABEL",
    "PRINCIPAL_PARTY_REF",
    "RECENT_WINDOW_DAYS",
    "UNKNOWN_DISPLAY_LABEL",
    "UNRESOLVED_PARTY_REF",
    "ConstraintCategoryRef",
    "ConstraintCategoryRow",
    "ConstraintCategoryView",
    "ConstraintCompletionView",
    "ConstraintCursorError",
    "ConstraintEvidenceLinkRow",
    "ConstraintEvidenceLinkView",
    "ConstraintGrouping",
    "ConstraintHistoryEntryView",
    "ConstraintHistoryPage",
    "ConstraintHistoryPosition",
    "ConstraintHistoryRow",
    "ConstraintListCursor",
    "ConstraintListEntry",
    "ConstraintListPage",
    "ConstraintListQuery",
    "ConstraintListScope",
    "ConstraintListSpec",
    "ConstraintOverview",
    "ConstraintOverviewFacts",
    "ConstraintPartyRow",
    "ConstraintQueryError",
    "ConstraintRecentFilter",
    "ConstraintRelationshipRow",
    "ConstraintRelationshipView",
    "ConstraintSort",
    "ConstraintSyncFacts",
    "ConstraintSyncHealthView",
    "ConstraintSyncStateView",
    "ConstraintSyncSummaryView",
    "ConstraintView",
    "ConstraintVoidView",
    "PartyRefView",
    "PersistedConstraintRecord",
    "RelationshipDirection",
    "SortDirection",
    "attention_for",
    "legacy_missing_fields",
    "list_binding_digest",
    "party_refs_of",
]

#: Page sizes. 50 is the accepted Register figure; 100 is the ceiling every
#: other paged plane in this repository already uses (`MAX_PAGE_SIZE`,
#: `domain.search.query`), so a Constraint page cannot be the one place an
#: outsider chooses how much work a request is.
DEFAULT_LIST_LIMIT: Final = 50
MAX_LIST_LIMIT: Final = 100

#: Search bounds. One character matches most of a register and is refused rather
#: than served; 512 is the same ceiling `domain.search.query` puts on a query,
#: for the same reason — normalization of an unbounded string is work whose size
#: the caller picks.
MIN_SEARCH_CHARACTERS: Final = 2
MAX_SEARCH_CHARACTERS: Final = 512

#: Longest cursor token accepted *before* it is decoded.
MAX_CURSOR_CHARACTERS: Final = 512

#: How far back "recently" reaches, in calendar days, for both recent filters.
RECENT_WINDOW_DAYS: Final = 7

#: The two closed party-reference tokens that name something other than an
#: Entity. `PRINCIPAL_PARTY_REF` is the whole identity of a PRINCIPAL party —
#: there is one Principal per partition and it *is* the partition, so a constant
#: names it exactly and discloses nothing. `UNRESOLVED_PARTY_REF` is a bucket
#: filter and never an individual party's identity, because an UNRESOLVED party
#: deliberately has none (`party.py`).
PRINCIPAL_PARTY_REF: Final = PartyKind.PRINCIPAL.value
UNRESOLVED_PARTY_REF: Final = PartyKind.UNRESOLVED.value

#: What a PRINCIPAL party is called when it is shown. A backend constant, not a
#: lookup: no per-Principal display source exists in this repository, and
#: `party.py` forbids putting a `prn_` value or a fabricated Entity name in a
#: party reference. Stated here once so no caller invents a second answer.
PRINCIPAL_DISPLAY_LABEL: Final = "Me"

#: What an ENTITY party is called when neither the stored display label, the
#: same-Principal Entity lookup, nor the preserved source wording supplies one.
#: The `ent_` identifier is deliberately *not* used as a label: an identifier
#: shown as a name reads as a name.
UNKNOWN_DISPLAY_LABEL: Final = "Unknown"

#: The one list order family a cursor binds, named so that changing the sort
#: contract invalidates every cursor issued under the old one.
LIST_CURSOR_VERSION: Final = 1

#: Unicode general categories a search term may not contain, matching
#: `domain.search.query`: control, format, surrogate, private-use, unassigned.
_FORBIDDEN_SEARCH_CATEGORIES: Final[frozenset[str]] = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})

_SHA256_HEX_LENGTH: Final = 64


class ConstraintQueryError(ValueError):
    """A list request was out of bounds or malformed. `code` is stable.

    Every message names the rule and never the value: this error is handed the
    caller's own search text and party references, and there is no code path
    here that interpolates one into a message.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ConstraintCursorError(ValueError):
    """A list cursor was not readable. `code` is stable and there is one message.

    A cursor that reported *why* it was rejected would tell whoever supplied it
    how to build a better one, and no legitimate caller needs to know: a cursor
    comes from this system or it does not.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ConstraintSyncStateView(StrEnum):
    """The sync states derivable from persisted rows alone. Exactly four.

    The frontend recognises ten names. Six of them — external import pending,
    workbook unavailable, schema unsupported, partial, verification pending and
    verification failed — each require a connector call, a workbook read, or a
    live run comparison, which is WP11's behavior and not something a read plane
    may assert. They are not members here, so no read path can emit one to
    satisfy a fixture.
    """

    NEVER_SYNCED = "never_synced"
    IN_SYNC = "in_sync"
    DB_EXPORT_PENDING = "db_export_pending"
    CONFLICT = "conflict"


class ConstraintListScope(StrEnum):
    """The four lifecycle scopes a Register page can be asked for.

    `OPEN` is the four active states, `CLOSED` is both terminal states (the row
    keeps `status` so CLOSED and VOID stay distinct), `DRAFT` is the unpublished
    state, and `ALL` applies no lifecycle predicate at all — Principal, Project
    and paging still bound it.
    """

    OPEN = "open"
    CLOSED = "closed"
    ALL = "all"
    DRAFT = "draft"


class ConstraintRecentFilter(StrEnum):
    """The two "recently" filters. At most one applies to a request.

    `RECENTLY_CHANGED` is measured against the backend UTC instant because
    `updated_at` is a `timestamptz`; `RECENTLY_CLOSED` is measured against the
    Project's own calendar date, because a completion date is a Project date.
    """

    RECENTLY_CHANGED = "recently_changed"
    RECENTLY_CLOSED = "recently_closed"


class ConstraintSort(StrEnum):
    """The five orders a Register page can be asked for."""

    CODE = "code"
    DATE_IDENTIFIED = "date_identified"
    DAYS_ELAPSED = "days_elapsed"
    DUE_DATE = "due_date"
    UPDATED_AT = "updated_at"


class SortDirection(StrEnum):
    """Ascending or descending. Both are supported for every sort."""

    ASC = "asc"
    DESC = "desc"


class ConstraintGrouping(StrEnum):
    """How a reader wants the page grouped.

    The server returns a stable group key per row and never a grouped result
    set, so a row is never duplicated across groups. `BIC` and `RESPONSIBLE` are
    multi-valued and carry no group totals: the accepted contract does not
    define what a multi-party row's membership is, and inventing one would be a
    number a reader could not check.
    """

    NONE = "none"
    CATEGORY = "category"
    STATUS = "status"
    BIC = "bic"
    RESPONSIBLE = "responsible"


class RelationshipDirection(StrEnum):
    """Which end of a Constraint relationship the read subject is."""

    OUTGOING = "outgoing"
    INCOMING = "incoming"


@dataclass(frozen=True, slots=True)
class PersistedConstraintRecord:
    """One row of `knowledge.project_constraints`, exactly as stored.

    Nullability here matches the DDL and **not** the write invariants. A legacy
    workbook import may legally be `CLOSED` with no `constraint_code`, no
    `published_at`, no `completion_date` and no `date_identified`, and this
    record carries all four as `None` without complaint. It performs no
    cross-field validation of any kind: `_check_publication_shape` and
    `_check_terminal_fields` belong to the aggregate, which the write path still
    uses unmodified.

    This is the one type in this module that carries `principal_id`. It is the
    repository's hand-off to the read service and is never projected: every
    `…View`, `…Entry`, `…Overview` and `…Page` below is built from it and names
    no partition.

    `bic` and `responsible` are the ordered party references when the hydrator
    was given them — the single-record read supplies them, and the list read
    does not, because a page's parties are read once in bulk rather than once
    per row.
    """

    constraint_id: str
    principal_id: str
    lifecycle_state: ConstraintLifecycleState
    record_quality: ConstraintRecordQuality
    origin: ConstraintOrigin
    version: int
    created_at: datetime
    updated_at: datetime
    project_id: str | None = None
    category_id: str | None = None
    constraint_code: str | None = None
    description: str | None = None
    date_identified: date | None = None
    due_date: date | None = None
    reference: str | None = None
    current_update: str | None = None
    completion_date: date | None = None
    closure_commentary: str | None = None
    voided_date: date | None = None
    void_reason: str | None = None
    published_at: datetime | None = None
    bic: tuple[PartyRef, ...] = ()
    responsible: tuple[PartyRef, ...] = ()


@dataclass(frozen=True, slots=True)
class PartyRefView:
    """One BIC or Responsible party as a reader sees it.

    `party_ref_id` is the filter identity and `display_label` is presentation
    text — never the other way round. A PRINCIPAL party's identity is the closed
    token `"principal"`; an ENTITY party's is its `ent_` identifier; an
    UNRESOLVED party has none, so `party_ref_id` is `None` and it is filterable
    only as the `"unresolved"` bucket. `entity_id` is present only for an ENTITY
    party, which by construction is one visible in the same Principal partition.
    """

    kind: PartyKind
    party_ref_id: str | None
    display_label: str
    entity_id: str | None = None


@dataclass(frozen=True, slots=True)
class ConstraintCategoryRef:
    """The Category a Constraint belongs to, as much of it as a row needs."""

    category_id: str
    prefix: str
    title: str


@dataclass(frozen=True, slots=True)
class ConstraintCategoryView:
    """One Constraint Category, with its allocator counters and derived flags.

    `archived_at` is deliberately absent: the accepted contract names an active
    flag, not an archival timestamp, and a read plane that surfaced one would be
    asserting a mutation history it did not read.
    """

    category_id: str
    project_id: str
    prefix: str
    title: str
    description: str | None
    display_order: int
    state: ConstraintCategoryState
    next_sequence: int
    issued_count: int
    version: int
    prefix_locked: bool

    @property
    def is_active(self) -> bool:
        """Whether this Category still admits a normal Publish."""
        return self.state is ConstraintCategoryState.ACTIVE


@dataclass(frozen=True, slots=True)
class ConstraintListEntry:
    """One Register row: the stored fields plus every backend-derived flag.

    The four derived booleans and `days_elapsed` are computed here rather than
    in the browser so that a reader and the overview cannot disagree about what
    is overdue. `group_keys` is this row's stable membership under the requested
    grouping — one key for Category or Status, zero or many for the two party
    groupings, and never a reason to return the row twice.
    """

    constraint_id: str
    project_id: str | None
    constraint_code: str | None
    description: str | None
    category: ConstraintCategoryRef | None
    status: ConstraintLifecycleState
    date_identified: date | None
    due_date: date | None
    bic: tuple[PartyRefView, ...]
    responsible: tuple[PartyRefView, ...]
    reference: str | None
    days_elapsed: int | None
    version: int
    updated_at: datetime
    is_overdue: bool
    is_due_soon: bool
    in_my_court: bool
    record_quality: ConstraintRecordQuality
    needs_attention: bool
    sync_state: ConstraintSyncStateView
    group_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConstraintCompletionView:
    """How a CLOSED Constraint was closed. Both fields stay `None` for a legacy row."""

    completion_date: date | None
    closure_commentary: str | None


@dataclass(frozen=True, slots=True)
class ConstraintVoidView:
    """How a VOID Constraint was voided."""

    voided_date: date | None
    void_reason: str | None


@dataclass(frozen=True, slots=True)
class ConstraintHistoryEntryView:
    """One mutation receipt, projected to what a reader may see.

    `request_digest`, `idempotency_key`, `client_context` and `correlation_id`
    are stored and are deliberately not fields here: a receipt tells a reader
    that a mutation was attempted and what became of it, not what the caller
    sent or how a replay was recognised.
    """

    history_id: str
    operation: ConstraintMutationOperation
    actor: ConstraintMutationActor
    outcome: ConstraintMutationOutcome
    before_version: int
    after_version: int
    occurred_at: datetime
    revision_id: str | None
    safe_failure_reason: str | None


@dataclass(frozen=True, slots=True)
class ConstraintRelationshipView:
    """One relationship, from the read subject's end.

    The related Constraint's code and status come from a join inside the same
    Principal partition, so a relationship whose other end is not readable is
    not projected rather than projected with a gap.
    """

    relationship_id: str
    relationship_type: str
    direction: RelationshipDirection
    related_constraint_id: str
    related_constraint_code: str | None
    related_status: ConstraintLifecycleState


@dataclass(frozen=True, slots=True)
class ConstraintEvidenceLinkView:
    """One cited piece of evidence, as a validated reference and never as content.

    No provider payload, filesystem path, or workbook cell coordinate has a
    field here, because the link records what was cited and not what it said.
    """

    evidence_link_id: str
    evidence_kind: str
    evidence_ref: str
    role: str


@dataclass(frozen=True, slots=True)
class ConstraintSyncSummaryView:
    """What is known about one Constraint's synchronisation, from stored rows only."""

    state: ConstraintSyncStateView
    last_verified_at: datetime | None
    conflict_count: int


@dataclass(frozen=True, slots=True)
class ConstraintSyncHealthView:
    """The Project-level sync roll-up shown on the overview."""

    state: ConstraintSyncStateView
    open_conflict_count: int
    last_verified_at: datetime | None


@dataclass(frozen=True, slots=True)
class ConstraintView:
    """One Constraint in full: every list field, plus what only a detail read shows."""

    constraint_id: str
    project_id: str | None
    constraint_code: str | None
    description: str | None
    category: ConstraintCategoryRef | None
    status: ConstraintLifecycleState
    date_identified: date | None
    due_date: date | None
    bic: tuple[PartyRefView, ...]
    responsible: tuple[PartyRefView, ...]
    reference: str | None
    days_elapsed: int | None
    version: int
    created_at: datetime
    updated_at: datetime
    is_overdue: bool
    is_due_soon: bool
    in_my_court: bool
    record_quality: ConstraintRecordQuality
    needs_attention: bool
    needs_attention_reasons: tuple[ConstraintAttentionReason, ...]
    missing_fields: tuple[ConstraintFieldKey, ...]
    is_published: bool
    published_at: datetime | None
    current_update: str | None
    completion: ConstraintCompletionView | None
    void: ConstraintVoidView | None
    sync: ConstraintSyncSummaryView
    relationships: tuple[ConstraintRelationshipView, ...]
    evidence_links: tuple[ConstraintEvidenceLinkView, ...]


@dataclass(frozen=True, slots=True)
class ConstraintOverview:
    """The Project's Constraint position at one instant, on the Project's calendar.

    Flat by decision: three accepted sources define this same field set without
    a wrapper, and grouping the counts under a `totals` envelope is a wire
    shaping choice a later work package can make without changing this type.
    `average_open_age_business_days` is `None` — never `0.0` — when nothing
    qualifies, because an average of nothing is not zero.
    """

    project_id: str
    project_today: date
    project_timezone: str
    total_open: int
    overdue: int
    due_soon: int
    due_soon_through: date
    average_open_age_business_days: float | None
    in_my_court: int
    on_hold: int
    recently_changed: int
    recently_closed: int
    draft: int
    needs_attention: int
    sync_health: ConstraintSyncHealthView
    as_of: datetime


@dataclass(frozen=True, slots=True)
class ConstraintListPage:
    """One bounded page of Register rows.

    A page that hit its limit is reported as truncated rather than returned as
    if it were all there was.
    """

    entries: tuple[ConstraintListEntry, ...]
    is_truncated: bool
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ConstraintHistoryPage:
    """One bounded page of mutation receipts, newest first."""

    entries: tuple[ConstraintHistoryEntryView, ...]
    is_truncated: bool
    next_cursor: str | None


# --- Rows the persistence adapter returns ------------------------------------
#
# These are the shapes the read port promises, one per statement family. They
# are plain pictures of selected columns: no invariant, no derivation, and no
# partition identifier beyond what the row is already scoped by.


@dataclass(frozen=True, slots=True)
class ConstraintCategoryRow:
    """One `constraint_categories` row, allocator counters included."""

    category_id: str
    project_id: str
    prefix: str
    title: str
    description: str | None
    display_order: int
    state: ConstraintCategoryState
    next_sequence: int
    issued_count: int
    version: int
    prefix_locked_at: datetime | None


@dataclass(frozen=True, slots=True)
class ConstraintPartyRow:
    """One `project_constraint_parties` row, in its stored role and ordinal.

    Both labels are returned because they are two different facts: the stored
    display label is a presentation snapshot, and `original_label` is preserved
    source wording that an UNRESOLVED party is guaranteed to have.
    """

    constraint_id: str
    role: str
    ordinal: int
    party_kind: PartyKind
    entity_id: str | None
    display_label: str | None
    original_label: str | None


@dataclass(frozen=True, slots=True)
class ConstraintHistoryRow:
    """One `project_constraint_history` row, already narrowed to the safe columns.

    The digest, idempotency key, client context and correlation identifier are
    not selected, so the projection cannot leak one by growing a field later.
    """

    history_id: str
    constraint_id: str
    operation: ConstraintMutationOperation
    actor: ConstraintMutationActor
    outcome: ConstraintMutationOutcome
    before_version: int
    after_version: int
    occurred_at: datetime
    revision_id: str | None
    safe_failure_reason: str | None


@dataclass(frozen=True, slots=True)
class ConstraintRelationshipRow:
    """One relationship with the related Constraint's readable facts joined in."""

    relationship_id: str
    relationship_type: str
    direction: RelationshipDirection
    related_constraint_id: str
    related_constraint_code: str | None
    related_status: ConstraintLifecycleState


@dataclass(frozen=True, slots=True)
class ConstraintEvidenceLinkRow:
    """One `project_constraint_evidence_links` row, reference only."""

    evidence_link_id: str
    evidence_kind: str
    evidence_ref: str
    role: str


@dataclass(frozen=True, slots=True)
class ConstraintSyncFacts:
    """Everything the four derivable sync states need, read and nothing more.

    `has_target` is whether the Project has a `constraint_sync_targets` row at
    all; `baseline_versions` maps a Constraint identifier to the Constraint
    version its sync baseline was taken at; `open_conflict_counts` maps one to
    its number of `open` conflicts. A Constraint absent from both mappings has
    never been synced. No run, lease, workbook digest, provider version or
    external candidate is carried, because none of them is derivable state — they
    are WP11's behavior.
    """

    has_target: bool
    last_verified_at: datetime | None
    baseline_versions: Mapping[str, int]
    open_conflict_counts: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class ConstraintOverviewFacts:
    """The overview's counts as the aggregate statement produced them.

    The business-day age arrives as a sum and a denominator rather than an
    average so that the "no qualifying row" case is a zero denominator here and
    an explicit `None` in the view, instead of a zero that reads as an answer.
    """

    total_open: int
    overdue: int
    due_soon: int
    in_my_court: int
    on_hold: int
    recently_changed: int
    recently_closed: int
    draft: int
    needs_attention: int
    open_age_business_day_sum: int
    open_age_denominator: int


@dataclass(frozen=True, slots=True)
class ConstraintHistoryPosition:
    """The keyset position a history page continues from.

    `occurred_at` alone is not a total order — two receipts can share an
    instant — so the identifier travels with it and the comparison uses both.
    """

    occurred_at: datetime
    history_id: str

    def __post_init__(self) -> None:
        validate_identifier(self.history_id, IdKind.PROJECT_CONSTRAINT_HISTORY)
        object.__setattr__(self, "occurred_at", ensure_utc(self.occurred_at))


# --- The list request ---------------------------------------------------------


def _normalize_search(text: str) -> str | None:
    """Fold `text` to its canonical searchable form, or `None` if it is blank.

    NFC first, so that two spellings of the same character are one term, then
    the forbidden general categories are refused rather than stripped: silently
    removing a control character answers a question the caller did not ask.
    """
    folded = unicodedata.normalize("NFC", text).strip()
    if not folded:
        return None
    for character in folded:
        if unicodedata.category(character) in _FORBIDDEN_SEARCH_CATEGORIES:
            raise ConstraintQueryError(
                "constraint_search_forbidden_character",
                "a search term contains only printable characters",
            )
    if len(folded) < MIN_SEARCH_CHARACTERS:
        raise ConstraintQueryError(
            "constraint_search_too_short",
            f"a search term is at least {MIN_SEARCH_CHARACTERS} characters",
        )
    if len(folded) > MAX_SEARCH_CHARACTERS:
        raise ConstraintQueryError(
            "constraint_search_too_long",
            f"a search term is at most {MAX_SEARCH_CHARACTERS} characters",
        )
    return folded


def _check_party_refs(name: str, refs: frozenset[str]) -> None:
    """Refuse any party reference that is neither closed token nor an `ent_` identity.

    A syntactically valid identifier belonging to another Principal is *not*
    refused here: it is passed through and matches nothing, which is the same
    answer an absent one gives.
    """
    for ref in refs:
        if ref in (PRINCIPAL_PARTY_REF, UNRESOLVED_PARTY_REF):
            continue
        try:
            validate_identifier(ref, IdKind.ENTITY)
        except InvalidIdentifierError as error:
            raise ConstraintQueryError(
                "constraint_party_ref_unknown",
                f"a {name} reference is 'principal', 'unresolved', or an entity identity",
            ) from error


@dataclass(frozen=True, slots=True)
class ConstraintListQuery:
    """One Register request, bounded and normalised on construction.

    Filters compose as OR within a family and AND across families, and AND with
    the scope, the quick filters and the search term. There is no unsupported
    combination and no filter that widens the Principal or Project predicate,
    which are not expressible here at all.

    `search_text` is stored already normalised, so the value this object holds
    is the value the statement and the cursor binding both use. A blank term is
    not an error and not a predicate: it is simply no search. The field is named
    for the text it holds rather than for the operation, because a bare `search`
    attribute collides by name with the memory plane's `search` port method and
    `test_every_capability_reaching_a_memory_row_is_declared.py` sweeps that name
    across every module importing `contracts.ports` — a collision that guard's
    own prose calls the worse cost, since absorbing it would mean growing an
    allowlist that scales with the port surface rather than with this plane.
    """

    scope: ConstraintListScope = ConstraintListScope.OPEN
    statuses: frozenset[ConstraintLifecycleState] = field(default_factory=frozenset)
    category_ids: frozenset[str] = field(default_factory=frozenset)
    bic_party_refs: frozenset[str] = field(default_factory=frozenset)
    responsible_party_refs: frozenset[str] = field(default_factory=frozenset)
    sync_states: frozenset[ConstraintSyncStateView] = field(default_factory=frozenset)
    record_qualities: frozenset[ConstraintRecordQuality] = field(default_factory=frozenset)
    overdue: bool = False
    due_soon: bool = False
    my_court: bool = False
    needs_attention: bool = False
    recent: ConstraintRecentFilter | None = None
    search_text: str | None = None
    sort: ConstraintSort = ConstraintSort.CODE
    direction: SortDirection = SortDirection.ASC
    grouping: ConstraintGrouping = ConstraintGrouping.CATEGORY
    limit: int = DEFAULT_LIST_LIMIT
    cursor: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise ConstraintQueryError(
                "constraint_list_limit_invalid", "a page limit is an integer"
            )
        if not 1 <= self.limit <= MAX_LIST_LIMIT:
            raise ConstraintQueryError(
                "constraint_list_limit_out_of_range",
                f"a page contains 1..{MAX_LIST_LIMIT} constraints",
            )
        for category_id in self.category_ids:
            validate_identifier(category_id, IdKind.CONSTRAINT_CATEGORY)
        _check_party_refs("bic", self.bic_party_refs)
        _check_party_refs("responsible", self.responsible_party_refs)
        if self.search_text is not None:
            object.__setattr__(self, "search_text", _normalize_search(self.search_text))
        if self.cursor is not None and len(self.cursor) > MAX_CURSOR_CHARACTERS:
            raise ConstraintCursorError(
                "constraint_cursor_unreadable", "the cursor is not readable"
            )

    @property
    def search_fingerprint(self) -> str:
        """A stable digest of the normalised search term, or `""` when there is none.

        This is what the cursor binds to, so "is this the same search" can be
        answered without the term being carried in the token.
        """
        if self.search_text is None:
            return ""
        return hashlib.sha256(self.search_text.encode("utf-8")).hexdigest()

    def binding(self, *, principal_id: str, project_id: str) -> str:
        """The digest a cursor issued for this request must carry."""
        return list_binding_digest(principal_id=principal_id, project_id=project_id, query=self)


def list_binding_digest(*, principal_id: str, project_id: str, query: ConstraintListQuery) -> str:
    """Everything a Register page's meaning depends on, as one sha-256 digest.

    Canonical JSON — sorted keys, sorted filter members, no incidental
    whitespace — so the digest is a function of the values rather than of how a
    set happened to iterate. The search enters as its fingerprint and never as
    its text. Because the Principal and the Project are inside the digest, a
    cursor cannot be replayed against another partition or another Project: it
    fails to validate, rather than being caught by a later check that could be
    forgotten.
    """
    canonical = json.dumps(
        {
            "bic": sorted(query.bic_party_refs),
            "categories": sorted(query.category_ids),
            "direction": query.direction.value,
            "due_soon": query.due_soon,
            "grouping": query.grouping.value,
            "limit": query.limit,
            "my_court": query.my_court,
            "needs_attention": query.needs_attention,
            "overdue": query.overdue,
            "principal_id": principal_id,
            "project_id": project_id,
            "qualities": sorted(quality.value for quality in query.record_qualities),
            "recent": None if query.recent is None else query.recent.value,
            "responsible": sorted(query.responsible_party_refs),
            "scope": query.scope.value,
            "search": query.search_fingerprint,
            "sort": query.sort.value,
            "statuses": sorted(status.value for status in query.statuses),
            "sync_states": sorted(state.value for state in query.sync_states),
            "v": LIST_CURSOR_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ConstraintListCursor:
    """A position in one Register result set, bound to the request that produced it.

    Keyset rather than offset: the position is the last returned row's sort key
    together with its Constraint identifier, which is what keeps a page stable
    when rows are written between requests. `sort_key` is the ordered tuple the
    active sort compares on, rendered as JSON scalars — a date or an instant
    arrives as its ISO text, a sequence length as an integer, an absent key as
    `None` so that the `NULLS LAST` order and the keyset predicate agree.

    Opaque, not signed and not encrypted. The point is that the token has no
    structure a caller is invited to construct by hand, and that it contains
    nothing private if one does take it apart: a request digest, a sort key, and
    an opaque identifier.
    """

    binding: str
    sort_key: tuple[str | int | None, ...]
    constraint_id: str

    def __post_init__(self) -> None:
        if len(self.binding) != _SHA256_HEX_LENGTH or any(
            character not in "0123456789abcdef" for character in self.binding
        ):
            raise ConstraintCursorError(
                "constraint_cursor_unreadable", "the cursor is not readable"
            )
        validate_identifier(self.constraint_id, IdKind.PROJECT_CONSTRAINT)
        for element in self.sort_key:
            if isinstance(element, bool) or not isinstance(element, (str, int, type(None))):
                raise ConstraintCursorError(
                    "constraint_cursor_unreadable", "the cursor is not readable"
                )

    def encode(self) -> str:
        """Render the cursor as one opaque, URL-safe token."""
        payload = json.dumps(
            {
                "b": self.binding,
                "i": self.constraint_id,
                "k": list(self.sort_key),
                "v": LIST_CURSOR_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")

    @classmethod
    def decode(cls, token: str) -> ConstraintListCursor:
        """Read a token, or raise `ConstraintCursorError`.

        Every failure — over-length, undecodable base64, non-JSON, the wrong
        keys, the wrong element types, a rejected identifier — is the one error
        with the one message, raised outside the handler so that the original,
        which may render the rejected value, is not left in `__context__`.
        """
        cursor: ConstraintListCursor | None = None
        if token and len(token) <= MAX_CURSOR_CHARACTERS:
            cursor = _decode_cursor(token)
        if cursor is None:
            raise ConstraintCursorError(
                "constraint_cursor_unreadable", "the cursor is not readable"
            )
        return cursor

    def is_bound_to(self, binding: str) -> bool:
        """Whether this cursor was issued for a request with `binding`."""
        return self.binding == binding


def _decode_cursor(token: str) -> ConstraintListCursor | None:
    """The decoding half of `ConstraintListCursor.decode`, which raises nothing."""
    padded = token + "=" * (-len(token) % 4)
    try:
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(decoded, dict):
        return None
    payload: dict[str, Any] = decoded
    if set(payload) != {"b", "i", "k", "v"} or payload["v"] != LIST_CURSOR_VERSION:
        return None
    binding, constraint_id, key = payload["b"], payload["i"], payload["k"]
    if not isinstance(binding, str) or not isinstance(constraint_id, str):
        return None
    if not isinstance(key, list):
        return None
    try:
        return ConstraintListCursor(
            binding=binding, sort_key=tuple(key), constraint_id=constraint_id
        )
    except (ConstraintCursorError, InvalidIdentifierError, TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class ConstraintListSpec:
    """One resolved list request, as the persistence adapter receives it.

    The service resolves the Project's calendar once and hands both dates down,
    so the SQL predicates that count and the Python derivations that render are
    generated from the same two values and cannot drift. `fetch_limit` is
    already `limit + 1`: the adapter applies it in SQL, and the extra row is
    what sets `is_truncated` rather than a slice of an unbounded result.
    """

    query: ConstraintListQuery
    as_of: datetime
    project_today: date
    due_soon_through: date
    fetch_limit: int
    after: ConstraintListCursor | None = None


# --- Pure derivations ---------------------------------------------------------


def party_refs_of(rows: tuple[ConstraintPartyRow, ...], role: str) -> tuple[PartyRef, ...]:
    """The WP01 party references for one role, in stored ordinal order.

    A PRINCIPAL party's stored labels are dropped rather than carried: a
    `PartyRef` of that kind is forbidden a label of its own, and the read plane
    is not the place to start disagreeing with the domain about it.
    """
    refs: list[PartyRef] = []
    for row in sorted(
        (row for row in rows if row.role == role), key=lambda row: (row.ordinal, row.constraint_id)
    ):
        if row.party_kind is PartyKind.PRINCIPAL:
            refs.append(PartyRef(kind=PartyKind.PRINCIPAL))
            continue
        label = row.display_label or row.original_label
        refs.append(PartyRef(kind=row.party_kind, entity_id=row.entity_id, label=label))
    return tuple(refs)


def legacy_missing_fields(record: PersistedConstraintRecord) -> tuple[ConstraintFieldKey, ...]:
    """Which `ConstraintFieldKey` values a legacy-incomplete record has no value for.

    Populated only for `LEGACY_INCOMPLETE` quality. A `NORMAL` record — a Draft
    part-way through being authored, say — is not "missing" anything: it is
    simply not finished, and reporting an author's own unfinished work as a data
    defect would make the diagnostic useless for the case it exists for.
    """
    if record.record_quality is not ConstraintRecordQuality.LEGACY_INCOMPLETE:
        return ()
    missing: list[ConstraintFieldKey] = []
    if record.project_id is None:
        missing.append(ConstraintFieldKey.PROJECT_ID)
    if record.category_id is None:
        missing.append(ConstraintFieldKey.CATEGORY_ID)
    if record.constraint_code is None:
        missing.append(ConstraintFieldKey.CONSTRAINT_CODE)
    if record.description is None or not record.description.strip():
        missing.append(ConstraintFieldKey.DESCRIPTION)
    if record.date_identified is None:
        missing.append(ConstraintFieldKey.DATE_IDENTIFIED)
    if record.due_date is None:
        missing.append(ConstraintFieldKey.DUE_DATE)
    if not record.bic:
        missing.append(ConstraintFieldKey.BIC)
    return tuple(missing)


def attention_for(
    record: PersistedConstraintRecord, *, has_open_conflict: bool
) -> ConstraintAttention:
    """Why this record needs a reader's attention, from persisted state only.

    Two reasons are derivable and both are facts already stored: the record's
    own quality, and whether a canonical sync conflict row is open against it.
    `DATA_QUALITY_EXCEPTION` is never emitted — no column expresses it and no
    accepted source defines its condition, so a read plane claiming it would be
    inventing a finding.
    """
    reasons: list[ConstraintAttentionReason] = []
    if record.record_quality is ConstraintRecordQuality.LEGACY_INCOMPLETE:
        reasons.append(ConstraintAttentionReason.LEGACY_INCOMPLETE)
    if has_open_conflict:
        reasons.append(ConstraintAttentionReason.OPEN_SYNC_CONFLICT)
    return ConstraintAttention(reasons=tuple(reasons), missing_fields=legacy_missing_fields(record))
