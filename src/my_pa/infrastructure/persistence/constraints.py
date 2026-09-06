"""The Constraint Management tables, behind `contracts.ports.ConstraintManagementRepository`.

PC-CM-IMP-WP02 wrote the mutation seam; PC-CM-IMP-WP03 added the read plane
beside it. Eleven of the fourteen tables §C declares now have a concrete caller
and are reached here: the eight WP02 wrote through — `constraint_project_settings`,
`constraint_categories`, `project_constraints`, `project_constraint_parties`,
`project_constraint_revisions`, `project_constraint_revision_parties`,
`project_constraint_history` and `constraint_category_history` — plus the three
WP03 reads and never writes: `project_constraint_relationships`,
`project_constraint_evidence_links` and, read-only, the sync trio
`constraint_sync_targets`, `constraint_sync_baselines` and
`constraint_sync_conflicts`. `constraint_sync_runs` still has no caller: a run
is behavior, and reading one would not tell a reader anything a baseline and an
open conflict do not already say. Nothing in this module writes to any sync
table, starts a run, takes a lease, or reads a workbook — that is WP11's, and a
read plane that did it would be doing sync rather than reporting it.

**The write path and the read path hydrate differently, on purpose.**
`_to_constraint` builds the strict WP01 aggregate and is what `get` and
`get_for_update` still use; `_to_read_record` is its sibling and builds
`PersistedConstraintRecord`, whose nullability matches the DDL. A legally
persisted `legacy_incomplete` import is therefore readable through every WP03
method while remaining unconstructible as a write aggregate. The asymmetry is
the design: the aggregate stays strict and the reader stays able to show what
is actually stored.

**Every read is bounded in SQL.** No page is a slice of a fetched list, no page
of parties is read a row at a time, and no read takes a row lock: `get_for_update`
and `get_category_for_update` remain the only two statements in this module that
compose `with_for_update()`.

Two things separate this module from `commitment_management.py`, which it
otherwise mirrors row for row:

**The partition is reached through the guard, never written by hand.** Every
statement composes `_mine` (over `partition_criterion`) or `_bound` (over
`principal_bound_values`), the one-line wrappers `goodnotes_pull.py` established.
`commitment_management.py` spells `commitments.c.principal_id == principal_id`
at each call site and is quarantined for it; that shape is not copied here.

**The Principal is a parameter, never a field of the payload.** Every write
takes `principal_id` from the application boundary and stamps it through
`principal_bound_values`, which *refuses* values that already name a partition
column. A `ProjectConstraint` built with another Principal's identifier
therefore cannot be written into that Principal's partition by this module: the
row is stamped with the authenticated caller, and the `(principal_id, ...)`
composite foreign keys refuse it against a parent that is not theirs.

Known limitation, recorded rather than worked around: a stored
`legacy_incomplete` row raises `ConstraintInvariantError` out of the WP01
constructor when `get`/`get_for_update` hydrates it, because that constructor
cannot build the shape the narrow legacy CHECK relaxation admits. Nothing in
WP02 writes such a row. The hydration path for it belongs to the legacy import
work package (WP13) along with the importer that creates one.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime, timedelta
from types import TracebackType
from typing import Any, Final

from sqlalchemy import (
    ColumnElement,
    Date,
    Engine,
    Integer,
    Table,
    and_,
    asc,
    case,
    delete,
    desc,
    func,
    insert,
    literal,
    or_,
    select,
    type_coerce,
    update,
)
from sqlalchemy.engine import Connection, Row

from my_pa.contracts.ports import (
    ConstraintManagementRepository,
    ConstraintManagementUnitOfWork,
)
from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.project_controls.category import ConstraintCategory, ConstraintCategoryState
from my_pa.domain.project_controls.constraint import (
    ACTIVE_CONSTRAINT_LIFECYCLE_STATES,
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintRecordQuality,
    ProjectConstraint,
)
from my_pa.domain.project_controls.history import (
    ConstraintCategoryHistoryEntry,
    ConstraintHistoryEntry,
    ConstraintMutationActor,
    ConstraintMutationOperation,
    ConstraintMutationOutcome,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.read_models import (
    PRINCIPAL_PARTY_REF,
    RECENT_WINDOW_DAYS,
    UNRESOLVED_PARTY_REF,
    ConstraintCategoryRow,
    ConstraintEvidenceLinkRow,
    ConstraintHistoryPosition,
    ConstraintHistoryRow,
    ConstraintListCursor,
    ConstraintListScope,
    ConstraintListSpec,
    ConstraintOverviewFacts,
    ConstraintPartyRow,
    ConstraintRecentFilter,
    ConstraintRelationshipRow,
    ConstraintSort,
    ConstraintSyncFacts,
    ConstraintSyncStateView,
    PersistedConstraintRecord,
    RelationshipDirection,
    SortDirection,
)
from my_pa.domain.project_controls.revision import ConstraintRevision
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    matching_partition_criterion,
    partition_criterion,
    principal_bound_values,
    principal_scoped,
)
from my_pa.infrastructure.persistence.tables import (
    constraint_categories,
    constraint_category_history,
    constraint_project_settings,
    constraint_sync_baselines,
    constraint_sync_conflicts,
    constraint_sync_targets,
    entities,
    project_constraint_evidence_links,
    project_constraint_history,
    project_constraint_parties,
    project_constraint_relationships,
    project_constraint_revision_parties,
    project_constraint_revisions,
    project_constraints,
)

__all__ = ["SqlAlchemyConstraintManagementUnitOfWork", "SqlConstraintManagementRepository"]

#: The two stored party roles. A frozen literal pair rather than a live enum,
#: exactly as the stored CHECK spells it: this is a column vocabulary, and the
#: domain names the two collections as fields rather than as an enum.
_BIC_ROLE: Final = "bic"
_RESPONSIBLE_ROLE: Final = "responsible"


def _mine(table: Table, principal_id: str) -> ColumnElement[bool]:
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Table, principal_id: str, values: dict[str, object]) -> dict[str, object]:
    return principal_bound_values(values, table, capture_context(principal_id))


def _party_assignment_id(constraint_id: str, role: str, ordinal: int) -> str:
    """A stable `cpty_` identity for one assignment slot.

    Derived rather than random so that replacing a Constraint's parties leaves
    the same slot carrying the same identity across writes, which is what makes
    a row-addressed assignment addressable at all.
    """
    suffix = hashlib.sha256(
        f"constraint_party\x1f{constraint_id}\x1f{role}\x1f{ordinal}".encode()
    ).hexdigest()[:24]
    return make_identifier(IdKind.CONSTRAINT_PARTY_ASSIGNMENT, suffix)


def _party_columns(party: PartyRef) -> dict[str, object]:
    """The stored shape of one party reference, for either party table."""
    return {
        "party_kind": party.kind.value,
        "entity_id": party.entity_id,
        "display_label": party.label,
        "original_label": party.label,
        "resolved_at": None,
    }


def _to_party(row: Row[Any]) -> PartyRef:
    mapping = row._mapping
    return PartyRef(
        kind=PartyKind(mapping["party_kind"]),
        entity_id=mapping["entity_id"],
        label=mapping["display_label"],
    )


def _split_parties(rows: list[Row[Any]]) -> tuple[tuple[PartyRef, ...], tuple[PartyRef, ...]]:
    """The two ordered collections, reconstructed from `(role, ordinal)` order."""
    bic = tuple(_to_party(row) for row in rows if row._mapping["role"] == _BIC_ROLE)
    responsible = tuple(_to_party(row) for row in rows if row._mapping["role"] == _RESPONSIBLE_ROLE)
    return bic, responsible


def _to_settings(row: Row[Any]) -> ConstraintProjectSettings:
    mapping = row._mapping
    return ConstraintProjectSettings(
        principal_id=mapping["principal_id"],
        project_id=mapping["project_id"],
        timezone_name=mapping["timezone_name"],
        version=mapping["version"],
        created_at=mapping["created_at"],
        updated_at=mapping["updated_at"],
    )


def _to_category(row: Row[Any]) -> ConstraintCategory:
    mapping = row._mapping
    return ConstraintCategory(
        category_id=mapping["category_id"],
        principal_id=mapping["principal_id"],
        project_id=mapping["project_id"],
        prefix=mapping["prefix"],
        title=mapping["title"],
        state=ConstraintCategoryState(mapping["state"]),
        created_at=mapping["created_at"],
        updated_at=mapping["updated_at"],
        description=mapping["description"],
        display_order=mapping["display_order"],
        prefix_locked_at=mapping["prefix_locked_at"],
    )


def _to_constraint(
    row: Row[Any], bic: tuple[PartyRef, ...], responsible: tuple[PartyRef, ...]
) -> ProjectConstraint:
    mapping = row._mapping
    return ProjectConstraint(
        constraint_id=mapping["constraint_id"],
        principal_id=mapping["principal_id"],
        lifecycle_state=ConstraintLifecycleState(mapping["lifecycle_state"]),
        origin=ConstraintOrigin(mapping["origin"]),
        created_at=mapping["created_at"],
        updated_at=mapping["updated_at"],
        version=mapping["version"],
        project_id=mapping["project_id"],
        category_id=mapping["category_id"],
        constraint_code=mapping["constraint_code"],
        description=mapping["description"],
        date_identified=mapping["date_identified"],
        due_date=mapping["due_date"],
        reference=mapping["reference"],
        current_update=mapping["current_update"],
        bic=bic,
        responsible=responsible,
        completion_date=mapping["completion_date"],
        closure_commentary=mapping["closure_commentary"],
        voided_date=mapping["voided_date"],
        void_reason=mapping["void_reason"],
        record_quality=ConstraintRecordQuality(mapping["record_quality"]),
        published_at=mapping["published_at"],
    )


def _to_revision(
    row: Row[Any], bic: tuple[PartyRef, ...], responsible: tuple[PartyRef, ...]
) -> ConstraintRevision:
    mapping = row._mapping
    return ConstraintRevision(
        revision_id=mapping["revision_id"],
        principal_id=mapping["principal_id"],
        constraint_id=mapping["constraint_id"],
        history_id=mapping["history_id"],
        version=mapping["version"],
        lifecycle_state=ConstraintLifecycleState(mapping["lifecycle_state"]),
        origin=ConstraintOrigin(mapping["origin"]),
        record_quality=ConstraintRecordQuality(mapping["record_quality"]),
        recorded_at=mapping["recorded_at"],
        project_id=mapping["project_id"],
        category_id=mapping["category_id"],
        constraint_code=mapping["constraint_code"],
        description=mapping["description"],
        date_identified=mapping["date_identified"],
        due_date=mapping["due_date"],
        reference=mapping["reference"],
        current_update=mapping["current_update"],
        completion_date=mapping["completion_date"],
        closure_commentary=mapping["closure_commentary"],
        voided_date=mapping["voided_date"],
        void_reason=mapping["void_reason"],
        published_at=mapping["published_at"],
        bic=bic,
        responsible=responsible,
    )


def _to_history(row: Row[Any]) -> ConstraintHistoryEntry:
    mapping = row._mapping
    return ConstraintHistoryEntry(
        history_id=mapping["history_id"],
        principal_id=mapping["principal_id"],
        constraint_id=mapping["constraint_id"],
        operation=ConstraintMutationOperation(mapping["operation"]),
        actor=ConstraintMutationActor(mapping["actor"]),
        outcome=ConstraintMutationOutcome(mapping["outcome"]),
        before_version=mapping["before_version"],
        after_version=mapping["after_version"],
        occurred_at=mapping["occurred_at"],
        recorded_at=mapping["recorded_at"],
        project_id=mapping["project_id"],
        revision_id=mapping["revision_id"],
        idempotency_key=mapping["idempotency_key"],
        request_digest=mapping["request_digest"],
        client_context=mapping["client_context"],
        correlation_id=mapping["correlation_id"],
        safe_failure_reason=mapping["safe_failure_reason"],
    )


# --- The read plane (PC-CM-IMP-WP03) -----------------------------------------
#
# Everything from here to the repository class builds one of the ten read
# statements. Three rules hold throughout and are what the tests check rather
# than describe: the Principal partition is reached through `_mine` (or
# `matching_partition_criterion` on the far side of a join), the bound on how
# much work a statement does is expressed in the statement, and no expression
# here casts a Constraint Code to a number.


#: The reference Monday every business-day count is measured from. 1900-01-01
#: was a Monday and precedes any Project date this plane can be shown, which is
#: what turns "weekdays between two dates" into a closed-form subtraction rather
#: than a loop or a generated series: `_weekdays_through(x)` counts weekdays from
#: this Monday through `x` inclusive, and a range's count is one minus the other.
_WEEKDAY_EPOCH: Final = date(1900, 1, 1)

#: Monday..Friday are ISO days 1..5, so a weekday is `isodow < 6`.
_FIRST_WEEKEND_ISODOW: Final = 6

#: The leading component of every sort key: `0` when the row has the key, `1`
#: when it does not. `NULLS LAST` in both directions is then a value the keyset
#: predicate compares rather than a rule it has to remember separately, and it is
#: the same discriminator `application.constraints` writes into the cursor. The
#: two must agree exactly or a continuation would skip or repeat rows.
_KEY_PRESENT: Final = 0
_KEY_ABSENT: Final = 1

#: What an absent sort key stands in as. Only ever compared against another
#: absent key, because the discriminator above separates the two groups before
#: any of these is reached, so a collision with real data is not expressible.
_ABSENT_TEXT: Final = ""
_ABSENT_NUMBER: Final = 0
_ABSENT_DATE: Final = date(1, 1, 1)
_ABSENT_INSTANT: Final = datetime(1, 1, 1, tzinfo=UTC)

#: The one conflict state that counts as open.
_OPEN_CONFLICT: Final = "open"

_ACTIVE_STATE_VALUES: Final[tuple[str, ...]] = tuple(
    sorted(state.value for state in ACTIVE_CONSTRAINT_LIFECYCLE_STATES)
)
_TERMINAL_STATE_VALUES: Final[tuple[str, ...]] = (
    ConstraintLifecycleState.CLOSED.value,
    ConstraintLifecycleState.VOID.value,
)


def _to_read_record(
    row: Row[Any],
    bic: tuple[PartyRef, ...] = (),
    responsible: tuple[PartyRef, ...] = (),
) -> PersistedConstraintRecord:
    """One `project_constraints` row as a read record, with nothing invented.

    The sibling of `_to_constraint`, and deliberately not a replacement for it.
    Where the aggregate constructor enforces the write invariants — a closed
    record has a completion date, a published one has a code — this hydrator
    enforces none of them and copies the columns across as they are stored. That
    is the whole legacy strategy: a row the four `legacy_incomplete` CHECK
    relaxations admit is readable here, and `get` still refuses to build an
    aggregate out of it.

    `bic` and `responsible` default to empty because the list read does not
    supply them: a page's parties are read once in bulk by `parties_for` rather
    than once per row. The single-record read joins them and passes them in.
    """
    mapping = row._mapping
    return PersistedConstraintRecord(
        constraint_id=mapping["constraint_id"],
        principal_id=mapping["principal_id"],
        lifecycle_state=ConstraintLifecycleState(mapping["lifecycle_state"]),
        record_quality=ConstraintRecordQuality(mapping["record_quality"]),
        origin=ConstraintOrigin(mapping["origin"]),
        version=mapping["version"],
        created_at=mapping["created_at"],
        updated_at=mapping["updated_at"],
        project_id=mapping["project_id"],
        category_id=mapping["category_id"],
        constraint_code=mapping["constraint_code"],
        description=mapping["description"],
        date_identified=mapping["date_identified"],
        due_date=mapping["due_date"],
        reference=mapping["reference"],
        current_update=mapping["current_update"],
        completion_date=mapping["completion_date"],
        closure_commentary=mapping["closure_commentary"],
        voided_date=mapping["voided_date"],
        void_reason=mapping["void_reason"],
        published_at=mapping["published_at"],
        bic=bic,
        responsible=responsible,
    )


def _to_category_row(row: Row[Any]) -> ConstraintCategoryRow:
    """One `constraint_categories` row, allocator counters included.

    The counters travel with it because a Register's Category filter list is
    also what a later allocator reads, and a projection that dropped them would
    make the second caller issue a second statement for the same row.
    """
    mapping = row._mapping
    return ConstraintCategoryRow(
        category_id=mapping["category_id"],
        project_id=mapping["project_id"],
        prefix=mapping["prefix"],
        title=mapping["title"],
        description=mapping["description"],
        display_order=mapping["display_order"],
        state=ConstraintCategoryState(mapping["state"]),
        next_sequence=mapping["next_sequence"],
        issued_count=mapping["issued_count"],
        version=mapping["version"],
        prefix_locked_at=mapping["prefix_locked_at"],
    )


def _to_party_row(row: Row[Any]) -> ConstraintPartyRow:
    """One `project_constraint_parties` row, in its stored role and ordinal."""
    mapping = row._mapping
    return ConstraintPartyRow(
        constraint_id=mapping["constraint_id"],
        role=mapping["role"],
        ordinal=mapping["ordinal"],
        party_kind=PartyKind(mapping["party_kind"]),
        entity_id=mapping["entity_id"],
        display_label=mapping["display_label"],
        original_label=mapping["original_label"],
    )


def _sequence_segment() -> ColumnElement[str]:
    """The Constraint Code's sequence segment, as text and only as text.

    `7.03` is an identity, not a number: a numeric cast would make `7.30` of
    `7.3` and would order `2.10` before `2.09`. Reversing, taking the first
    segment and reversing back is `str.rpartition('.')[2]` in SQL — the same
    thing `application.constraints` does when it writes the cursor anchor — and
    it involves no cast at any point. A code with no `.` yields itself, exactly
    as `rpartition` does.
    """
    code = project_constraints.c.constraint_code
    return func.reverse(func.split_part(func.reverse(code), ".", 1))


def _weekdays_through(value: ColumnElement[Any]) -> ColumnElement[int]:
    """Weekdays from the reference Monday through `value`, inclusive.

    Whole weeks contribute five each and the remainder contributes at most five,
    because the count starts on a Monday. This is the halving step that makes
    `_business_days_elapsed` a pair of subtractions instead of a per-row walk
    over every day between two dates.
    """
    days = (value - literal(_WEEKDAY_EPOCH, Date)).self_group()
    total = type_coerce(days + literal(1, Integer), Integer).self_group()
    whole_weeks = type_coerce(total.op("/")(literal(7, Integer)), Integer).self_group()
    remainder = type_coerce(total.op("%")(literal(7, Integer)), Integer).self_group()
    counted = whole_weeks * literal(5, Integer) + func.least(remainder, literal(5, Integer))
    # Grouped, because this value is subtracted from another one: without the
    # parentheses SQL precedence would apply the minus to the first term only.
    return counted.self_group()


def _is_weekday(value: ColumnElement[Any]) -> ColumnElement[bool]:
    """Monday through Friday, in SQL. No holiday calendar, exactly as WP01."""
    return func.extract("isodow", value) < literal(_FIRST_WEEKEND_ISODOW, Integer)


def _business_days_elapsed(
    start: ColumnElement[Any], end: ColumnElement[Any]
) -> ColumnElement[int]:
    """`business_days_elapsed(start, end)` as one expression: Excel `NETWORKDAYS`.

    Weekdays in `[start, end]` are the weekdays through `end` less those through
    `start`, plus `start` itself when it is a weekday — the inclusive lower
    bound, restored once rather than by shifting a date. A reversed range is the
    negated count of the range the other way round, which is what WP01 returns
    and therefore what an overview computed here has to return too.
    """
    forward = (
        _weekdays_through(end)
        - _weekdays_through(start)
        + case((_is_weekday(start), literal(1, Integer)), else_=literal(0, Integer))
    ).self_group()
    backward = (
        _weekdays_through(start)
        - _weekdays_through(end)
        + case((_is_weekday(end), literal(1, Integer)), else_=literal(0, Integer))
    ).self_group()
    return case((end >= start, forward), else_=-backward)


def _contains(term: str) -> str:
    """`term` as a LIKE pattern matching it literally, anywhere.

    The convention `entity.py:505` established, for the same reason: `%`, `_`
    and `\\` are pattern syntax, so a search for one of them would otherwise
    match more than the reader asked for — a bare `%` returning the whole
    Register. Escaped against a declared ESCAPE rather than stripped, because a
    Constraint reference may legitimately contain any of the three.
    """
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _party_exists(principal_id: str, role: str, refs: frozenset[str]) -> ColumnElement[bool]:
    """`EXISTS` over one role's party rows, OR-ed across the requested references.

    A subquery rather than a join, because a Constraint may be waiting on
    several parties and joining would return the row once per match — turning a
    filter into a multiplier and a page limit into a lie. The references are the
    closed §D vocabulary: the `principal` and `unresolved` tokens select a kind,
    and anything else is an Entity identifier compared as an identifier. A
    syntactically valid identifier belonging to another Principal simply matches
    nothing, because the subquery is `_mine`-scoped.
    """
    clauses: list[ColumnElement[bool]] = []
    if PRINCIPAL_PARTY_REF in refs:
        clauses.append(project_constraint_parties.c.party_kind == PartyKind.PRINCIPAL.value)
    if UNRESOLVED_PARTY_REF in refs:
        clauses.append(project_constraint_parties.c.party_kind == PartyKind.UNRESOLVED.value)
    entity_ids = sorted(
        ref for ref in refs if ref not in (PRINCIPAL_PARTY_REF, UNRESOLVED_PARTY_REF)
    )
    if entity_ids:
        clauses.append(project_constraint_parties.c.entity_id.in_(entity_ids))
    return (
        select(literal(1, Integer))
        .where(
            _mine(project_constraint_parties, principal_id),
            project_constraint_parties.c.constraint_id == project_constraints.c.constraint_id,
            project_constraint_parties.c.role == role,
            or_(*clauses),
        )
        .exists()
    )


def _principal_bic_exists(principal_id: str) -> ColumnElement[bool]:
    """Whether this Constraint's BIC explicitly names the Principal.

    The SQL form of `constraint.in_my_court` with an empty bound-entity set: a
    `PRINCIPAL`-kind BIC row and nothing else. No label, name or address is
    compared anywhere in it, so a party wording that happens to read like the
    Principal cannot establish In My Court.
    """
    return (
        select(literal(1, Integer))
        .where(
            _mine(project_constraint_parties, principal_id),
            project_constraint_parties.c.constraint_id == project_constraints.c.constraint_id,
            project_constraint_parties.c.role == _BIC_ROLE,
            project_constraint_parties.c.party_kind == PartyKind.PRINCIPAL.value,
        )
        .exists()
    )


def _open_conflict_exists(principal_id: str) -> ColumnElement[bool]:
    """Whether a canonical sync conflict is open against this Constraint."""
    return (
        select(literal(1, Integer))
        .where(
            _mine(constraint_sync_conflicts, principal_id),
            constraint_sync_conflicts.c.constraint_id == project_constraints.c.constraint_id,
            constraint_sync_conflicts.c.state == _OPEN_CONFLICT,
        )
        .exists()
    )


def _sync_state_expression(principal_id: str, project_id: str) -> ColumnElement[str]:
    """The one sync state persisted rows prove, as a column the filter can compare.

    The same order of reasoning `application.constraints._sync_state` applies,
    so a `sync_states` filter and a rendered row can never disagree: an open
    conflict outranks everything, then a missing target or missing baseline is
    never-synced, then the baseline version either lags the Constraint's or
    matches it. The six frontend names that need a connector, a workbook or a
    live run are not producible by this expression at all.
    """
    has_target = (
        select(literal(1, Integer))
        .where(
            _mine(constraint_sync_targets, principal_id),
            constraint_sync_targets.c.project_id == project_id,
        )
        .exists()
    )
    baseline = (
        select(func.max(constraint_sync_baselines.c.baseline_constraint_version))
        .where(
            _mine(constraint_sync_baselines, principal_id),
            constraint_sync_baselines.c.constraint_id == project_constraints.c.constraint_id,
        )
        .scalar_subquery()
    )
    return case(
        (_open_conflict_exists(principal_id), literal(ConstraintSyncStateView.CONFLICT.value)),
        (
            or_(~has_target, baseline.is_(None)),
            literal(ConstraintSyncStateView.NEVER_SYNCED.value),
        ),
        (
            project_constraints.c.version > baseline,
            literal(ConstraintSyncStateView.DB_EXPORT_PENDING.value),
        ),
        else_=literal(ConstraintSyncStateView.IN_SYNC.value),
    )


def _active() -> ColumnElement[bool]:
    """The four active lifecycle states, as one predicate."""
    return project_constraints.c.lifecycle_state.in_(_ACTIVE_STATE_VALUES)


def _scope_predicate(scope: ConstraintListScope) -> ColumnElement[bool] | None:
    """The lifecycle predicate one Register scope means, or `None` for `ALL`.

    `ALL` returns no predicate rather than a tautology: the Principal and Project
    predicates and the page limit still bound it, and an always-true clause in
    the statement would only invite a reader to think one of them was optional.
    """
    if scope is ConstraintListScope.OPEN:
        return _active()
    if scope is ConstraintListScope.CLOSED:
        return project_constraints.c.lifecycle_state.in_(_TERMINAL_STATE_VALUES)
    if scope is ConstraintListScope.DRAFT:
        return project_constraints.c.lifecycle_state == ConstraintLifecycleState.DRAFT.value
    return None


def _search_predicate(term: str) -> ColumnElement[bool]:
    """The four approved columns, OR-ed, as a bounded substring match.

    `constraint_code`, `description`, `reference` and `current_update` and
    nothing else — there is no `to_tsvector` index on any Constraint column, so
    `ILIKE` against a declared ESCAPE is the mechanism, and this predicate is
    always AND-ed with the Principal and Project predicates and a SQL `LIMIT`
    rather than standing on its own.
    """
    pattern = _contains(term)
    return or_(
        project_constraints.c.constraint_code.ilike(pattern, escape="\\"),
        project_constraints.c.description.ilike(pattern, escape="\\"),
        project_constraints.c.reference.ilike(pattern, escape="\\"),
        project_constraints.c.current_update.ilike(pattern, escape="\\"),
    )


def _list_predicates(principal_id: str, spec: ConstraintListSpec) -> list[ColumnElement[bool]]:
    """Every filter one Register request means, as `AND`-ed clauses.

    OR within a family, AND across families, and AND with the scope, the quick
    filters and the search — the §F.3 composition, expressed by the shape of the
    list rather than by a comment. The quick filters use the same derivations the
    overview counts with, which is what makes list/overview coherence a property
    of one definition rather than of two that happen to agree today.
    """
    query = spec.query
    today = spec.project_today
    predicates: list[ColumnElement[bool]] = []
    scope = _scope_predicate(query.scope)
    if scope is not None:
        predicates.append(scope)
    if query.statuses:
        predicates.append(
            project_constraints.c.lifecycle_state.in_(
                sorted(status.value for status in query.statuses)
            )
        )
    if query.category_ids:
        predicates.append(project_constraints.c.category_id.in_(sorted(query.category_ids)))
    if query.record_qualities:
        predicates.append(
            project_constraints.c.record_quality.in_(
                sorted(quality.value for quality in query.record_qualities)
            )
        )
    if query.overdue:
        predicates.append(
            and_(
                _active(),
                project_constraints.c.due_date.is_not(None),
                project_constraints.c.due_date < today,
            )
        )
    if query.due_soon:
        predicates.append(
            and_(
                _active(),
                project_constraints.c.due_date.is_not(None),
                project_constraints.c.due_date >= today,
                project_constraints.c.due_date <= spec.due_soon_through,
            )
        )
    if query.my_court:
        predicates.append(and_(_active(), _principal_bic_exists(principal_id)))
    if query.needs_attention:
        predicates.append(
            or_(
                project_constraints.c.record_quality
                == ConstraintRecordQuality.LEGACY_INCOMPLETE.value,
                _open_conflict_exists(principal_id),
            )
        )
    if query.bic_party_refs:
        predicates.append(_party_exists(principal_id, _BIC_ROLE, query.bic_party_refs))
    if query.responsible_party_refs:
        predicates.append(
            _party_exists(principal_id, _RESPONSIBLE_ROLE, query.responsible_party_refs)
        )
    if query.recent is not None:
        predicates.append(_recent_predicate(spec))
    if query.search_text is not None:
        predicates.append(_search_predicate(query.search_text))
    return predicates


def _recent_predicate(spec: ConstraintListSpec) -> ColumnElement[bool]:
    """One of the two "recently" windows, each measured on its own clock.

    `RECENTLY_CHANGED` compares a `timestamptz` against the request's UTC
    instant, so no local-date conversion enters it. `RECENTLY_CLOSED` compares a
    Project date against the trailing seven Project dates, because a completion
    date is a date on the Project's calendar and nothing else. `VOID` is excluded
    by the `closed` predicate itself rather than by a second clause.
    """
    if spec.query.recent is ConstraintRecentFilter.RECENTLY_CHANGED:
        return project_constraints.c.updated_at >= spec.as_of - timedelta(days=RECENT_WINDOW_DAYS)
    return and_(
        project_constraints.c.lifecycle_state == ConstraintLifecycleState.CLOSED.value,
        project_constraints.c.completion_date.is_not(None),
        project_constraints.c.completion_date
        >= spec.project_today - timedelta(days=RECENT_WINDOW_DAYS - 1),
        project_constraints.c.completion_date <= spec.project_today,
    )


def _discriminator(present: ColumnElement[bool]) -> ColumnElement[int]:
    """`0` when the row has the sort key and `1` when it does not."""
    return case((present, literal(_KEY_PRESENT, Integer)), else_=literal(_KEY_ABSENT, Integer))


def _order_components(
    spec: ConstraintListSpec,
) -> list[tuple[ColumnElement[Any], bool]]:
    """The active sort's full ordering key, component by component, with directions.

    Two properties matter and both are checked rather than described. **The
    discriminator always ascends**, so a row missing the sort key is last in both
    directions and never leads the Register. **The tuple is the whole key**: the
    Code sort orders by `(display_order, prefix, length(sequence), sequence)`
    and the cursor anchors on all four, because two Categories can allocate the
    same sequence numbers under different prefixes and a narrower anchor would
    be ambiguous exactly at a Category boundary — the place a continuation would
    then skip or repeat rows.

    `DAYS_ELAPSED` is a monotonically decreasing function of `date_identified`
    for a fixed Project date, so it orders on that column with the direction
    inverted. Nothing is computed in Python and then sliced.
    """
    query = spec.query
    ascending = query.direction is SortDirection.ASC
    if query.sort is ConstraintSort.DAYS_ELAPSED:
        ascending = not ascending
    components: list[tuple[ColumnElement[Any], bool]] = []
    if query.sort is ConstraintSort.CODE:
        sequence = _sequence_segment()
        present = and_(
            project_constraints.c.constraint_code.is_not(None),
            constraint_categories.c.category_id.is_not(None),
        )
        components.append((_discriminator(present), True))
        components.append(
            (
                func.coalesce(
                    constraint_categories.c.display_order, literal(_ABSENT_NUMBER, Integer)
                ),
                ascending,
            )
        )
        components.append((func.coalesce(constraint_categories.c.prefix, _ABSENT_TEXT), ascending))
        components.append(
            (
                func.coalesce(func.length(sequence), literal(_ABSENT_NUMBER, Integer)),
                ascending,
            )
        )
        components.append((func.coalesce(sequence, _ABSENT_TEXT), ascending))
    elif query.sort is ConstraintSort.UPDATED_AT:
        column = project_constraints.c.updated_at
        components.append((_discriminator(column.is_not(None)), True))
        components.append((func.coalesce(column, _ABSENT_INSTANT), ascending))
    else:
        column = (
            project_constraints.c.due_date
            if query.sort is ConstraintSort.DUE_DATE
            else project_constraints.c.date_identified
        )
        components.append((_discriminator(column.is_not(None)), True))
        components.append((func.coalesce(column, _ABSENT_DATE), ascending))
    components.append((project_constraints.c.constraint_id, ascending))
    return components


def _anchor_values(spec: ConstraintListSpec, cursor: ConstraintListCursor) -> list[Any]:
    """The cursor's position as values comparable against `_order_components`.

    Each absent component becomes the same stand-in the ordering coalesces to,
    so the comparison is total; the discriminator ahead of it has already
    decided which group the row is in, so a stand-in is only ever compared with
    another stand-in. The identifier tie-breaker closes the tuple, which is what
    makes every sort a total order and paging unable to duplicate or skip a
    stable row.
    """
    sort = spec.query.sort
    key = cursor.sort_key
    values: list[Any] = [_KEY_ABSENT if key and key[0] == _KEY_ABSENT else _KEY_PRESENT]
    if sort is ConstraintSort.CODE:
        values.append(_number_at(key, 1))
        values.append(_text_at(key, 2))
        values.append(_number_at(key, 3))
        values.append(_text_at(key, 4))
    elif sort is ConstraintSort.UPDATED_AT:
        rendered = _text_at(key, 1)
        values.append(_ABSENT_INSTANT if not rendered else datetime.fromisoformat(rendered))
    else:
        rendered = _text_at(key, 1)
        values.append(_ABSENT_DATE if not rendered else date.fromisoformat(rendered))
    values.append(cursor.constraint_id)
    return values


def _number_at(key: tuple[str | int | None, ...], index: int) -> int:
    """One integer component of a cursor anchor, or the absent stand-in."""
    value = key[index] if index < len(key) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else _ABSENT_NUMBER


def _text_at(key: tuple[str | int | None, ...], index: int) -> str:
    """One text component of a cursor anchor, or the absent stand-in."""
    value = key[index] if index < len(key) else None
    return value if isinstance(value, str) else _ABSENT_TEXT


def _after_predicate(
    components: Sequence[tuple[ColumnElement[Any], bool]], values: Sequence[Any]
) -> ColumnElement[bool]:
    """ "Strictly after this position", in the same order the statement sorts by.

    The lexicographic comparison written out: the first component past the
    anchor, or the first equal and the second past it, and so on. Written by
    hand rather than as a row-value comparison because the components do not all
    run the same way — the null discriminator always ascends while the rest
    follow the requested direction — and a row-value comparison cannot express
    a mixed order.
    """
    clauses: list[ColumnElement[bool]] = []
    for index, ((expression, ascending), value) in enumerate(zip(components, values, strict=True)):
        strict = expression > value if ascending else expression < value
        equals = [
            earlier == earlier_value
            for (earlier, _), earlier_value in zip(components[:index], values[:index], strict=True)
        ]
        clauses.append(and_(*equals, strict) if equals else strict)
    return or_(*clauses)


class SqlConstraintManagementRepository(ConstraintManagementRepository):
    """`ConstraintManagementRepository`, over a plain SQLAlchemy Core `Connection`.

    Takes the connection rather than opening one, exactly as
    `SqlCommitmentManagementRepository` does: the caller owns the transaction
    and this class only issues statements on it. Nothing here commits.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    # --- Project settings ------------------------------------------------

    def get_project_settings(
        self, principal_id: str, project_id: str
    ) -> ConstraintProjectSettings | None:
        row = self._connection.execute(
            principal_scoped(
                select(*constraint_project_settings.c),
                constraint_project_settings,
                capture_context(principal_id),
            ).where(constraint_project_settings.c.project_id == project_id)
        ).one_or_none()
        return None if row is None else _to_settings(row)

    def insert_project_settings(
        self, principal_id: str, settings: ConstraintProjectSettings
    ) -> None:
        self._connection.execute(
            insert(constraint_project_settings).values(
                _bound(
                    constraint_project_settings,
                    principal_id,
                    {
                        "project_id": settings.project_id,
                        "timezone_name": settings.timezone_name,
                        "version": settings.version,
                        "created_at": settings.created_at,
                        "updated_at": settings.updated_at,
                    },
                )
            )
        )

    def update_project_settings(
        self, principal_id: str, settings: ConstraintProjectSettings
    ) -> None:
        self._connection.execute(
            update(constraint_project_settings)
            .where(
                _mine(constraint_project_settings, principal_id),
                constraint_project_settings.c.project_id == settings.project_id,
            )
            .values(
                timezone_name=settings.timezone_name,
                version=settings.version,
                updated_at=settings.updated_at,
            )
        )

    # --- Categories ------------------------------------------------------

    def get_category(self, principal_id: str, category_id: str) -> ConstraintCategory | None:
        row = self._connection.execute(
            principal_scoped(
                select(*constraint_categories.c),
                constraint_categories,
                capture_context(principal_id),
            ).where(constraint_categories.c.category_id == category_id)
        ).one_or_none()
        return None if row is None else _to_category(row)

    def get_category_for_update(
        self, principal_id: str, category_id: str
    ) -> ConstraintCategory | None:
        row = self._connection.execute(
            principal_scoped(
                select(*constraint_categories.c),
                constraint_categories,
                capture_context(principal_id),
            )
            .where(constraint_categories.c.category_id == category_id)
            .with_for_update()
        ).one_or_none()
        return None if row is None else _to_category(row)

    def insert_category(
        self,
        principal_id: str,
        category: ConstraintCategory,
        *,
        next_sequence: int = 1,
        issued_count: int = 0,
        version: int = 1,
    ) -> None:
        self._connection.execute(
            insert(constraint_categories).values(
                _bound(
                    constraint_categories,
                    principal_id,
                    {
                        "category_id": category.category_id,
                        "project_id": category.project_id,
                        "prefix": category.prefix,
                        "title": category.title,
                        "description": category.description,
                        "display_order": category.display_order,
                        "state": category.state.value,
                        "next_sequence": next_sequence,
                        "issued_count": issued_count,
                        "prefix_locked_at": category.prefix_locked_at,
                        "version": version,
                        "created_at": category.created_at,
                        "updated_at": category.updated_at,
                        "archived_at": _archived_at(category),
                    },
                )
            )
        )

    def update_category(
        self,
        principal_id: str,
        category: ConstraintCategory,
        *,
        next_sequence: int,
        issued_count: int,
        version: int,
    ) -> None:
        self._connection.execute(
            update(constraint_categories)
            .where(
                _mine(constraint_categories, principal_id),
                constraint_categories.c.category_id == category.category_id,
            )
            .values(
                prefix=category.prefix,
                title=category.title,
                description=category.description,
                display_order=category.display_order,
                state=category.state.value,
                next_sequence=next_sequence,
                issued_count=issued_count,
                prefix_locked_at=category.prefix_locked_at,
                version=version,
                updated_at=category.updated_at,
                archived_at=_archived_at(category),
            )
        )

    # --- Constraints -----------------------------------------------------

    def get(self, principal_id: str, constraint_id: str) -> ProjectConstraint | None:
        row = self._connection.execute(
            principal_scoped(
                select(*project_constraints.c),
                project_constraints,
                capture_context(principal_id),
            ).where(project_constraints.c.constraint_id == constraint_id)
        ).one_or_none()
        if row is None:
            return None
        bic, responsible = self._parties(principal_id, constraint_id)
        return _to_constraint(row, bic, responsible)

    def get_for_update(self, principal_id: str, constraint_id: str) -> ProjectConstraint | None:
        row = self._connection.execute(
            principal_scoped(
                select(*project_constraints.c),
                project_constraints,
                capture_context(principal_id),
            )
            .where(project_constraints.c.constraint_id == constraint_id)
            .with_for_update()
        ).one_or_none()
        if row is None:
            return None
        bic, responsible = self._parties(principal_id, constraint_id)
        return _to_constraint(row, bic, responsible)

    def _parties(
        self, principal_id: str, constraint_id: str
    ) -> tuple[tuple[PartyRef, ...], tuple[PartyRef, ...]]:
        rows = list(
            self._connection.execute(
                principal_scoped(
                    select(*project_constraint_parties.c),
                    project_constraint_parties,
                    capture_context(principal_id),
                )
                .where(project_constraint_parties.c.constraint_id == constraint_id)
                .order_by(
                    asc(project_constraint_parties.c.role),
                    asc(project_constraint_parties.c.ordinal),
                )
            ).all()
        )
        return _split_parties(rows)

    def insert_constraint(
        self,
        principal_id: str,
        constraint: ProjectConstraint,
        *,
        current_revision_id: str | None = None,
    ) -> None:
        values = _constraint_columns(constraint)
        values["constraint_id"] = constraint.constraint_id
        values["created_at"] = constraint.created_at
        values["current_revision_id"] = current_revision_id
        self._connection.execute(
            insert(project_constraints).values(_bound(project_constraints, principal_id, values))
        )
        self._write_parties(principal_id, constraint)

    def update_constraint(
        self,
        principal_id: str,
        constraint: ProjectConstraint,
        *,
        current_revision_id: str | None = None,
    ) -> None:
        values = _constraint_columns(constraint)
        if current_revision_id is not None:
            values["current_revision_id"] = current_revision_id
        self._connection.execute(
            update(project_constraints)
            .where(
                _mine(project_constraints, principal_id),
                project_constraints.c.constraint_id == constraint.constraint_id,
            )
            .values(**values)
        )
        self._connection.execute(
            delete(project_constraint_parties).where(
                _mine(project_constraint_parties, principal_id),
                project_constraint_parties.c.constraint_id == constraint.constraint_id,
            )
        )
        self._write_parties(principal_id, constraint)

    def _write_parties(self, principal_id: str, constraint: ProjectConstraint) -> None:
        rows = [
            _bound(
                project_constraint_parties,
                principal_id,
                {
                    "party_assignment_id": _party_assignment_id(
                        constraint.constraint_id, role, ordinal
                    ),
                    "constraint_id": constraint.constraint_id,
                    "role": role,
                    "ordinal": ordinal,
                    "created_at": constraint.updated_at,
                    "updated_at": constraint.updated_at,
                    **_party_columns(party),
                },
            )
            for role, parties in (
                (_BIC_ROLE, constraint.bic),
                (_RESPONSIBLE_ROLE, constraint.responsible),
            )
            for ordinal, party in enumerate(parties)
        ]
        if rows:
            self._connection.execute(insert(project_constraint_parties), rows)

    # --- Revisions -------------------------------------------------------

    def insert_revision(self, principal_id: str, revision: ConstraintRevision) -> None:
        self._connection.execute(
            insert(project_constraint_revisions).values(
                _bound(
                    project_constraint_revisions,
                    principal_id,
                    {
                        "revision_id": revision.revision_id,
                        "constraint_id": revision.constraint_id,
                        "history_id": revision.history_id,
                        "version": revision.version,
                        "project_id": revision.project_id,
                        "category_id": revision.category_id,
                        "constraint_code": revision.constraint_code,
                        "description": revision.description,
                        "date_identified": revision.date_identified,
                        "lifecycle_state": revision.lifecycle_state.value,
                        "due_date": revision.due_date,
                        "reference": revision.reference,
                        "current_update": revision.current_update,
                        "completion_date": revision.completion_date,
                        "closure_commentary": revision.closure_commentary,
                        "voided_date": revision.voided_date,
                        "void_reason": revision.void_reason,
                        "record_quality": revision.record_quality.value,
                        "origin": revision.origin.value,
                        "published_at": revision.published_at,
                        "recorded_at": revision.recorded_at,
                    },
                )
            )
        )
        rows = [
            _bound(
                project_constraint_revision_parties,
                principal_id,
                {
                    "revision_id": revision.revision_id,
                    "role": role,
                    "ordinal": ordinal,
                    **_party_columns(party),
                },
            )
            for role, parties in (
                (_BIC_ROLE, revision.bic),
                (_RESPONSIBLE_ROLE, revision.responsible),
            )
            for ordinal, party in enumerate(parties)
        ]
        if rows:
            self._connection.execute(insert(project_constraint_revision_parties), rows)

    def get_revision(
        self, principal_id: str, constraint_id: str, version: int
    ) -> ConstraintRevision | None:
        row = self._connection.execute(
            principal_scoped(
                select(*project_constraint_revisions.c),
                project_constraint_revisions,
                capture_context(principal_id),
            ).where(
                project_constraint_revisions.c.constraint_id == constraint_id,
                project_constraint_revisions.c.version == version,
            )
        ).one_or_none()
        if row is None:
            return None
        party_rows = list(
            self._connection.execute(
                principal_scoped(
                    select(*project_constraint_revision_parties.c),
                    project_constraint_revision_parties,
                    capture_context(principal_id),
                )
                .where(
                    project_constraint_revision_parties.c.revision_id == row._mapping["revision_id"]
                )
                .order_by(
                    asc(project_constraint_revision_parties.c.role),
                    asc(project_constraint_revision_parties.c.ordinal),
                )
            ).all()
        )
        bic, responsible = _split_parties(party_rows)
        return _to_revision(row, bic, responsible)

    # --- Mutation receipts -----------------------------------------------

    def insert_history(self, principal_id: str, entry: ConstraintHistoryEntry) -> None:
        self._connection.execute(
            insert(project_constraint_history).values(
                _bound(
                    project_constraint_history,
                    principal_id,
                    {
                        "history_id": entry.history_id,
                        "constraint_id": entry.constraint_id,
                        "project_id": entry.project_id,
                        "operation": entry.operation.value,
                        "actor": entry.actor.value,
                        "outcome": entry.outcome.value,
                        "before_version": entry.before_version,
                        "after_version": entry.after_version,
                        "occurred_at": entry.occurred_at,
                        "recorded_at": entry.recorded_at,
                        "idempotency_key": entry.idempotency_key,
                        "request_digest": entry.request_digest,
                        "client_context": entry.client_context,
                        "revision_id": entry.revision_id,
                        "correlation_id": entry.correlation_id,
                        "safe_failure_reason": entry.safe_failure_reason,
                    },
                )
            )
        )

    def find_history_by_idempotency_key(
        self, principal_id: str, idempotency_key: str
    ) -> ConstraintHistoryEntry | None:
        row = self._connection.execute(
            principal_scoped(
                select(*project_constraint_history.c),
                project_constraint_history,
                capture_context(principal_id),
            ).where(project_constraint_history.c.idempotency_key == idempotency_key)
        ).one_or_none()
        return None if row is None else _to_history(row)

    def insert_category_history(
        self, principal_id: str, entry: ConstraintCategoryHistoryEntry
    ) -> None:
        self._connection.execute(
            insert(constraint_category_history).values(
                _bound(
                    constraint_category_history,
                    principal_id,
                    {
                        "history_id": entry.history_id,
                        "category_id": entry.category_id,
                        "project_id": entry.project_id,
                        "operation": entry.operation.value,
                        "actor": entry.actor.value,
                        "outcome": entry.outcome.value,
                        "before_version": entry.before_version,
                        "after_version": entry.after_version,
                        "occurred_at": entry.occurred_at,
                        "recorded_at": entry.recorded_at,
                        "idempotency_key": entry.idempotency_key,
                        "request_digest": entry.request_digest,
                        "client_context": entry.client_context,
                        "correlation_id": entry.correlation_id,
                        "safe_failure_reason": entry.safe_failure_reason,
                    },
                )
            )
        )

    # --- The read plane (PC-CM-IMP-WP03) ---------------------------------

    def list_categories(
        self,
        principal_id: str,
        project_id: str,
        *,
        include_states: frozenset[ConstraintCategoryState] | None = None,
    ) -> tuple[ConstraintCategoryRow, ...]:
        """P1. One Project's Categories, in display order, one statement.

        `display_order` alone is not a total order — nothing stops two
        Categories sharing one — so the identifier closes it and a reader sees
        the same list in the same order twice. `include_states` of `None` means
        every state on purpose: an `INACTIVE` Category still names the codes it
        issued, and a filter list that omitted it would leave those rows
        unattributable.
        """
        statement = principal_scoped(
            select(*constraint_categories.c),
            constraint_categories,
            capture_context(principal_id),
        ).where(constraint_categories.c.project_id == project_id)
        if include_states is not None:
            statement = statement.where(
                constraint_categories.c.state.in_(sorted(state.value for state in include_states))
            )
        rows = self._connection.execute(
            statement.order_by(
                asc(constraint_categories.c.display_order),
                asc(constraint_categories.c.category_id),
            )
        ).all()
        return tuple(_to_category_row(row) for row in rows)

    def read_constraint(
        self, principal_id: str, constraint_id: str
    ) -> PersistedConstraintRecord | None:
        """P2. One Constraint as a read record, parties joined, one statement.

        The read sibling of `get`, and the reason a legacy import is visible at
        all: `_to_read_record` copies the row across without the aggregate
        constructor, so the same row that makes `get` raise
        `ConstraintInvariantError` is returned here intact, with every absent
        value still absent.

        The parties arrive through an outer join rather than a second statement
        — a Constraint has a handful of them and they are what
        `legacy_missing_fields` needs to say whether BIC is missing. A
        Constraint with none still returns exactly one row, which the join's
        outer half is for.
        """
        party = project_constraint_parties
        rows = self._connection.execute(
            principal_scoped(
                select(
                    *project_constraints.c,
                    party.c.role.label("party_role"),
                    party.c.ordinal.label("party_ordinal"),
                    party.c.party_kind.label("party_kind"),
                    party.c.entity_id.label("party_entity_id"),
                    party.c.display_label.label("party_display_label"),
                ).select_from(
                    project_constraints.outerjoin(
                        party,
                        and_(
                            matching_partition_criterion(project_constraints, party),
                            party.c.constraint_id == project_constraints.c.constraint_id,
                        ),
                    )
                ),
                project_constraints,
                capture_context(principal_id),
            )
            .where(project_constraints.c.constraint_id == constraint_id)
            .order_by(asc(party.c.role), asc(party.c.ordinal))
        ).all()
        if not rows:
            return None
        bic: list[PartyRef] = []
        responsible: list[PartyRef] = []
        for row in rows:
            mapping = row._mapping
            if mapping["party_role"] is None:
                continue
            reference = (
                PartyRef(kind=PartyKind.PRINCIPAL)
                if mapping["party_kind"] == PartyKind.PRINCIPAL.value
                else PartyRef(
                    kind=PartyKind(mapping["party_kind"]),
                    entity_id=mapping["party_entity_id"],
                    label=mapping["party_display_label"],
                )
            )
            target = bic if mapping["party_role"] == _BIC_ROLE else responsible
            target.append(reference)
        return _to_read_record(rows[0], tuple(bic), tuple(responsible))

    def list_constraints(
        self, principal_id: str, project_id: str, *, spec: ConstraintListSpec
    ) -> tuple[PersistedConstraintRecord, ...]:
        """P3. One page of the Register: filters, keyset and limit, all in SQL.

        One statement, whatever the page contains. The Category is outer-joined
        because the Code sort orders by the Category's `display_order` and
        `prefix` and a Draft has no Category at all; the party filters are
        `EXISTS` subqueries so a Constraint waiting on three people is still one
        row; and the limit is `spec.fetch_limit`, already the caller's limit plus
        one, applied by the database rather than by slicing what came back.

        The returned records carry no parties. A page's parties are one bulk
        read (`parties_for`), which is the difference between a page whose cost
        is bounded and one whose cost the data decides.
        """
        components = _order_components(spec)
        statement = principal_scoped(
            select(*project_constraints.c).select_from(
                project_constraints.outerjoin(
                    constraint_categories,
                    and_(
                        matching_partition_criterion(project_constraints, constraint_categories),
                        constraint_categories.c.category_id == project_constraints.c.category_id,
                    ),
                )
            ),
            project_constraints,
            capture_context(principal_id),
        ).where(
            project_constraints.c.project_id == project_id,
            *_list_predicates(principal_id, spec),
        )
        if spec.query.sync_states:
            statement = statement.where(
                _sync_state_expression(principal_id, project_id).in_(
                    sorted(state.value for state in spec.query.sync_states)
                )
            )
        if spec.after is not None:
            statement = statement.where(
                _after_predicate(components, _anchor_values(spec, spec.after))
            )
        ordered = statement.order_by(
            *(
                asc(expression) if ascending else desc(expression)
                for expression, ascending in components
            )
        ).limit(spec.fetch_limit)
        return tuple(_to_read_record(row) for row in self._connection.execute(ordered).all())

    def parties_for(
        self, principal_id: str, constraint_ids: Collection[str]
    ) -> tuple[ConstraintPartyRow, ...]:
        """P4. Every party row for a whole page, in one statement.

        `IN` over the page's identifiers, served by
        `project_constraint_parties_by_principal_constraint`. The ordering is
        `(constraint_id, role, ordinal)` so the caller can group without sorting
        and so a multi-party Constraint's BIC list comes back in the order it
        was stored. An empty page issues no statement: there is nothing to ask.
        """
        wanted = sorted(set(constraint_ids))
        if not wanted:
            return ()
        rows = self._connection.execute(
            principal_scoped(
                select(*project_constraint_parties.c),
                project_constraint_parties,
                capture_context(principal_id),
            )
            .where(project_constraint_parties.c.constraint_id.in_(wanted))
            .order_by(
                asc(project_constraint_parties.c.constraint_id),
                asc(project_constraint_parties.c.role),
                asc(project_constraint_parties.c.ordinal),
            )
        ).all()
        return tuple(_to_party_row(row) for row in rows)

    def entity_labels(self, principal_id: str, entity_ids: Collection[str]) -> Mapping[str, str]:
        """P5. Display names for a page's ENTITY parties, in one statement.

        `_mine`-scoped, so an Entity in another Principal's partition is simply
        absent from the mapping and the party falls back to its preserved
        wording — the foreign Entity is never named and its existence is not
        distinguishable from its absence. Called only when at least one ENTITY
        party has no stored label of its own, so a page whose parties all carry
        their own labels issues no statement here at all.
        """
        wanted = sorted(set(entity_ids))
        if not wanted:
            return {}
        rows = self._connection.execute(
            principal_scoped(
                select(entities.c.entity_id, entities.c.display_name),
                entities,
                capture_context(principal_id),
            ).where(entities.c.entity_id.in_(wanted))
        ).all()
        return {row._mapping["entity_id"]: row._mapping["display_name"] for row in rows}

    def list_history(
        self,
        principal_id: str,
        constraint_id: str,
        *,
        limit: int,
        after: ConstraintHistoryPosition | None = None,
    ) -> tuple[ConstraintHistoryRow, ...]:
        """P6. One page of mutation receipts, newest first, one statement.

        Ordered by `(occurred_at, history_id)` descending, which is a total
        order because two receipts can share an instant but not an identifier;
        the keyset continues from exactly that pair. Only the safe columns are
        selected — the request digest, idempotency key, client context and
        correlation identifier are not in the projection, so a later field
        cannot leak one by accident.
        """
        statement = principal_scoped(
            select(
                project_constraint_history.c.history_id,
                project_constraint_history.c.constraint_id,
                project_constraint_history.c.operation,
                project_constraint_history.c.actor,
                project_constraint_history.c.outcome,
                project_constraint_history.c.before_version,
                project_constraint_history.c.after_version,
                project_constraint_history.c.occurred_at,
                project_constraint_history.c.revision_id,
                project_constraint_history.c.safe_failure_reason,
            ),
            project_constraint_history,
            capture_context(principal_id),
        ).where(project_constraint_history.c.constraint_id == constraint_id)
        if after is not None:
            statement = statement.where(
                or_(
                    project_constraint_history.c.occurred_at < after.occurred_at,
                    and_(
                        project_constraint_history.c.occurred_at == after.occurred_at,
                        project_constraint_history.c.history_id < after.history_id,
                    ),
                )
            )
        rows = self._connection.execute(
            statement.order_by(
                desc(project_constraint_history.c.occurred_at),
                desc(project_constraint_history.c.history_id),
            ).limit(limit)
        ).all()
        return tuple(
            ConstraintHistoryRow(
                history_id=row._mapping["history_id"],
                constraint_id=row._mapping["constraint_id"],
                operation=ConstraintMutationOperation(row._mapping["operation"]),
                actor=ConstraintMutationActor(row._mapping["actor"]),
                outcome=ConstraintMutationOutcome(row._mapping["outcome"]),
                before_version=row._mapping["before_version"],
                after_version=row._mapping["after_version"],
                occurred_at=row._mapping["occurred_at"],
                revision_id=row._mapping["revision_id"],
                safe_failure_reason=row._mapping["safe_failure_reason"],
            )
            for row in rows
        )

    def relationships_for(
        self, principal_id: str, constraint_id: str
    ) -> tuple[ConstraintRelationshipRow, ...]:
        """P7. Both ends of every relationship this Constraint is part of, one statement.

        The far end's code and status are joined from `project_constraints` with
        the partition predicate applied to **both** sides — `_mine` on the
        relationship and `matching_partition_criterion` on the join. A
        relationship whose other end is not readable in this partition therefore
        returns no row at all, rather than a row with a gap in it that a reader
        could infer the far end's existence from.
        """
        relationship = project_constraint_relationships
        related_id = case(
            (
                relationship.c.source_constraint_id == constraint_id,
                relationship.c.target_constraint_id,
            ),
            else_=relationship.c.source_constraint_id,
        )
        rows = self._connection.execute(
            principal_scoped(
                select(
                    relationship.c.relationship_id,
                    relationship.c.relationship_type,
                    relationship.c.source_constraint_id,
                    related_id.label("related_constraint_id"),
                    project_constraints.c.constraint_code.label("related_constraint_code"),
                    project_constraints.c.lifecycle_state.label("related_lifecycle_state"),
                ).select_from(
                    relationship.join(
                        project_constraints,
                        and_(
                            matching_partition_criterion(relationship, project_constraints),
                            project_constraints.c.constraint_id == related_id,
                        ),
                    )
                ),
                relationship,
                capture_context(principal_id),
            )
            .where(
                or_(
                    relationship.c.source_constraint_id == constraint_id,
                    relationship.c.target_constraint_id == constraint_id,
                )
            )
            .order_by(asc(relationship.c.created_at), asc(relationship.c.relationship_id))
        ).all()
        return tuple(
            ConstraintRelationshipRow(
                relationship_id=row._mapping["relationship_id"],
                relationship_type=row._mapping["relationship_type"],
                direction=(
                    RelationshipDirection.OUTGOING
                    if row._mapping["source_constraint_id"] == constraint_id
                    else RelationshipDirection.INCOMING
                ),
                related_constraint_id=row._mapping["related_constraint_id"],
                related_constraint_code=row._mapping["related_constraint_code"],
                related_status=ConstraintLifecycleState(row._mapping["related_lifecycle_state"]),
            )
            for row in rows
        )

    def evidence_links_for(
        self, principal_id: str, constraint_id: str
    ) -> tuple[ConstraintEvidenceLinkRow, ...]:
        """P8. Every evidence citation on one Constraint, as references only.

        The identifier, its kind and the role it plays. No body, no title, no
        provider name and no workbook locator is selected, because a citation is
        a pointer and resolving it is the owning plane's decision rather than
        this one's.
        """
        rows = self._connection.execute(
            principal_scoped(
                select(
                    project_constraint_evidence_links.c.evidence_link_id,
                    project_constraint_evidence_links.c.evidence_kind,
                    project_constraint_evidence_links.c.evidence_ref,
                    project_constraint_evidence_links.c.role,
                ),
                project_constraint_evidence_links,
                capture_context(principal_id),
            )
            .where(project_constraint_evidence_links.c.constraint_id == constraint_id)
            .order_by(
                asc(project_constraint_evidence_links.c.created_at),
                asc(project_constraint_evidence_links.c.evidence_link_id),
            )
        ).all()
        return tuple(
            ConstraintEvidenceLinkRow(
                evidence_link_id=row._mapping["evidence_link_id"],
                evidence_kind=row._mapping["evidence_kind"],
                evidence_ref=row._mapping["evidence_ref"],
                role=row._mapping["role"],
            )
            for row in rows
        )

    def sync_summary(
        self, principal_id: str, project_id: str, constraint_ids: Collection[str]
    ) -> ConstraintSyncFacts:
        """P9. The stored facts the four derivable sync states read from. Two statements.

        The first joins the Project's sync targets to their baselines, so target
        existence, the last verified instant and every baseline version arrive
        together rather than as three questions. The second counts open
        conflicts per Constraint. An empty `constraint_ids` means the whole
        Project, which is what the overview roll-up asks for.

        **Read-only in the strict sense.** No statement here writes, and nothing
        in this method starts a run, takes or renews a lease, reads a workbook,
        calls a connector, or compares three ways. Those are WP11's behavior;
        what this reports is what is already on disk.
        """
        wanted = sorted(set(constraint_ids))
        baseline_join: ColumnElement[bool] = and_(
            matching_partition_criterion(constraint_sync_targets, constraint_sync_baselines),
            constraint_sync_baselines.c.sync_target_id == constraint_sync_targets.c.sync_target_id,
        )
        if wanted:
            baseline_join = and_(
                baseline_join, constraint_sync_baselines.c.constraint_id.in_(wanted)
            )
        target_rows = self._connection.execute(
            principal_scoped(
                select(
                    constraint_sync_targets.c.last_verified_at,
                    constraint_sync_baselines.c.constraint_id.label("baseline_constraint_id"),
                    constraint_sync_baselines.c.baseline_constraint_version,
                ).select_from(
                    constraint_sync_targets.outerjoin(constraint_sync_baselines, baseline_join)
                ),
                constraint_sync_targets,
                capture_context(principal_id),
            ).where(constraint_sync_targets.c.project_id == project_id)
        ).all()
        baseline_versions: dict[str, int] = {}
        verified: list[datetime] = []
        for row in target_rows:
            mapping = row._mapping
            if mapping["last_verified_at"] is not None:
                verified.append(mapping["last_verified_at"])
            baseline_id = mapping["baseline_constraint_id"]
            if baseline_id is not None:
                version = mapping["baseline_constraint_version"]
                baseline_versions[baseline_id] = max(
                    version, baseline_versions.get(baseline_id, version)
                )
        conflict_statement = principal_scoped(
            select(
                constraint_sync_conflicts.c.constraint_id,
                func.count().label("open_conflicts"),
            ),
            constraint_sync_conflicts,
            capture_context(principal_id),
        ).where(
            constraint_sync_conflicts.c.project_id == project_id,
            constraint_sync_conflicts.c.state == _OPEN_CONFLICT,
            constraint_sync_conflicts.c.constraint_id.is_not(None),
        )
        if wanted:
            conflict_statement = conflict_statement.where(
                constraint_sync_conflicts.c.constraint_id.in_(wanted)
            )
        conflict_rows = self._connection.execute(
            conflict_statement.group_by(constraint_sync_conflicts.c.constraint_id)
        ).all()
        return ConstraintSyncFacts(
            has_target=bool(target_rows),
            last_verified_at=max(verified) if verified else None,
            baseline_versions=baseline_versions,
            open_conflict_counts={
                row._mapping["constraint_id"]: row._mapping["open_conflicts"]
                for row in conflict_rows
            },
        )

    def overview_facts(
        self,
        principal_id: str,
        project_id: str,
        *,
        as_of: datetime,
        project_today: date,
        due_soon_through: date,
    ) -> ConstraintOverviewFacts:
        """P10. Every overview count for one Project, from one aggregate statement.

        The inner select narrows to the Principal's rows in this Project and
        decides, per row, the three things a count needs that a column does not
        already say: whether BIC names the Principal, whether a sync conflict is
        open, and how many working days the record has been open. The outer
        select is then nothing but `count(*) FILTER (…)` over those columns, so
        every metric is computed from the same rows in the same pass.

        Overdue and Due Soon are disjoint by construction — one is strictly
        before the Project date and the other begins at it — and a row with no
        Due Date is in neither, so a legacy import cannot appear as falsely
        overdue. The open-age numerator and denominator both exclude a row with
        no `date_identified`, which is how an undated legacy import stays out of
        the average instead of dragging it to zero.
        """
        active = project_constraints.c.lifecycle_state.in_(_ACTIVE_STATE_VALUES)
        inner = (
            principal_scoped(
                select(
                    project_constraints.c.lifecycle_state.label("lifecycle_state"),
                    project_constraints.c.record_quality.label("record_quality"),
                    project_constraints.c.due_date.label("due_date"),
                    project_constraints.c.completion_date.label("completion_date"),
                    project_constraints.c.updated_at.label("updated_at"),
                    project_constraints.c.date_identified.label("date_identified"),
                    active.label("is_active"),
                    _principal_bic_exists(principal_id).label("has_principal_bic"),
                    _open_conflict_exists(principal_id).label("has_open_conflict"),
                    _business_days_elapsed(
                        project_constraints.c.date_identified, literal(project_today, Date)
                    ).label("open_age"),
                ),
                project_constraints,
                capture_context(principal_id),
            )
            .where(project_constraints.c.project_id == project_id)
            .subquery()
        )
        dated_and_active = and_(inner.c.is_active, inner.c.date_identified.is_not(None))
        row = self._connection.execute(
            select(
                func.count().filter(inner.c.is_active).label("total_open"),
                func.count()
                .filter(
                    and_(
                        inner.c.is_active,
                        inner.c.due_date.is_not(None),
                        inner.c.due_date < project_today,
                    )
                )
                .label("overdue"),
                func.count()
                .filter(
                    and_(
                        inner.c.is_active,
                        inner.c.due_date.is_not(None),
                        inner.c.due_date >= project_today,
                        inner.c.due_date <= due_soon_through,
                    )
                )
                .label("due_soon"),
                func.count()
                .filter(and_(inner.c.is_active, inner.c.has_principal_bic))
                .label("in_my_court"),
                func.count()
                .filter(inner.c.lifecycle_state == ConstraintLifecycleState.ON_HOLD.value)
                .label("on_hold"),
                func.count()
                .filter(inner.c.updated_at >= as_of - timedelta(days=RECENT_WINDOW_DAYS))
                .label("recently_changed"),
                func.count()
                .filter(
                    and_(
                        inner.c.lifecycle_state == ConstraintLifecycleState.CLOSED.value,
                        inner.c.completion_date.is_not(None),
                        inner.c.completion_date
                        >= project_today - timedelta(days=RECENT_WINDOW_DAYS - 1),
                        inner.c.completion_date <= project_today,
                    )
                )
                .label("recently_closed"),
                func.count()
                .filter(inner.c.lifecycle_state == ConstraintLifecycleState.DRAFT.value)
                .label("draft"),
                func.count()
                .filter(
                    or_(
                        inner.c.record_quality == ConstraintRecordQuality.LEGACY_INCOMPLETE.value,
                        inner.c.has_open_conflict,
                    )
                )
                .label("needs_attention"),
                func.coalesce(
                    func.sum(inner.c.open_age).filter(dated_and_active), literal(0, Integer)
                ).label("open_age_sum"),
                func.count().filter(dated_and_active).label("open_age_denominator"),
            )
        ).one()
        mapping = row._mapping
        return ConstraintOverviewFacts(
            total_open=mapping["total_open"],
            overdue=mapping["overdue"],
            due_soon=mapping["due_soon"],
            in_my_court=mapping["in_my_court"],
            on_hold=mapping["on_hold"],
            recently_changed=mapping["recently_changed"],
            recently_closed=mapping["recently_closed"],
            draft=mapping["draft"],
            needs_attention=mapping["needs_attention"],
            open_age_business_day_sum=int(mapping["open_age_sum"]),
            open_age_denominator=mapping["open_age_denominator"],
        )


def _archived_at(category: ConstraintCategory) -> object:
    """The stored `archived_at`, which the table pairs exactly with the archived state."""
    return category.updated_at if category.state is ConstraintCategoryState.ARCHIVED else None


def _constraint_columns(constraint: ProjectConstraint) -> dict[str, object]:
    """The Constraint scalars an insert and an update both write."""
    return {
        "project_id": constraint.project_id,
        "category_id": constraint.category_id,
        "constraint_code": constraint.constraint_code,
        "description": constraint.description,
        "date_identified": constraint.date_identified,
        "lifecycle_state": constraint.lifecycle_state.value,
        "due_date": constraint.due_date,
        "reference": constraint.reference,
        "current_update": constraint.current_update,
        "completion_date": constraint.completion_date,
        "closure_commentary": constraint.closure_commentary,
        "voided_date": constraint.voided_date,
        "void_reason": constraint.void_reason,
        "record_quality": constraint.record_quality.value,
        "origin": constraint.origin.value,
        "published_at": constraint.published_at,
        "version": constraint.version,
        "updated_at": constraint.updated_at,
    }


class SqlAlchemyConstraintManagementUnitOfWork(ConstraintManagementUnitOfWork):
    """One PostgreSQL transaction over the Constraint Management tables.

    The identical shape `SqlAlchemyCommitmentManagementUnitOfWork` establishes:
    the unit of work owns `engine.begin()`, and the repository it hands out
    issues statements on that connection and never commits.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._context: AbstractContextManager[Connection] | None = None
        self._connection: Connection | None = None

    def __enter__(self) -> ConstraintManagementUnitOfWork:
        if self._context is not None:
            raise RuntimeError("this unit of work is already inside a transaction")
        context = self._engine.begin()
        self._connection = context.__enter__()
        self._context = context
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        context = self._context
        self._context = None
        self._connection = None
        if context is not None:
            context.__exit__(exc_type, exc, traceback)

    @property
    def constraints(self) -> ConstraintManagementRepository:
        connection = self._connection
        if connection is None:
            raise RuntimeError("this unit of work is not inside a transaction")
        return SqlConstraintManagementRepository(connection)
