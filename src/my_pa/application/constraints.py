"""Read the Constraint plane: one Project calendar, one set of derivations, six answers.

PC-CM-IMP-WP03. This module is the only place a Constraint read is composed, and
it exists mainly to make one thing structurally true: **every date-derived answer
in the plane comes from one calendar resolution.** A request resolves the
Project's `project_today` once, derives `due_soon_through` from it once, and
hands both to the rows it renders *and* to the aggregate statement that counts
them. A list row saying "overdue" and an overview count of overdue rows are
therefore the same claim by construction, not by two implementations agreeing.

The derivations themselves are not here. `is_overdue`, `is_due_soon`,
`business_days_elapsed` and `in_my_court` live in the WP01 domain and are called
unchanged; this module orchestrates them and reimplements none. In My Court in
particular is the explicit PRINCIPAL-BIC rule and nothing more: no Principal is
bound to an Entity anywhere in this repository, so `principal_bound_entity_ids`
is passed empty, and no name, label, email, or substring is compared. An
Entity-backed In My Court is a bounded gap, disclosed rather than guessed at.

The service is stateless — a frozen dataclass with no constructor dependencies —
and its narrow read port is a local `Protocol` handed in per call, the shape
`application.identity_history` established. That keeps the application layer free
of any infrastructure import and makes every method testable against a fake with
no container, no transaction, and no clock to freeze: `now` is an argument.

Errors follow the plane's nondisclosure posture exactly. Absent and foreign are
the same answer (`NotFoundError`). A cursor that cannot be read is
`InvalidRequestError`; one that reads but belongs to another request is
`ConflictError`; neither restarts the listing quietly and neither says which it
was. And an unavailable Project calendar is `UnavailableError` — never a zero,
never an empty page, because "no overdue constraints" and "I could not tell you"
are different sentences and only one of them is safe to act on.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from my_pa.application.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
    UnavailableError,
)
from my_pa.domain.common.identifiers import InvalidIdentifierError
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.project_controls.business_time import (
    ProjectTimezoneError,
    business_days_elapsed,
    due_soon_through,
    is_due_soon,
    is_overdue,
    project_today,
)
from my_pa.domain.project_controls.category import ConstraintCategoryState
from my_pa.domain.project_controls.constraint import ConstraintLifecycleState, in_my_court
from my_pa.domain.project_controls.party import PartyKind
from my_pa.domain.project_controls.read_models import (
    MAX_CURSOR_CHARACTERS,
    PRINCIPAL_DISPLAY_LABEL,
    PRINCIPAL_PARTY_REF,
    UNKNOWN_DISPLAY_LABEL,
    ConstraintCategoryRef,
    ConstraintCategoryRow,
    ConstraintCategoryView,
    ConstraintCompletionView,
    ConstraintCursorError,
    ConstraintEvidenceLinkRow,
    ConstraintEvidenceLinkView,
    ConstraintGrouping,
    ConstraintHistoryEntryView,
    ConstraintHistoryPage,
    ConstraintHistoryPosition,
    ConstraintHistoryRow,
    ConstraintListCursor,
    ConstraintListEntry,
    ConstraintListPage,
    ConstraintListQuery,
    ConstraintListSpec,
    ConstraintOverview,
    ConstraintOverviewFacts,
    ConstraintPartyRow,
    ConstraintRelationshipRow,
    ConstraintRelationshipView,
    ConstraintSort,
    ConstraintSyncFacts,
    ConstraintSyncHealthView,
    ConstraintSyncStateView,
    ConstraintSyncSummaryView,
    ConstraintView,
    ConstraintVoidView,
    PartyRefView,
    PersistedConstraintRecord,
    attention_for,
    party_refs_of,
)
from my_pa.domain.project_controls.settings import ConstraintProjectSettings

__all__ = ["ConstraintReadRepository", "ConstraintReadService"]

_BIC_ROLE = "bic"
_RESPONSIBLE_ROLE = "responsible"

#: The one history order there is, named so that a cursor binds it. If a second
#: order is ever offered this value changes and every token issued under the old
#: one stops validating.
_HISTORY_ORDER = "occurred_at_desc_history_id_desc_v1"

#: The leading component of every keyset anchor: whether the row has the sort
#: key at all. `NULLS LAST` is then a comparison on a value rather than a rule
#: the predicate has to carry separately, and an absent key is never represented
#: by a stand-in that a real value could equal.
_KEY_PRESENT = 0
_KEY_ABSENT = 1

#: The largest history page this service will issue. The same ceiling every
#: other paged plane here uses, for the same reason.
MAX_HISTORY_PAGE_SIZE = 100
DEFAULT_HISTORY_PAGE_SIZE = 50


class ConstraintReadRepository(Protocol):
    """The narrow read port the Constraint read plane requires.

    Structural, and satisfied by the persistence adapter without it importing
    anything from here. Ten read methods plus the settings read that resolves
    the Project calendar — nothing that writes, locks, or mutates is nameable
    through this port at all.
    """

    def get_project_settings(
        self, principal_id: str, project_id: str
    ) -> ConstraintProjectSettings | None:
        """This Principal's Constraint settings for one Project, or `None`."""

    def list_categories(
        self,
        principal_id: str,
        project_id: str,
        *,
        include_states: frozenset[ConstraintCategoryState] | None = None,
    ) -> tuple[ConstraintCategoryRow, ...]:
        """This Principal's Categories for one Project, in display order."""

    def read_constraint(
        self, principal_id: str, constraint_id: str
    ) -> PersistedConstraintRecord | None:
        """One Constraint as a read record, parties included, or `None`."""

    def list_constraints(
        self, principal_id: str, project_id: str, *, spec: ConstraintListSpec
    ) -> tuple[PersistedConstraintRecord, ...]:
        """One page of Register rows, resolved filters and keyset applied in SQL."""

    def parties_for(
        self, principal_id: str, constraint_ids: Collection[str]
    ) -> tuple[ConstraintPartyRow, ...]:
        """Every BIC and Responsible row for the named Constraints, in stored order."""

    def entity_labels(self, principal_id: str, entity_ids: Collection[str]) -> Mapping[str, str]:
        """Display names for the named Entities in this Principal's partition."""

    def list_history(
        self,
        principal_id: str,
        constraint_id: str,
        *,
        limit: int,
        after: ConstraintHistoryPosition | None = None,
    ) -> tuple[ConstraintHistoryRow, ...]:
        """One page of mutation receipts, newest first, keyset-continued."""

    def relationships_for(
        self, principal_id: str, constraint_id: str
    ) -> tuple[ConstraintRelationshipRow, ...]:
        """Every relationship this Constraint is either end of, with the far end joined."""

    def evidence_links_for(
        self, principal_id: str, constraint_id: str
    ) -> tuple[ConstraintEvidenceLinkRow, ...]:
        """Every evidence citation on one Constraint, as references and never as content."""

    def sync_summary(
        self, principal_id: str, project_id: str, constraint_ids: Collection[str]
    ) -> ConstraintSyncFacts:
        """The stored facts the four derivable sync states are read from."""

    def overview_facts(
        self,
        principal_id: str,
        project_id: str,
        *,
        as_of: datetime,
        project_today: date,
        due_soon_through: date,
    ) -> ConstraintOverviewFacts:
        """Every overview count for one Project, from one aggregate statement."""


@dataclass(frozen=True, slots=True)
class ConstraintReadService:
    """The six Constraint reads, each bounded, principal-scoped, and fail-closed."""

    def list_categories(
        self,
        repository: ConstraintReadRepository,
        *,
        principal_id: str,
        project_id: str,
        include_states: frozenset[ConstraintCategoryState] | None = None,
    ) -> tuple[ConstraintCategoryView, ...]:
        """Every Category of one Project, in display order.

        Needs no Project date, so it succeeds for a Project whose timezone
        nobody has configured. A Project belonging to another Principal returns
        nothing, which is what an empty Project returns.
        """
        rows = repository.list_categories(principal_id, project_id, include_states=include_states)
        return tuple(_category_view(row) for row in rows)

    def read_category(
        self,
        repository: ConstraintReadRepository,
        *,
        principal_id: str,
        project_id: str,
        category_id: str,
    ) -> ConstraintCategoryView:
        """One Category of one Project.

        Selected from the Project's own bounded Category list rather than
        through a second statement: a Project has few Categories, and one read
        path means one place the partition predicate has to be right. Absent and
        foreign are the same `NotFoundError`.
        """
        for row in repository.list_categories(principal_id, project_id, include_states=None):
            if row.category_id == category_id:
                return _category_view(row)
        raise NotFoundError()

    def list_constraints(
        self,
        repository: ConstraintReadRepository,
        *,
        principal_id: str,
        project_id: str,
        query: ConstraintListQuery,
        now: datetime,
    ) -> ConstraintListPage:
        """One bounded page of the Register, with every derived flag already decided.

        The order of work is the contract: resolve the calendar, bind the
        cursor, fetch `limit + 1` rows, read the page's parties and sync facts
        once each, then render. Nothing after the fetch can widen the page, and
        nothing before it can be answered without the calendar.
        """
        as_of = ensure_utc(now)
        settings = self._settings(repository, principal_id, project_id)
        today = _project_today(as_of, settings)
        through = due_soon_through(today)
        binding = query.binding(principal_id=principal_id, project_id=project_id)
        after = _decode_cursor(query.cursor, binding)
        spec = ConstraintListSpec(
            query=query,
            as_of=as_of,
            project_today=today,
            due_soon_through=through,
            fetch_limit=query.limit + 1,
            after=after,
        )
        found = repository.list_constraints(principal_id, project_id, spec=spec)
        is_truncated = len(found) > query.limit
        selected = found[: query.limit]
        constraint_ids = tuple(record.constraint_id for record in selected)
        parties = self._parties_by_constraint(repository, principal_id, constraint_ids)
        labels = self._entity_labels(repository, principal_id, parties)
        sync = repository.sync_summary(principal_id, project_id, constraint_ids)
        category_rows = {
            row.category_id: row
            for row in repository.list_categories(principal_id, project_id, include_states=None)
        }
        categories = {
            category_id: ConstraintCategoryRef(row.category_id, row.prefix, row.title)
            for category_id, row in category_rows.items()
        }
        entries = tuple(
            self._list_entry(
                record,
                party_rows=parties.get(record.constraint_id, ()),
                entity_labels=labels,
                categories=categories,
                sync=sync,
                today=today,
                grouping=query.grouping,
            )
            for record in selected
        )
        cursor: str | None = None
        if is_truncated and entries:
            cursor = ConstraintListCursor(
                binding=binding,
                sort_key=_sort_key(selected[-1], query, category_rows),
                constraint_id=selected[-1].constraint_id,
            ).encode()
        return ConstraintListPage(entries=entries, is_truncated=is_truncated, next_cursor=cursor)

    def read_constraint(
        self,
        repository: ConstraintReadRepository,
        *,
        principal_id: str,
        constraint_id: str,
        now: datetime,
    ) -> ConstraintView:
        """One Constraint in full, derived on its own Project's calendar.

        A record with no Project — a Draft saved before one was chosen — is
        still readable: it has no Project calendar, so `days_elapsed` is `None`
        and neither date flag holds, which is the truth about it rather than a
        substituted zero. Once a Project *is* named, its calendar is required
        and an unconfigured one fails closed.
        """
        as_of = ensure_utc(now)
        record = repository.read_constraint(principal_id, constraint_id)
        if record is None:
            raise NotFoundError()
        today: date | None = None
        if record.project_id is not None:
            settings = self._settings(repository, principal_id, record.project_id)
            today = _project_today(as_of, settings)
        party_rows = repository.parties_for(principal_id, (constraint_id,))
        labels = self._entity_labels(repository, principal_id, {constraint_id: party_rows})
        sync = (
            repository.sync_summary(principal_id, record.project_id, (constraint_id,))
            if record.project_id is not None
            else ConstraintSyncFacts(
                has_target=False,
                last_verified_at=None,
                baseline_versions={},
                open_conflict_counts={},
            )
        )
        category: ConstraintCategoryRef | None = None
        if record.project_id is not None and record.category_id is not None:
            for row in repository.list_categories(
                principal_id, record.project_id, include_states=None
            ):
                if row.category_id == record.category_id:
                    category = ConstraintCategoryRef(row.category_id, row.prefix, row.title)
                    break
        conflict_count = sync.open_conflict_counts.get(constraint_id, 0)
        attention = attention_for(record, has_open_conflict=conflict_count > 0)
        relationships = tuple(
            ConstraintRelationshipView(
                relationship_id=row.relationship_id,
                relationship_type=row.relationship_type,
                direction=row.direction,
                related_constraint_id=row.related_constraint_id,
                related_constraint_code=row.related_constraint_code,
                related_status=row.related_status,
            )
            for row in repository.relationships_for(principal_id, constraint_id)
        )
        evidence_links = tuple(
            ConstraintEvidenceLinkView(
                evidence_link_id=row.evidence_link_id,
                evidence_kind=row.evidence_kind,
                evidence_ref=row.evidence_ref,
                role=row.role,
            )
            for row in repository.evidence_links_for(principal_id, constraint_id)
        )
        is_closed = record.lifecycle_state is ConstraintLifecycleState.CLOSED
        is_void = record.lifecycle_state is ConstraintLifecycleState.VOID
        return ConstraintView(
            constraint_id=record.constraint_id,
            project_id=record.project_id,
            constraint_code=record.constraint_code,
            description=record.description,
            category=category,
            status=record.lifecycle_state,
            date_identified=record.date_identified,
            due_date=record.due_date,
            bic=_party_views(party_rows, _BIC_ROLE, labels),
            responsible=_party_views(party_rows, _RESPONSIBLE_ROLE, labels),
            reference=record.reference,
            days_elapsed=_days_elapsed(record.date_identified, today),
            version=record.version,
            created_at=record.created_at,
            updated_at=record.updated_at,
            is_overdue=_is_overdue(record, today),
            is_due_soon=_is_due_soon(record, today),
            in_my_court=in_my_court(
                record.lifecycle_state,
                party_refs_of(party_rows, _BIC_ROLE),
                principal_bound_entity_ids=frozenset(),
            ),
            record_quality=record.record_quality,
            needs_attention=attention.needs_attention,
            needs_attention_reasons=attention.reasons,
            missing_fields=attention.missing_fields,
            is_published=record.lifecycle_state is not ConstraintLifecycleState.DRAFT,
            published_at=record.published_at,
            current_update=record.current_update,
            completion=ConstraintCompletionView(
                completion_date=record.completion_date,
                closure_commentary=record.closure_commentary,
            )
            if is_closed
            else None,
            void=ConstraintVoidView(voided_date=record.voided_date, void_reason=record.void_reason)
            if is_void
            else None,
            sync=ConstraintSyncSummaryView(
                state=_sync_state(record, sync),
                last_verified_at=sync.last_verified_at,
                conflict_count=conflict_count,
            ),
            relationships=relationships,
            evidence_links=evidence_links,
        )

    def read_history(
        self,
        repository: ConstraintReadRepository,
        *,
        principal_id: str,
        constraint_id: str,
        page_size: int = DEFAULT_HISTORY_PAGE_SIZE,
        cursor: str | None = None,
    ) -> ConstraintHistoryPage:
        """One bounded page of mutation receipts, newest first.

        Needs no Project calendar and takes no clock: a receipt records when it
        happened and nothing is derived from now. A Constraint that is absent or
        another Principal's simply has no receipts, which is the same page an
        untouched Constraint returns — one statement, and nothing that could
        distinguish the two.
        """
        if not 1 <= page_size <= MAX_HISTORY_PAGE_SIZE:
            raise InvalidRequestError(SafeDetail.PAGE_SIZE)
        binding = _history_binding(principal_id, constraint_id, page_size)
        after = None if cursor is None else _decode_history_cursor(cursor, binding)
        rows = repository.list_history(
            principal_id, constraint_id, limit=page_size + 1, after=after
        )
        is_truncated = len(rows) > page_size
        selected = rows[:page_size]
        next_cursor: str | None = None
        if is_truncated and selected:
            last = selected[-1]
            next_cursor = _encode_history_cursor(
                binding,
                ConstraintHistoryPosition(occurred_at=last.occurred_at, history_id=last.history_id),
            )
        return ConstraintHistoryPage(
            entries=tuple(
                ConstraintHistoryEntryView(
                    history_id=row.history_id,
                    operation=row.operation,
                    actor=row.actor,
                    outcome=row.outcome,
                    before_version=row.before_version,
                    after_version=row.after_version,
                    occurred_at=row.occurred_at,
                    revision_id=row.revision_id,
                    safe_failure_reason=row.safe_failure_reason,
                )
                for row in selected
            ),
            is_truncated=is_truncated,
            next_cursor=next_cursor,
        )

    def read_overview(
        self,
        repository: ConstraintReadRepository,
        *,
        principal_id: str,
        project_id: str,
        now: datetime,
    ) -> ConstraintOverview:
        """The Project's Constraint position, counted on the Project's own calendar.

        Every count comes from one aggregate statement generated from the same
        `project_today` and `due_soon_through` the Register rows are rendered
        with, which is what makes overview/list coherence a property rather than
        a convention. An unconfigured or unknown timezone fails closed: a count
        of zero overdue Constraints is a claim this service will not make when
        it cannot compute the boundary.
        """
        as_of = ensure_utc(now)
        settings = self._settings(repository, principal_id, project_id)
        today = _project_today(as_of, settings)
        through = due_soon_through(today)
        facts = repository.overview_facts(
            principal_id,
            project_id,
            as_of=as_of,
            project_today=today,
            due_soon_through=through,
        )
        sync = repository.sync_summary(principal_id, project_id, ())
        open_conflicts = sum(sync.open_conflict_counts.values())
        average: float | None = None
        if facts.open_age_denominator > 0:
            average = facts.open_age_business_day_sum / facts.open_age_denominator
        if open_conflicts > 0:
            health_state = ConstraintSyncStateView.CONFLICT
        elif not sync.has_target:
            health_state = ConstraintSyncStateView.NEVER_SYNCED
        else:
            health_state = ConstraintSyncStateView.IN_SYNC
        return ConstraintOverview(
            project_id=project_id,
            project_today=today,
            project_timezone=settings.timezone_name,
            total_open=facts.total_open,
            overdue=facts.overdue,
            due_soon=facts.due_soon,
            due_soon_through=through,
            average_open_age_business_days=average,
            in_my_court=facts.in_my_court,
            on_hold=facts.on_hold,
            recently_changed=facts.recently_changed,
            recently_closed=facts.recently_closed,
            draft=facts.draft,
            needs_attention=facts.needs_attention,
            sync_health=ConstraintSyncHealthView(
                state=health_state,
                open_conflict_count=open_conflicts,
                last_verified_at=sync.last_verified_at,
            ),
            as_of=as_of,
        )

    # --- composition helpers ---------------------------------------------

    def _settings(
        self, repository: ConstraintReadRepository, principal_id: str, project_id: str
    ) -> ConstraintProjectSettings:
        settings = repository.get_project_settings(principal_id, project_id)
        if settings is None:
            # Unconfigured and foreign are the same answer here, and both are
            # unavailable rather than empty: without a calendar there is no
            # defensible Overdue boundary to count against.
            raise UnavailableError(SafeDetail.PROJECT_ID)
        return settings

    def _parties_by_constraint(
        self,
        repository: ConstraintReadRepository,
        principal_id: str,
        constraint_ids: tuple[str, ...],
    ) -> dict[str, tuple[ConstraintPartyRow, ...]]:
        if not constraint_ids:
            return {}
        grouped: dict[str, list[ConstraintPartyRow]] = {}
        for row in repository.parties_for(principal_id, constraint_ids):
            grouped.setdefault(row.constraint_id, []).append(row)
        return {key: tuple(value) for key, value in grouped.items()}

    def _entity_labels(
        self,
        repository: ConstraintReadRepository,
        principal_id: str,
        parties: Mapping[str, tuple[ConstraintPartyRow, ...]],
    ) -> Mapping[str, str]:
        wanted = {
            row.entity_id
            for rows in parties.values()
            for row in rows
            if row.party_kind is PartyKind.ENTITY
            and row.entity_id is not None
            and not row.display_label
        }
        if not wanted:
            return {}
        return repository.entity_labels(principal_id, tuple(sorted(wanted)))

    def _list_entry(
        self,
        record: PersistedConstraintRecord,
        *,
        party_rows: tuple[ConstraintPartyRow, ...],
        entity_labels: Mapping[str, str],
        categories: Mapping[str, ConstraintCategoryRef],
        sync: ConstraintSyncFacts,
        today: date,
        grouping: ConstraintGrouping,
    ) -> ConstraintListEntry:
        conflict_count = sync.open_conflict_counts.get(record.constraint_id, 0)
        attention = attention_for(record, has_open_conflict=conflict_count > 0)
        bic = _party_views(party_rows, _BIC_ROLE, entity_labels)
        responsible = _party_views(party_rows, _RESPONSIBLE_ROLE, entity_labels)
        return ConstraintListEntry(
            constraint_id=record.constraint_id,
            project_id=record.project_id,
            constraint_code=record.constraint_code,
            description=record.description,
            category=None if record.category_id is None else categories.get(record.category_id),
            status=record.lifecycle_state,
            date_identified=record.date_identified,
            due_date=record.due_date,
            bic=bic,
            responsible=responsible,
            reference=record.reference,
            days_elapsed=_days_elapsed(record.date_identified, today),
            version=record.version,
            updated_at=record.updated_at,
            is_overdue=_is_overdue(record, today),
            is_due_soon=_is_due_soon(record, today),
            in_my_court=in_my_court(
                record.lifecycle_state,
                party_refs_of(party_rows, _BIC_ROLE),
                principal_bound_entity_ids=frozenset(),
            ),
            record_quality=record.record_quality,
            needs_attention=attention.needs_attention,
            sync_state=_sync_state(record, sync),
            group_keys=_group_keys(record, grouping, bic, responsible),
        )


# --- pure projection helpers ------------------------------------------------


def _category_view(row: ConstraintCategoryRow) -> ConstraintCategoryView:
    return ConstraintCategoryView(
        category_id=row.category_id,
        project_id=row.project_id,
        prefix=row.prefix,
        title=row.title,
        description=row.description,
        display_order=row.display_order,
        state=row.state,
        next_sequence=row.next_sequence,
        issued_count=row.issued_count,
        version=row.version,
        prefix_locked=row.prefix_locked_at is not None,
    )


def _party_views(
    rows: tuple[ConstraintPartyRow, ...], role: str, entity_labels: Mapping[str, str]
) -> tuple[PartyRefView, ...]:
    """Project one role's stored party rows, in ordinal order, per the identity rules.

    A PRINCIPAL party is the closed token and the backend constant label: no
    per-Principal display source exists, and no `prn_` value may appear in a
    party reference. An ENTITY party is its own identifier, labelled from the
    stored snapshot, else the same-Principal Entity name, else the preserved
    source wording, else `"Unknown"` — never the identifier itself, which shown
    as a name would read as one. An UNRESOLVED party has no identity at all.
    """
    views: list[PartyRefView] = []
    for row in sorted((row for row in rows if row.role == role), key=lambda row: row.ordinal):
        if row.party_kind is PartyKind.PRINCIPAL:
            views.append(
                PartyRefView(
                    kind=PartyKind.PRINCIPAL,
                    party_ref_id=PRINCIPAL_PARTY_REF,
                    display_label=PRINCIPAL_DISPLAY_LABEL,
                )
            )
            continue
        if row.party_kind is PartyKind.ENTITY and row.entity_id is not None:
            label = (
                row.display_label
                or entity_labels.get(row.entity_id)
                or row.original_label
                or UNKNOWN_DISPLAY_LABEL
            )
            views.append(
                PartyRefView(
                    kind=PartyKind.ENTITY,
                    party_ref_id=row.entity_id,
                    display_label=label,
                    entity_id=row.entity_id,
                )
            )
            continue
        views.append(
            PartyRefView(
                kind=PartyKind.UNRESOLVED,
                party_ref_id=None,
                display_label=row.display_label or row.original_label or UNKNOWN_DISPLAY_LABEL,
            )
        )
    return tuple(views)


def _group_keys(
    record: PersistedConstraintRecord,
    grouping: ConstraintGrouping,
    bic: tuple[PartyRefView, ...],
    responsible: tuple[PartyRefView, ...],
) -> tuple[str, ...]:
    """This row's stable membership under `grouping`.

    Single-valued for Category and Status; zero, one or many for the two party
    groupings, because a Constraint can be waiting on several parties and the
    accepted contract does not say which of them owns the row. The row is
    returned once whatever its membership, and no group total accompanies it.
    """
    if grouping is ConstraintGrouping.CATEGORY:
        return () if record.category_id is None else (record.category_id,)
    if grouping is ConstraintGrouping.STATUS:
        return (record.lifecycle_state.value,)
    if grouping is ConstraintGrouping.BIC:
        return tuple(view.party_ref_id for view in bic if view.party_ref_id is not None)
    if grouping is ConstraintGrouping.RESPONSIBLE:
        return tuple(view.party_ref_id for view in responsible if view.party_ref_id is not None)
    return ()


def _days_elapsed(date_identified: date | None, today: date | None) -> int | None:
    """Inclusive working days since Date Identified, or `None` when either is unknown."""
    if date_identified is None or today is None:
        return None
    return business_days_elapsed(date_identified, today)


def _is_overdue(record: PersistedConstraintRecord, today: date | None) -> bool:
    if today is None:
        return False
    return is_overdue(record.lifecycle_state, record.due_date, today)


def _is_due_soon(record: PersistedConstraintRecord, today: date | None) -> bool:
    if today is None:
        return False
    return is_due_soon(record.lifecycle_state, record.due_date, today)


def _sync_state(
    record: PersistedConstraintRecord, sync: ConstraintSyncFacts
) -> ConstraintSyncStateView:
    """The one sync state persisted rows can prove for this Constraint.

    Conflict first, because an open conflict outranks any baseline comparison;
    then the baseline, whose version either matches the Constraint's or is
    behind it. No target and no baseline mean never synced. The six frontend
    names that need a connector, a workbook, or a live run are not reachable
    from here at all — they have no member to be assigned to.
    """
    if sync.open_conflict_counts.get(record.constraint_id, 0) > 0:
        return ConstraintSyncStateView.CONFLICT
    baseline = sync.baseline_versions.get(record.constraint_id)
    if not sync.has_target or baseline is None:
        return ConstraintSyncStateView.NEVER_SYNCED
    if record.version > baseline:
        return ConstraintSyncStateView.DB_EXPORT_PENDING
    return ConstraintSyncStateView.IN_SYNC


def _sort_key(
    record: PersistedConstraintRecord,
    query: ConstraintListQuery,
    categories: Mapping[str, ConstraintCategoryRow],
) -> tuple[str | int | None, ...]:
    """The keyset anchor for the last row of a page, under the active sort.

    **An anchor carries the whole ordering key, minus the `constraint_id`
    tie-breaker the cursor holds beside it.** An anchor narrower than its own
    `ORDER BY` does not name a unique position: two Categories can allocate the
    same sequence numbers under different prefixes, so a Code anchor of
    `(length, sequence)` alone would be ambiguous at a Category boundary and a
    continuation from it could skip or repeat rows. The Code anchor is therefore
    the full `(display_order, prefix, length(sequence), sequence)` that §F.7
    orders by, taken from the Category list the page already loaded rather than
    from a statement of its own.

    Every anchor leads with an explicit null discriminator — `0` for a row that
    has the sort key, `1` for one that does not — so that `NULLS LAST` is a
    value in the tuple rather than a convention the comparison has to remember,
    and so that a missing key is never stood in for by a sentinel that real data
    could collide with. Each remaining component is `None` when the key is
    absent.

    Rendered as JSON scalars so the cursor carries the position and not a Python
    value. `DAYS_ELAPSED` anchors on `date_identified` because it is a monotonic
    function of it for a fixed `project_today`, which is what lets the adapter
    order it in SQL rather than sorting a fetched list.
    """
    if query.sort is ConstraintSort.CODE:
        category = None if record.category_id is None else categories.get(record.category_id)
        code = record.constraint_code
        if code is None or category is None:
            return (_KEY_ABSENT, None, None, None, None)
        sequence = code.rpartition(".")[2]
        return (_KEY_PRESENT, category.display_order, category.prefix, len(sequence), sequence)
    if query.sort in (ConstraintSort.DATE_IDENTIFIED, ConstraintSort.DAYS_ELAPSED):
        return _nullable_anchor(
            None if record.date_identified is None else record.date_identified.isoformat()
        )
    if query.sort is ConstraintSort.DUE_DATE:
        return _nullable_anchor(None if record.due_date is None else record.due_date.isoformat())
    # `updated_at` is `NOT NULL`, so the discriminator is always "present"; it is
    # carried anyway so every anchor has the same shape as its own sort key.
    return (_KEY_PRESENT, record.updated_at.isoformat())


def _nullable_anchor(value: str | None) -> tuple[str | int | None, ...]:
    """One nullable sort key as a discriminator and its value."""
    if value is None:
        return (_KEY_ABSENT, None)
    return (_KEY_PRESENT, value)


def _project_today(as_of: datetime, settings: ConstraintProjectSettings) -> date:
    """The Project's calendar date, or an unavailable answer. Never a guess."""
    try:
        return project_today(as_of, settings.timezone_name)
    except ProjectTimezoneError as error:
        raise UnavailableError(SafeDetail.PROJECT_ID) from error


def _decode_cursor(token: str | None, binding: str) -> ConstraintListCursor | None:
    """Read a continuation token, or refuse it in the way its failure deserves.

    A token that cannot be read at all is an invalid request; one that reads but
    was issued for a different Principal, Project, filter set, sort or limit is
    a conflict. Neither silently restarts the listing, and neither says whether
    the anchor row exists, belongs elsewhere, or is gone.
    """
    if token is None:
        return None
    try:
        cursor = ConstraintListCursor.decode(token)
    except ConstraintCursorError as error:
        raise InvalidRequestError(SafeDetail.CURSOR) from error
    if not cursor.is_bound_to(binding):
        raise ConflictError(SafeDetail.CURSOR)
    return cursor


def _history_binding(principal_id: str, constraint_id: str, page_size: int) -> str:
    """What a history cursor must carry to belong to this request.

    The Principal and the Constraint are inside the digest, so a token issued
    for one Constraint's ledger cannot be replayed against another's, or against
    the same one under another partition, without failing to validate.
    """
    payload = json.dumps(
        {
            "constraint_id": constraint_id,
            "order": _HISTORY_ORDER,
            "page_size": page_size,
            "principal_id": principal_id,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _encode_history_cursor(binding: str, position: ConstraintHistoryPosition) -> str:
    """One opaque, URL-safe continuation token for a history page."""
    payload = json.dumps(
        {
            "b": binding,
            "i": position.history_id,
            "t": position.occurred_at.isoformat(),
            "v": 1,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return base64.urlsafe_b64encode(payload.encode("ascii")).decode("ascii").rstrip("=")


def _decode_history_cursor(token: str, binding: str) -> ConstraintHistoryPosition:
    """Read a history continuation token, or refuse it as its failure deserves.

    Unreadable is an invalid request; readable but issued for another
    Constraint, Principal, or page size is a conflict. The two are distinguished
    because they mean different things to a caller holding a stale token, and
    neither reveals anything about the anchor row.
    """
    decoded = _read_history_payload(token)
    if decoded is None:
        raise InvalidRequestError(SafeDetail.CURSOR)
    if decoded["b"] != binding:
        raise ConflictError(SafeDetail.CURSOR)
    position: ConstraintHistoryPosition | None = None
    try:
        position = ConstraintHistoryPosition(
            occurred_at=ensure_utc(datetime.fromisoformat(decoded["t"])),
            history_id=decoded["i"],
        )
    except (InvalidIdentifierError, TypeError, ValueError, OverflowError):
        position = None
    if position is None:
        # Raised outside the handler so the original, which may render the
        # rejected identifier or timestamp, is not left in `__context__`.
        raise InvalidRequestError(SafeDetail.CURSOR)
    return position


def _read_history_payload(token: str) -> dict[str, Any] | None:
    """The decoding half of `_decode_history_cursor`, which raises nothing."""
    if not token or len(token) > MAX_CURSOR_CHARACTERS:
        return None
    padded = token + "=" * (-len(token) % 4)
    try:
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(decoded, dict) or set(decoded) != {"b", "i", "t", "v"}:
        return None
    if decoded["v"] != 1:
        return None
    if not all(isinstance(decoded[key], str) for key in ("b", "i", "t")):
        return None
    payload: dict[str, Any] = decoded
    return payload
