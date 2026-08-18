"""Assemble the bounded context card for one entity.

Five reads through the same port, bounded per collection, with every bound that
bit reported. It writes nothing and decides nothing: the card is what is
recorded, not a view about it.

**Why the bound is applied here and not in the repository.** The repository
answers "what is recorded"; deciding how much of that a card carries is a
product judgement, and putting it behind the port would mean a caller who wanted
all of it had no way to ask. Whether such a caller should exist is a later
question; hiding the choice in a SQL `LIMIT` would answer it by accident.
"""

from __future__ import annotations

from my_pa.contracts.ports import EntitiesRepository
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.relationship.context_card import (
    CONTEXT_CARD_COLLECTION_LIMIT,
    ContextCardLimitation,
    EntityContextCard,
)

__all__ = ["EntityContextService"]


class EntityContextService:
    """Builds one entity's context card from the records around it."""

    def __init__(self, entities: EntitiesRepository) -> None:
        self._entities = entities

    def card(self, principal_id: str, entity_id: str) -> EntityContextCard | None:
        """The card, or `None` when the Principal holds no such entity.

        `None` rather than an empty card, for the reason `get` answers `None`: a
        card for an entity that does not exist would be a card asserting that it
        does.
        """
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(entity_id, IdKind.ENTITY)
        entity = self._entities.get(principal_id, entity_id)
        if entity is None:
            return None

        aliases, alias_limit = _bounded(self._entities.aliases(principal_id, entity_id))
        identifiers, identifier_limit = _bounded(
            self._entities.external_identifiers(principal_id, entity_id)
        )
        assignments, assignment_limit = _bounded(
            self._entities.assignments(principal_id, entity_id, active_only=False)
        )
        relationships, relationship_limit = _bounded(
            self._entities.relationships(principal_id, entity_id, direction="any")
        )

        limitations = tuple(
            limitation
            for limitation, applied in (
                (ContextCardLimitation.MORE_ALIASES_THAN_THIS_CARD_CARRIES, alias_limit),
                (
                    ContextCardLimitation.MORE_IDENTIFIERS_THAN_THIS_CARD_CARRIES,
                    identifier_limit,
                ),
                (
                    ContextCardLimitation.MORE_ASSIGNMENTS_THAN_THIS_CARD_CARRIES,
                    assignment_limit,
                ),
                (
                    ContextCardLimitation.MORE_RELATIONSHIPS_THAN_THIS_CARD_CARRIES,
                    relationship_limit,
                ),
            )
            if applied
        )
        return EntityContextCard(
            entity=entity,
            aliases=tuple(aliases),
            identifiers=tuple(identifiers),
            assignments=tuple(assignments),
            relationships=tuple(relationships),
            limitations=limitations,
        )


def _bounded[RecordT](records: list[RecordT]) -> tuple[list[RecordT], bool]:
    """The first `CONTEXT_CARD_COLLECTION_LIMIT` records, and whether that bit."""
    kept = records[:CONTEXT_CARD_COLLECTION_LIMIT]
    return kept, len(kept) < len(records)
