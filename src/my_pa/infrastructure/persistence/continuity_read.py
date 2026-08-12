"""Principal-scoped complete continuity read model for the web workspace."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Table, select
from sqlalchemy.engine import Connection, Row
from sqlalchemy.sql.elements import ColumnElement

from my_pa.contracts.ports import ContinuityReadRepository
from my_pa.domain.relationship.event import RelationshipEvent
from my_pa.domain.situation.continuity import (
    Commitment,
    ContinuityEvidenceState,
    Decision,
    Task,
)
from my_pa.domain.situation.situation import Frame, Trace
from my_pa.infrastructure.persistence.principal_scope import capture_context, partition_criterion
from my_pa.infrastructure.persistence.situation_repository import (
    SqlContinuityRepository,
    SqlFrameRepository,
    SqlRelationshipEventRepository,
    SqlTraceRepository,
)
from my_pa.infrastructure.persistence.tables import (
    commitments,
    decisions,
    frames,
    relationship_events,
    tasks,
    traces,
)

__all__ = ["SqlContinuityReadRepository"]


class SqlContinuityReadRepository(ContinuityReadRepository):
    """Read accepted state only, applying the shared partition guard per table."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def _rows(
        self, principal_id: str, table: Table, *criteria: ColumnElement[bool]
    ) -> list[Row[Any]]:
        context = capture_context(principal_id)
        return list(
            self._connection.execute(
                select(*table.c)
                .where(partition_criterion(table, context), *criteria)
                .order_by(*table.primary_key.columns)
            ).all()
        )

    def frames(self, principal_id: str) -> tuple[Frame, ...]:
        return tuple(SqlFrameRepository._to_frame(row) for row in self._rows(principal_id, frames))

    def traces(self, principal_id: str) -> tuple[Trace, ...]:
        return tuple(SqlTraceRepository._to_trace(row) for row in self._rows(principal_id, traces))

    def commitments(self, principal_id: str) -> tuple[Commitment, ...]:
        rows = self._rows(
            principal_id,
            commitments,
            commitments.c.evidence_state == ContinuityEvidenceState.ACCEPTED.value,
        )
        return tuple(SqlContinuityRepository._to_commitment(row) for row in rows)

    def decisions(self, principal_id: str) -> tuple[Decision, ...]:
        rows = self._rows(
            principal_id,
            decisions,
            decisions.c.evidence_state == ContinuityEvidenceState.ACCEPTED.value,
        )
        return tuple(SqlContinuityRepository._to_decision(row) for row in rows)

    def tasks(self, principal_id: str) -> tuple[Task, ...]:
        rows = self._rows(
            principal_id,
            tasks,
            tasks.c.evidence_state == ContinuityEvidenceState.ACCEPTED.value,
        )
        return tuple(SqlContinuityRepository._to_task(row) for row in rows)

    def relationship_events(self, principal_id: str) -> tuple[RelationshipEvent, ...]:
        rows = self._rows(
            principal_id, relationship_events, relationship_events.c.accepted.is_(True)
        )
        return tuple(SqlRelationshipEventRepository._to_event(row) for row in rows)
