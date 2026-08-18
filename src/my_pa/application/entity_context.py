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

from collections import Counter
from datetime import datetime

from my_pa.contracts.ports import EntitiesRepository
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.relationship.context_card import (
    CONTEXT_CARD_COLLECTION_LIMIT,
    ContextCardCoverage,
    ContextCardLimitation,
    EntityContextCard,
)
from my_pa.domain.relationship.governance import EntityObservation

__all__ = ["EntityContextService"]


class EntityContextService:
    """Builds one entity's context card from the records around it."""

    def __init__(self, entities: EntitiesRepository) -> None:
        self._entities = entities

    def card(
        self, principal_id: str, entity_id: str, *, assembled_at: datetime
    ) -> EntityContextCard | None:
        """The card, or `None` when the Principal holds no such entity.

        `None` rather than an empty card, for the reason `get` answers `None`: a
        card for an entity that does not exist would be a card asserting that it
        does.

        `assembled_at` is passed in rather than read from a clock here, because
        a card is a *generated* artefact and section 26.3 asks it to carry its
        generation identity — which means the moment has to come from whatever
        is generating it, not from a call this module makes on its own.
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
        every_observation = self._entities.observations(principal_id, entity_id)
        observations, observation_limit = _bounded(every_observation)

        # Coverage is computed over *every* observation, not the bounded page:
        # "four sources contributed" is a fact about the evidence, and reporting
        # it from a truncated sample would understate it exactly when the card
        # is most crowded.
        coverage = _coverage(every_observation)

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
                (
                    ContextCardLimitation.MORE_OBSERVATIONS_THAN_THIS_CARD_CARRIES,
                    observation_limit,
                ),
                (ContextCardLimitation.NO_SOURCE_HAS_BEEN_OBSERVED, not coverage),
            )
            if applied
        )
        return EntityContextCard(
            entity=entity,
            assembled_at=assembled_at,
            aliases=tuple(aliases),
            identifiers=tuple(identifiers),
            assignments=tuple(assignments),
            relationships=tuple(relationships),
            observations=tuple(observations),
            coverage=coverage,
            limitations=limitations,
        )


def _bounded[RecordT](records: list[RecordT]) -> tuple[list[RecordT], bool]:
    """The first `CONTEXT_CARD_COLLECTION_LIMIT` records, and whether that bit."""
    kept = records[:CONTEXT_CARD_COLLECTION_LIMIT]
    return kept, len(kept) < len(records)


def _coverage(observations: list[EntityObservation]) -> tuple[ContextCardCoverage, ...]:
    """What each source contributed, newest-first by its most recent observation.

    Ordered so the freshest source leads, because a reader scanning coverage is
    usually asking "how current is this" before "how much is there".
    """
    counts: Counter[str] = Counter()
    latest: dict[str, datetime] = {}
    for observation in observations:
        counts[observation.source_id] += 1
        seen = latest.get(observation.source_id)
        if seen is None or observation.observed_at > seen:
            latest[observation.source_id] = observation.observed_at
    return tuple(
        sorted(
            (
                ContextCardCoverage(
                    source_id=source_id,
                    observation_count=counts[source_id],
                    most_recent_observation_at=latest[source_id],
                )
                for source_id in counts
            ),
            key=lambda entry: (-entry.most_recent_observation_at.timestamp(), entry.source_id),
        )
    )
