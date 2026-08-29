"""Principal-partitioned SQL projection over authoritative identity ledgers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any, Final

from sqlalchemy import Integer, String, cast, func, literal, or_, select, tuple_, union_all
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection, Row
from sqlalchemy.sql.selectable import SelectBase

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.relationship.identity_history import (
    IdentityHistoryChange,
    IdentityHistoryCursorError,
    IdentityHistoryEntry,
    IdentityHistoryOperation,
    IdentityHistoryPosition,
    IdentityHistorySource,
)
from my_pa.infrastructure.persistence.tables import (
    entity_identity_effects,
    entity_identity_operations,
    entity_merge_records,
    entity_mutation_events,
)

__all__ = ["SqlIdentityHistoryQuery"]

_DIRECT_CAPABILITIES: Final = tuple(
    operation.value
    for operation in IdentityHistoryOperation
    if operation not in (IdentityHistoryOperation.MERGE, IdentityHistoryOperation.SPLIT)
)


class SqlIdentityHistoryQuery:
    """Read one history with partition predicates inside every UNION branch."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def entries(
        self,
        principal_id: str,
        entity_id: str,
        *,
        limit: int,
        after: IdentityHistoryPosition | None = None,
    ) -> tuple[tuple[IdentityHistoryEntry, int], ...]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(entity_id, IdKind.ENTITY)
        if limit < 1:
            raise ValueError("an identity history query returns at least one entry")
        history = self._history(principal_id, entity_id).cte("identity_history")
        if after is not None:
            anchor = self._connection.execute(
                select(history.c.history_id).where(
                    history.c.occurred_at == after.occurred_at,
                    history.c.source_order == after.source_order,
                    history.c.history_id == after.history_id,
                )
            ).scalar_one_or_none()
            if anchor is None:
                raise IdentityHistoryCursorError(
                    "an identity history cursor names no entry in this entity's history"
                )
        statement = select(history)
        if after is not None:
            statement = statement.where(
                tuple_(history.c.occurred_at, history.c.source_order, history.c.history_id)
                > tuple_(
                    literal(after.occurred_at),
                    literal(after.source_order),
                    literal(after.history_id),
                )
            )
        rows = self._connection.execute(
            statement.order_by(
                history.c.occurred_at, history.c.source_order, history.c.history_id
            ).limit(limit)
        ).all()
        operation_ids = tuple(
            str(row.history_id)
            for row in rows
            if row.source_kind == IdentityHistorySource.IDENTITY_OPERATION.value
        )
        effects = self._effects(principal_id, operation_ids)
        return tuple((self._entry(row, effects), int(row.source_order)) for row in rows)

    def _history(self, principal_id: str, entity_id: str) -> SelectBase:
        empty_object = cast(literal(None), JSONB)
        direct = select(
            entity_mutation_events.c.event_id.label("history_id"),
            entity_mutation_events.c.recorded_at.label("occurred_at"),
            literal(1, type_=Integer).label("source_order"),
            literal(IdentityHistorySource.DIRECT_MUTATION.value).label("source_kind"),
            entity_mutation_events.c.capability.label("operation_kind"),
            entity_mutation_events.c.actor_class,
            cast(literal(None), String).label("actor_id"),
            entity_mutation_events.c.authority,
            entity_mutation_events.c.correlation_id,
            entity_mutation_events.c.audit_id,
            entity_mutation_events.c.reason,
            func.jsonb_build_array(entity_mutation_events.c.after_state["entity_id"].astext).label(
                "involved_entity_ids"
            ),
            entity_mutation_events.c.record_family,
            entity_mutation_events.c.record_id,
            entity_mutation_events.c.before_state,
            entity_mutation_events.c.after_state,
            # A direct mutation predates the governed operation ledger: it
            # descends from no operation and cites no identity-operation
            # receipt. Projected as NULL rather than omitted so every branch of
            # the union states the same shape and a reader sees the absence.
            cast(literal(None), String).label("source_identity_operation_id"),
            cast(literal(None), String).label("receipt_id"),
        ).where(
            entity_mutation_events.c.principal_id == principal_id,
            entity_mutation_events.c.capability.in_(_DIRECT_CAPABILITIES),
            entity_mutation_events.c.after_state["entity_id"].astext == entity_id,
        )
        operations = select(
            entity_identity_operations.c.identity_operation_id.label("history_id"),
            entity_identity_operations.c.completed_at.label("occurred_at"),
            literal(2, type_=Integer).label("source_order"),
            literal(IdentityHistorySource.IDENTITY_OPERATION.value).label("source_kind"),
            entity_identity_operations.c.operation_type.label("operation_kind"),
            entity_identity_operations.c.actor_class,
            entity_identity_operations.c.performed_by.label("actor_id"),
            cast(literal(None), String).label("authority"),
            entity_identity_operations.c.correlation_id,
            entity_identity_operations.c.audit_id,
            entity_identity_operations.c.reason,
            (
                func.jsonb_build_array(entity_identity_operations.c.survivor_entity_id).op("||")(
                    entity_identity_operations.c.merged_entity_ids
                )
            ).label("involved_entity_ids"),
            cast(literal(None), String).label("record_family"),
            cast(literal(None), String).label("record_id"),
            empty_object.label("before_state"),
            empty_object.label("after_state"),
            # The governed lineage: which merge a split descended from, and the
            # receipt the operation was authorized under. Both are held on the
            # operation row itself, so history reads them rather than deriving
            # them.
            entity_identity_operations.c.source_identity_operation_id,
            entity_identity_operations.c.receipt_id,
        ).where(
            entity_identity_operations.c.principal_id == principal_id,
            entity_identity_operations.c.state == "completed",
            or_(
                entity_identity_operations.c.survivor_entity_id == entity_id,
                entity_identity_operations.c.merged_entity_ids.contains([entity_id]),
            ),
        )
        legacy = select(
            entity_merge_records.c.merge_id.label("history_id"),
            entity_merge_records.c.decided_at.label("occurred_at"),
            literal(3, type_=Integer).label("source_order"),
            literal(IdentityHistorySource.LEGACY_MERGE.value).label("source_kind"),
            literal(IdentityHistoryOperation.MERGE.value).label("operation_kind"),
            cast(literal(None), String).label("actor_class"),
            entity_merge_records.c.decided_by.label("actor_id"),
            cast(literal(None), String).label("authority"),
            cast(literal(None), String).label("correlation_id"),
            cast(literal(None), String).label("audit_id"),
            entity_merge_records.c.reason,
            func.jsonb_build_array(
                entity_merge_records.c.retained_entity_id,
                entity_merge_records.c.merged_entity_id,
            ).label("involved_entity_ids"),
            cast(literal(None), String).label("record_family"),
            cast(literal(None), String).label("record_id"),
            empty_object.label("before_state"),
            empty_object.label("after_state"),
            # A legacy merge is the lineage an accepted proposal left before the
            # governed operation ledger existed, so it names neither.
            cast(literal(None), String).label("source_identity_operation_id"),
            cast(literal(None), String).label("receipt_id"),
        ).where(
            entity_merge_records.c.principal_id == principal_id,
            or_(
                entity_merge_records.c.retained_entity_id == entity_id,
                entity_merge_records.c.merged_entity_id == entity_id,
            ),
        )
        return union_all(direct, operations, legacy)

    def _effects(
        self, principal_id: str, operation_ids: tuple[str, ...]
    ) -> Mapping[str, tuple[IdentityHistoryChange, ...]]:
        if not operation_ids:
            return {}
        rows = self._connection.execute(
            select(entity_identity_effects)
            .where(
                entity_identity_effects.c.principal_id == principal_id,
                entity_identity_effects.c.identity_operation_id.in_(operation_ids),
            )
            .order_by(
                entity_identity_effects.c.identity_operation_id,
                entity_identity_effects.c.sequence,
            )
        ).all()
        grouped: defaultdict[str, list[IdentityHistoryChange]] = defaultdict(list)
        for row in rows:
            grouped[str(row.identity_operation_id)].append(
                IdentityHistoryChange(
                    family=str(row.record_family),
                    record_id=str(row.record_id),
                    effect_kind=str(row.effect_kind),
                    before_state=_object(row.before_state),
                    after_state=_object(row.after_state),
                )
            )
        return {operation_id: tuple(changes) for operation_id, changes in grouped.items()}

    @staticmethod
    def _entry(
        row: Row[Any], effects: Mapping[str, tuple[IdentityHistoryChange, ...]]
    ) -> IdentityHistoryEntry:
        source = IdentityHistorySource(str(row.source_kind))
        changes = effects.get(str(row.history_id), ())
        if source is IdentityHistorySource.IDENTITY_OPERATION and not changes:
            raise ValueError("a completed identity operation has no authoritative effects")
        if source is IdentityHistorySource.DIRECT_MUTATION:
            changes = (
                IdentityHistoryChange(
                    family=str(row.record_family),
                    record_id=str(row.record_id),
                    effect_kind=str(row.operation_kind),
                    before_state=_object(row.before_state),
                    after_state=_object(row.after_state),
                ),
            )
        involved = row.involved_entity_ids if isinstance(row.involved_entity_ids, list) else []
        return IdentityHistoryEntry(
            history_id=str(row.history_id),
            occurred_at=row.occurred_at,
            source=source,
            operation=IdentityHistoryOperation(str(row.operation_kind)),
            involved_entity_ids=tuple(dict.fromkeys(str(value) for value in involved)),
            changes=changes,
            actor_class=None if row.actor_class is None else str(row.actor_class),
            actor_id=None if row.actor_id is None else str(row.actor_id),
            authority=None if row.authority is None else str(row.authority),
            correlation_id=None if row.correlation_id is None else str(row.correlation_id),
            audit_id=None if row.audit_id is None else str(row.audit_id),
            reason=None if row.reason is None else str(row.reason),
            source_identity_operation_id=(
                None
                if row.source_identity_operation_id is None
                else str(row.source_identity_operation_id)
            ),
            receipt_id=None if row.receipt_id is None else str(row.receipt_id),
        )


def _object(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, dict) else None
