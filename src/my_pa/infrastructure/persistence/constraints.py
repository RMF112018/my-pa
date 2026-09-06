"""The Constraint Management tables, behind `contracts.ports.ConstraintManagementRepository`.

PC-CM-IMP-WP02. Eight of the fourteen tables §C declares have a concrete caller
in this work package and are reached here: `constraint_project_settings`,
`constraint_categories`, `project_constraints`, `project_constraint_parties`,
`project_constraint_revisions`, `project_constraint_revision_parties`,
`project_constraint_history` and `constraint_category_history`. The relationship,
evidence-link and four sync tables have no caller before WP06/WP11 and are
deliberately not reachable from here at all: a writer with no service behind it
is a surface, not a seam.

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
from contextlib import AbstractContextManager
from types import TracebackType
from typing import Any, Final

from sqlalchemy import ColumnElement, Engine, Table, asc, delete, insert, select, update
from sqlalchemy.engine import Connection, Row

from my_pa.contracts.ports import (
    ConstraintManagementRepository,
    ConstraintManagementUnitOfWork,
)
from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.project_controls.category import ConstraintCategory, ConstraintCategoryState
from my_pa.domain.project_controls.constraint import (
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
from my_pa.domain.project_controls.revision import ConstraintRevision
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    partition_criterion,
    principal_bound_values,
    principal_scoped,
)
from my_pa.infrastructure.persistence.tables import (
    constraint_categories,
    constraint_category_history,
    constraint_project_settings,
    project_constraint_history,
    project_constraint_parties,
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
