"""`knowledge.commitments`/`knowledge.commitment_history`, behind
`contracts.ports.CommitmentManagementRepository`.

WP-TM-05. This module mirrors `infrastructure.persistence.task_management`
row-for-row, over `commitments`/`commitment_history` instead of
`tasks`/`task_history`: every statement carries `principal_id`, `get_for_update`
issues `SELECT ... FOR UPDATE` for the same reason `TaskManagementRepository`'s
own docstring gives, and there is no `state` column to derive because
`domain.task.commitment.Commitment.state` maps directly onto
`commitments.state` — unlike `Task`, no legacy dual-column mapping exists for
Commitment.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from types import TracebackType
from typing import Any

from sqlalchemy import Engine, and_, asc, desc, func, insert, or_, select, update
from sqlalchemy.engine import Connection, Row

from my_pa.contracts.ports import (
    CommitmentManagementRepository,
    CommitmentManagementUnitOfWork,
    CounterpartyOption,
    WorkCursorError,
)
from my_pa.domain.situation.continuity import (
    CommitmentDirection,
    CommitmentState,
    ContinuityEvidenceState,
)
from my_pa.domain.task.commitment import Commitment
from my_pa.domain.task.commitment_history import CommitmentHistoryEntry, CommitmentMutationAction
from my_pa.domain.task.history import TaskMutationActor
from my_pa.domain.task.history import TaskMutationOutcome as _TaskMutationOutcome
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    partition_criterion,
)
from my_pa.infrastructure.persistence.tables import (
    commitment_history,
    commitments,
    relationship_people,
)

__all__ = ["SqlAlchemyCommitmentManagementUnitOfWork", "SqlCommitmentManagementRepository"]


class SqlCommitmentManagementRepository(CommitmentManagementRepository):
    """`CommitmentManagementRepository`, over a plain SQLAlchemy Core `Connection`.

    Takes the connection rather than opening one, exactly as
    `SqlTaskManagementRepository` does: the caller owns the transaction, this
    class only issues statements on it.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get_for_update(self, principal_id: str, commitment_id: str) -> Commitment | None:
        row = self._connection.execute(
            select(*commitments.c)
            .where(
                and_(
                    commitments.c.commitment_id == commitment_id,
                    commitments.c.principal_id == principal_id,
                )
            )
            .with_for_update()
        ).one_or_none()
        return None if row is None else _to_commitment(row)

    def get(self, principal_id: str, commitment_id: str) -> Commitment | None:
        row = self._connection.execute(
            select(*commitments.c).where(
                and_(
                    commitments.c.commitment_id == commitment_id,
                    commitments.c.principal_id == principal_id,
                )
            )
        ).one_or_none()
        return None if row is None else _to_commitment(row)

    def counterparty(self, principal_id: str, person_id: str) -> CounterpartyOption | None:
        row = self._connection.execute(
            select(
                relationship_people.c.person_id,
                relationship_people.c.display_name,
            ).where(
                partition_criterion(relationship_people, capture_context(principal_id)),
                relationship_people.c.person_id == person_id,
                relationship_people.c.superseded_by_person_id.is_(None),
            )
        ).one_or_none()
        return (
            None
            if row is None
            else CounterpartyOption(
                person_id=str(row.person_id), display_name=str(row.display_name)
            )
        )

    def list_counterparties(
        self, principal_id: str, *, limit: int
    ) -> tuple[CounterpartyOption, ...]:
        rows = self._connection.execute(
            select(
                relationship_people.c.person_id,
                relationship_people.c.display_name,
            )
            .where(
                partition_criterion(relationship_people, capture_context(principal_id)),
                relationship_people.c.superseded_by_person_id.is_(None),
            )
            .order_by(
                asc(func.lower(relationship_people.c.display_name)),
                asc(relationship_people.c.person_id),
            )
            .limit(limit)
        ).all()
        return tuple(
            CounterpartyOption(person_id=str(row.person_id), display_name=str(row.display_name))
            for row in rows
        )

    def list_commitments(
        self,
        principal_id: str,
        *,
        direction: CommitmentDirection | None = None,
        state: CommitmentState | None = None,
        evidence_state: ContinuityEvidenceState | None = None,
        after: str | None = None,
        limit: int,
    ) -> tuple[Commitment, ...]:
        conditions = [commitments.c.principal_id == principal_id]
        if direction is not None:
            conditions.append(commitments.c.direction == direction.value)
        if state is not None:
            conditions.append(commitments.c.state == state.value)
        if evidence_state is not None:
            conditions.append(commitments.c.evidence_state == evidence_state.value)
        if after is not None:
            anchor = self._connection.execute(
                select(
                    commitments.c.due_at,
                    commitments.c.created_at,
                    commitments.c.commitment_id,
                ).where(and_(*conditions, commitments.c.commitment_id == after))
            ).one_or_none()
            if anchor is None:
                raise WorkCursorError
            later_created = or_(
                commitments.c.created_at < anchor.created_at,
                and_(
                    commitments.c.created_at == anchor.created_at,
                    commitments.c.commitment_id > anchor.commitment_id,
                ),
            )
            if anchor.due_at is None:
                conditions.append(and_(commitments.c.due_at.is_(None), later_created))
            else:
                conditions.append(
                    or_(
                        commitments.c.due_at > anchor.due_at,
                        commitments.c.due_at.is_(None),
                        and_(commitments.c.due_at == anchor.due_at, later_created),
                    )
                )
        rows = self._connection.execute(
            select(*commitments.c)
            .where(and_(*conditions))
            .order_by(
                asc(commitments.c.due_at).nullslast(),
                desc(commitments.c.created_at),
                asc(commitments.c.commitment_id),
            )
            .limit(limit)
        ).all()
        return tuple(_to_commitment(row) for row in rows)

    def insert_commitment(self, commitment: Commitment) -> None:
        self._connection.execute(
            insert(commitments).values(
                commitment_id=commitment.commitment_id,
                principal_id=commitment.principal_id,
                counterparty_person_id=commitment.counterparty_person_id,
                direction=commitment.direction.value,
                summary=commitment.summary,
                state=commitment.state.value,
                evidence_state=commitment.evidence_state.value,
                origin_evidence_ref=commitment.origin_evidence_ref,
                project_id=commitment.project_id,
                situation_id=commitment.situation_id,
                due_at=commitment.due_at,
                opened_at=commitment.opened_at,
                closed_at=commitment.closed_at,
                closure_evidence_ref=commitment.closure_evidence_ref,
                accepted_by_review_decision_id=commitment.accepted_by_review_decision_id,
                created_at=commitment.created_at,
                updated_at=commitment.updated_at,
                version=commitment.version,
            )
        )

    def update_commitment(self, commitment: Commitment) -> None:
        self._connection.execute(
            update(commitments)
            .where(
                and_(
                    commitments.c.commitment_id == commitment.commitment_id,
                    commitments.c.principal_id == commitment.principal_id,
                )
            )
            .values(
                counterparty_person_id=commitment.counterparty_person_id,
                direction=commitment.direction.value,
                summary=commitment.summary,
                state=commitment.state.value,
                evidence_state=commitment.evidence_state.value,
                project_id=commitment.project_id,
                situation_id=commitment.situation_id,
                due_at=commitment.due_at,
                closed_at=commitment.closed_at,
                closure_evidence_ref=commitment.closure_evidence_ref,
                accepted_by_review_decision_id=commitment.accepted_by_review_decision_id,
                updated_at=commitment.updated_at,
                version=commitment.version,
            )
        )

    def find_history_by_idempotency_key(
        self, principal_id: str, idempotency_key: str
    ) -> CommitmentHistoryEntry | None:
        row = self._connection.execute(
            select(*commitment_history.c).where(
                and_(
                    commitment_history.c.principal_id == principal_id,
                    commitment_history.c.idempotency_key == idempotency_key,
                )
            )
        ).one_or_none()
        return None if row is None else _to_history(row)

    def insert_history(self, entry: CommitmentHistoryEntry) -> None:
        self._connection.execute(
            insert(commitment_history).values(
                history_id=entry.history_id,
                principal_id=entry.principal_id,
                commitment_id=entry.commitment_id,
                action=entry.action.value,
                actor=entry.actor.value,
                outcome=entry.outcome.value,
                before_version=entry.before_version,
                after_version=entry.after_version,
                idempotency_key=entry.idempotency_key,
                client_context=entry.client_context,
                request_digest=entry.request_digest,
                occurred_at=entry.occurred_at,
                recorded_at=entry.recorded_at,
            )
        )

    def list_history(
        self, principal_id: str, commitment_id: str, limit: int, *, after: str | None = None
    ) -> tuple[CommitmentHistoryEntry, ...]:
        conditions = [
            commitment_history.c.principal_id == principal_id,
            commitment_history.c.commitment_id == commitment_id,
        ]
        if after is not None:
            anchor = self._connection.execute(
                select(commitment_history.c.recorded_at, commitment_history.c.history_id).where(
                    and_(
                        commitment_history.c.principal_id == principal_id,
                        commitment_history.c.commitment_id == commitment_id,
                        commitment_history.c.history_id == after,
                    )
                )
            ).one_or_none()
            if anchor is None:
                raise WorkCursorError
            conditions.append(
                or_(
                    commitment_history.c.recorded_at > anchor.recorded_at,
                    and_(
                        commitment_history.c.recorded_at == anchor.recorded_at,
                        commitment_history.c.history_id > anchor.history_id,
                    ),
                )
            )
        rows = self._connection.execute(
            select(*commitment_history.c)
            .where(and_(*conditions))
            .order_by(asc(commitment_history.c.recorded_at), asc(commitment_history.c.history_id))
            .limit(limit)
        ).all()
        return tuple(_to_history(row) for row in rows)

    def search(
        self,
        principal_id: str,
        query: str,
        limit: int,
        *,
        after: str | None = None,
        direction: CommitmentDirection | None = None,
        state: CommitmentState | None = None,
    ) -> tuple[Commitment, ...]:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions = [
            commitments.c.principal_id == principal_id,
            commitments.c.summary.ilike(f"%{escaped}%", escape="\\"),
        ]
        if direction is not None:
            conditions.append(commitments.c.direction == direction.value)
        if state is not None:
            conditions.append(commitments.c.state == state.value)
        if after is not None:
            anchor = self._connection.execute(
                select(
                    commitments.c.due_at,
                    commitments.c.created_at,
                    commitments.c.commitment_id,
                ).where(and_(*conditions, commitments.c.commitment_id == after))
            ).one_or_none()
            if anchor is None:
                raise WorkCursorError
            later_created = or_(
                commitments.c.created_at < anchor.created_at,
                and_(
                    commitments.c.created_at == anchor.created_at,
                    commitments.c.commitment_id > anchor.commitment_id,
                ),
            )
            if anchor.due_at is None:
                conditions.append(and_(commitments.c.due_at.is_(None), later_created))
            else:
                conditions.append(
                    or_(
                        commitments.c.due_at > anchor.due_at,
                        commitments.c.due_at.is_(None),
                        and_(commitments.c.due_at == anchor.due_at, later_created),
                    )
                )
        rows = self._connection.execute(
            select(*commitments.c)
            .where(and_(*conditions))
            .order_by(
                asc(commitments.c.due_at).nullslast(),
                desc(commitments.c.created_at),
                asc(commitments.c.commitment_id),
            )
            .limit(limit)
        ).all()
        return tuple(_to_commitment(row) for row in rows)


def _to_commitment(row: Row[Any]) -> Commitment:
    mapping = row._mapping
    return Commitment(
        commitment_id=mapping["commitment_id"],
        principal_id=mapping["principal_id"],
        counterparty_person_id=mapping["counterparty_person_id"],
        direction=CommitmentDirection(mapping["direction"]),
        summary=mapping["summary"],
        state=CommitmentState(mapping["state"]),
        evidence_state=ContinuityEvidenceState(mapping["evidence_state"]),
        origin_evidence_ref=mapping["origin_evidence_ref"],
        opened_at=mapping["opened_at"],
        created_at=mapping["created_at"],
        updated_at=mapping["updated_at"],
        version=mapping["version"],
        due_at=mapping["due_at"],
        project_id=mapping["project_id"],
        situation_id=mapping["situation_id"],
        closed_at=mapping["closed_at"],
        closure_evidence_ref=mapping["closure_evidence_ref"],
        accepted_by_review_decision_id=mapping["accepted_by_review_decision_id"],
    )


def _to_history(row: Row[Any]) -> CommitmentHistoryEntry:
    mapping = row._mapping
    return CommitmentHistoryEntry(
        history_id=mapping["history_id"],
        principal_id=mapping["principal_id"],
        commitment_id=mapping["commitment_id"],
        action=CommitmentMutationAction(mapping["action"]),
        actor=TaskMutationActor(mapping["actor"]),
        outcome=_TaskMutationOutcome(mapping["outcome"]),
        before_version=mapping["before_version"],
        after_version=mapping["after_version"],
        occurred_at=mapping["occurred_at"],
        recorded_at=mapping["recorded_at"],
        idempotency_key=mapping["idempotency_key"],
        client_context=mapping["client_context"],
        request_digest=mapping.get("request_digest"),
    )


class SqlAlchemyCommitmentManagementUnitOfWork(CommitmentManagementUnitOfWork):
    """One PostgreSQL transaction over the commitment-management tables.

    The identical shape `SqlAlchemyTaskManagementUnitOfWork` establishes.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._context: AbstractContextManager[Connection] | None = None
        self._connection: Connection | None = None

    def __enter__(self) -> CommitmentManagementUnitOfWork:
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
    def commitments(self) -> CommitmentManagementRepository:
        connection = self._connection
        if connection is None:
            raise RuntimeError("this unit of work is not inside a transaction")
        return SqlCommitmentManagementRepository(connection)
