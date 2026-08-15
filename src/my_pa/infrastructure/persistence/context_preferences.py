"""Append-only retrieval preferences and their current projection.

Events are never deleted. The unique key `(principal_id, idempotency_key)` is
reserved first under `ON CONFLICT DO NOTHING`. Same key and same payload
replays; same key and a different payload conflicts. The current projection is
folded in the same transaction.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from my_pa.contracts.ports import (
    ContextPreferenceRepository,
    PreferenceConflictError,
    RepositoryFailureError,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.context.preference import (
    ContextPreferenceAction,
    ContextPreferenceAdmission,
    ContextPreferenceClass,
    ContextPreferenceCurrent,
    ContextPreferenceEvent,
    preference_class_for,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.tables import (
    context_preference_current,
    context_preference_events,
)

__all__ = ["SqlContextPreferenceRepository"]

_FOCUS_ACTIONS: frozenset[str] = frozenset({"pin", "unpin"})
_RELEVANCE_ACTIONS: frozenset[str] = frozenset({"mark_relevant", "mark_irrelevant"})
_ALIAS_ACTIONS: frozenset[str] = frozenset({"confirm_alias", "remove_alias"})
_SOURCE_ACTIONS: frozenset[str] = frozenset({"prefer_source", "deprefer_source"})


def _payload_matches(
    stored: ContextPreferenceEvent,
    *,
    action: str,
    target_id: str,
    alias: str | None,
    source_id: str | None,
) -> bool:
    return (
        stored.action.value == action
        and stored.target_id == target_id
        and stored.alias == alias
        and stored.source_id == source_id
    )


def _event_from_row(row: object) -> ContextPreferenceEvent:
    mapping = row._mapping  # type: ignore[attr-defined]
    return ContextPreferenceEvent(
        event_id=str(mapping["event_id"]),
        principal_id=str(mapping["principal_id"]),
        action=ContextPreferenceAction(str(mapping["action"])),
        target_id=str(mapping["target_id"]),
        idempotency_key=str(mapping["idempotency_key"]),
        event_number=int(mapping["event_number"]),
        created_at=mapping["created_at"],
        correlation_id=str(mapping["correlation_id"]),
        request_id=str(mapping["request_id"]),
        alias=None if mapping["alias"] is None else str(mapping["alias"]),
        source_id=None if mapping["source_id"] is None else str(mapping["source_id"]),
        superseded_at=mapping["superseded_at"],
        audit_id=None if mapping["audit_id"] is None else str(mapping["audit_id"]),
    )


def _current_from_row(row: object) -> ContextPreferenceCurrent:
    mapping = row._mapping  # type: ignore[attr-defined]
    return ContextPreferenceCurrent(
        principal_id=str(mapping["principal_id"]),
        target_id=str(mapping["target_id"]),
        preference_class=ContextPreferenceClass(str(mapping["preference_class"])),
        action=ContextPreferenceAction(str(mapping["action"])),
        event_id=str(mapping["event_id"]),
        alias=None if mapping["alias"] is None else str(mapping["alias"]),
        source_id=None if mapping["source_id"] is None else str(mapping["source_id"]),
    )


class SqlContextPreferenceRepository(ContextPreferenceRepository):
    """Preference events and projection on the caller's connection."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def current_for(self, principal_id: str) -> tuple[ContextPreferenceCurrent, ...]:
        try:
            rows = self._connection.execute(
                select(*context_preference_current.c)
                .where(context_preference_current.c.principal_id == principal_id)
                .order_by(
                    context_preference_current.c.target_id,
                    context_preference_current.c.preference_class,
                )
            ).all()
        except SQLAlchemyError:
            failure = RepositoryFailureError("the request could not be completed")
            raise failure from None
        return tuple(_current_from_row(row) for row in rows)

    def record(
        self,
        *,
        principal_id: str,
        action: str,
        target_id: str,
        idempotency_key: str,
        alias: str | None,
        source_id: str | None,
        correlation_id: str,
        request_id: str,
        audit_id: str | None,
        created_at: datetime,
    ) -> ContextPreferenceAdmission:
        try:
            return self._record(
                principal_id=principal_id,
                action=action,
                target_id=target_id,
                idempotency_key=idempotency_key,
                alias=alias,
                source_id=source_id,
                correlation_id=correlation_id,
                request_id=request_id,
                audit_id=audit_id,
                created_at=created_at,
            )
        except PreferenceConflictError:
            raise
        except SQLAlchemyError:
            failure = RepositoryFailureError("the request could not be completed")
            raise failure from None

    def _record(
        self,
        *,
        principal_id: str,
        action: str,
        target_id: str,
        idempotency_key: str,
        alias: str | None,
        source_id: str | None,
        correlation_id: str,
        request_id: str,
        audit_id: str | None,
        created_at: datetime,
    ) -> ContextPreferenceAdmission:
        prior = self._event_for(principal_id, idempotency_key)
        if prior is not None:
            if not _payload_matches(
                prior, action=action, target_id=target_id, alias=alias, source_id=source_id
            ):
                raise PreferenceConflictError("the idempotency key is bound to a different request")
            return ContextPreferenceAdmission(
                event=prior,
                current=self._current_for_target(principal_id, target_id),
                created=False,
            )

        event_id = issue_identifier(IdKind.CONTEXT_PREFERENCE_EVENT)
        next_number = self._next_event_number(principal_id)
        inserted = self._connection.execute(
            pg_insert(context_preference_events)
            .values(
                event_id=event_id,
                principal_id=principal_id,
                action=action,
                target_id=target_id,
                alias=alias,
                source_id=source_id,
                idempotency_key=idempotency_key,
                event_number=next_number,
                created_at=created_at,
                superseded_at=None,
                correlation_id=correlation_id,
                audit_id=audit_id,
                request_id=request_id,
            )
            .on_conflict_do_nothing(constraint="one_preference_key_per_principal")
            .returning(context_preference_events.c.event_id)
        ).first()
        if inserted is None:
            stored = self._event_for(principal_id, idempotency_key)
            if stored is None:
                raise RepositoryFailureError("the request could not be completed")
            if not _payload_matches(
                stored, action=action, target_id=target_id, alias=alias, source_id=source_id
            ):
                raise PreferenceConflictError("the idempotency key is bound to a different request")
            return ContextPreferenceAdmission(
                event=stored,
                current=self._current_for_target(principal_id, target_id),
                created=False,
            )

        event = self._event_for(principal_id, idempotency_key)
        if event is None:
            raise RepositoryFailureError("the request could not be completed")
        self._fold(event)
        return ContextPreferenceAdmission(
            event=event,
            current=self._current_for_target(principal_id, target_id),
            created=True,
        )

    def _event_for(self, principal_id: str, idempotency_key: str) -> ContextPreferenceEvent | None:
        row = self._connection.execute(
            select(*context_preference_events.c).where(
                context_preference_events.c.principal_id == principal_id,
                context_preference_events.c.idempotency_key == idempotency_key,
            )
        ).one_or_none()
        if row is None:
            return None
        return _event_from_row(row)

    def _next_event_number(self, principal_id: str) -> int:
        current = self._connection.execute(
            select(func.coalesce(func.max(context_preference_events.c.event_number), 0)).where(
                context_preference_events.c.principal_id == principal_id
            )
        ).scalar_one()
        return int(current) + 1

    def _current_for_target(
        self, principal_id: str, target_id: str
    ) -> tuple[ContextPreferenceCurrent, ...]:
        rows = self._connection.execute(
            select(*context_preference_current.c)
            .where(
                context_preference_current.c.principal_id == principal_id,
                context_preference_current.c.target_id == target_id,
            )
            .order_by(context_preference_current.c.preference_class)
        ).all()
        return tuple(_current_from_row(row) for row in rows)

    def _fold(self, event: ContextPreferenceEvent) -> None:
        slot = preference_class_for(event.action)
        if event.action is ContextPreferenceAction.CLEAR or slot is None:
            self._supersede(event, actions=None)
            self._connection.execute(
                context_preference_current.delete().where(
                    context_preference_current.c.principal_id == event.principal_id,
                    context_preference_current.c.target_id == event.target_id,
                )
            )
            return
        self._supersede(event, actions=_actions_for(slot))
        if event.action in {
            ContextPreferenceAction.UNPIN,
            ContextPreferenceAction.REMOVE_ALIAS,
            ContextPreferenceAction.DEPREFER_SOURCE,
        }:
            self._connection.execute(
                context_preference_current.delete().where(
                    context_preference_current.c.principal_id == event.principal_id,
                    context_preference_current.c.target_id == event.target_id,
                    context_preference_current.c.preference_class == slot.value,
                )
            )
            return
        self._connection.execute(
            pg_insert(context_preference_current)
            .values(
                principal_id=event.principal_id,
                target_id=event.target_id,
                preference_class=slot.value,
                action=event.action.value,
                event_id=event.event_id,
                alias=event.alias,
                source_id=event.source_id,
            )
            .on_conflict_do_update(
                constraint="one_current_preference_per_target_class",
                set_={
                    "action": event.action.value,
                    "event_id": event.event_id,
                    "alias": event.alias,
                    "source_id": event.source_id,
                },
            )
        )

    def _supersede(self, event: ContextPreferenceEvent, *, actions: frozenset[str] | None) -> None:
        condition = [
            context_preference_events.c.principal_id == event.principal_id,
            context_preference_events.c.target_id == event.target_id,
            context_preference_events.c.superseded_at.is_(None),
            context_preference_events.c.event_id != event.event_id,
        ]
        if actions is not None:
            condition.append(context_preference_events.c.action.in_(actions))
        self._connection.execute(
            update(context_preference_events)
            .where(*condition)
            .values(superseded_at=event.created_at)
        )


def _actions_for(slot: ContextPreferenceClass) -> frozenset[str]:
    if slot is ContextPreferenceClass.FOCUS:
        return _FOCUS_ACTIONS
    if slot is ContextPreferenceClass.RELEVANCE:
        return _RELEVANCE_ACTIONS
    if slot is ContextPreferenceClass.ALIAS:
        return _ALIAS_ACTIONS
    return _SOURCE_ACTIONS
