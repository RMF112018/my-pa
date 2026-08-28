"""Authoritative, bounded history of one entity's identity.

History is a projection over the ledgers that made the changes.  It does not
reconstruct snapshots those ledgers never stored: direct mutations expose their
exact recorded before/after objects, while governed identity operations expose
their ordered, digest-bound effects.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "IdentityHistoryChange",
    "IdentityHistoryCursorError",
    "IdentityHistoryEntry",
    "IdentityHistoryOperation",
    "IdentityHistoryPage",
    "IdentityHistoryPosition",
    "IdentityHistorySource",
]


class IdentityHistoryCursorError(ValueError):
    """A continuation does not name a position in this entity's history."""


class IdentityHistorySource(StrEnum):
    """Which authoritative ledger supplied one entry."""

    DIRECT_MUTATION = "direct_mutation"
    IDENTITY_OPERATION = "identity_operation"
    LEGACY_MERGE = "legacy_merge"


class IdentityHistoryOperation(StrEnum):
    """Identity-changing acts admitted by the current and forthcoming planes."""

    CREATE = "entities.create"
    UPDATE = "entities.update"
    ARCHIVE = "entities.archive"
    RESTORE = "entities.restore"
    IDENTIFIER_BIND = "entities.identifiers.bind"
    IDENTIFIER_RETIRE = "entities.identifiers.retire"
    IDENTIFIER_SUPERSEDE = "entities.identifiers.supersede"
    ALIAS_ADD = "entities.aliases.add"
    ALIAS_RETIRE = "entities.aliases.retire"
    ALIAS_SUPERSEDE = "entities.aliases.supersede"
    MERGE = "merge"
    SPLIT = "split"


@dataclass(frozen=True, slots=True)
class IdentityHistoryChange:
    """One exact ledger change belonging to a history entry."""

    family: str
    record_id: str
    effect_kind: str
    before_state: Mapping[str, object] | None = field(default=None, repr=False)
    after_state: Mapping[str, object] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.family.strip() or not self.effect_kind.strip():
            raise ValueError("an identity history change has a family and an effect kind")
        validate_identifier(self.record_id)
        for state in (self.before_state, self.after_state):
            if state is not None and not isinstance(state, Mapping):
                raise ValueError("an identity history state is an object when present")


@dataclass(frozen=True, slots=True)
class IdentityHistoryEntry:
    """One direct mutation or completed governed identity operation."""

    history_id: str
    occurred_at: datetime
    source: IdentityHistorySource
    operation: IdentityHistoryOperation
    involved_entity_ids: tuple[str, ...]
    changes: tuple[IdentityHistoryChange, ...]
    actor_class: str | None
    actor_id: str | None = None
    authority: str | None = None
    correlation_id: str | None = None
    audit_id: str | None = None
    reason: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        validate_identifier(self.history_id)
        ensure_utc(self.occurred_at)
        if not isinstance(self.source, IdentityHistorySource):
            raise ValueError("an identity history entry has a closed source")
        if not isinstance(self.operation, IdentityHistoryOperation):
            raise ValueError("an identity history entry has a closed operation")
        if not self.involved_entity_ids:
            raise ValueError("an identity history entry names an involved entity")
        for entity_id in self.involved_entity_ids:
            validate_identifier(entity_id, IdKind.ENTITY)
        if len(set(self.involved_entity_ids)) != len(self.involved_entity_ids):
            raise ValueError("an identity history entry names each entity once")
        if self.actor_class is not None and not self.actor_class.strip():
            raise ValueError("an identity history entry names an actor class")
        if self.actor_id is not None and not self.actor_id.strip():
            raise ValueError("an identity history entry names a non-blank actor")
        if self.reason is not None and not self.reason.strip():
            raise ValueError("an identity history reason is not blank")


@dataclass(frozen=True, slots=True)
class IdentityHistoryPosition:
    """The decoded complete keyset of the last entry on a page."""

    occurred_at: datetime
    source_order: int
    history_id: str

    def __post_init__(self) -> None:
        ensure_utc(self.occurred_at)
        if self.source_order not in (1, 2, 3):
            raise ValueError("an identity history position has a known source order")
        validate_identifier(self.history_id)


@dataclass(frozen=True, slots=True)
class IdentityHistoryPage:
    """One bounded chronological page and its opaque continuation."""

    entity_id: str
    entries: tuple[IdentityHistoryEntry, ...]
    is_truncated: bool
    next_cursor: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        validate_identifier(self.entity_id, IdKind.ENTITY)
        if self.is_truncated != (self.next_cursor is not None):
            raise ValueError("a truncated identity history page alone has a continuation")
