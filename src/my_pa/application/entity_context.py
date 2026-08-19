"""Assemble the bounded context card for one entity.

Five reads through the same port, bounded per collection, with every bound that
bit reported. It writes nothing and decides nothing: the card is what is
recorded, not a view about it.

**Where the bound is decided, and where it is enforced.** The number is decided
here: the repository answers "what is recorded", and how much of that a card
carries is a product judgement, so `CONTEXT_CARD_COLLECTION_LIMIT` lives in the
domain and the port's own default stays unbounded -- a caller who wants every
alias must still be able to ask for every alias. What is *enforced* in the
repository is the number this module chose, as a `LIMIT` on each query.

That split is the correction `RI-PR135-MAJOR-001` asks for. This module used to
decide the bound and then apply it by slicing a list the database had already
materialized, which meant a person with four thousand recorded edges cost four
thousand rows to render a card carrying twenty-five of them: the read was
depth-bounded and card-bounded and not count-bounded, and the only one of those
three the caller could see was the last. `observations` had said so in its own
port docstring since `WP-RI-06`; the other four collections now say it too.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from my_pa.contracts.ports import EntitiesRepository
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.relationship.context_card import (
    CONTEXT_CARD_COLLECTION_LIMIT,
    CONTEXT_CARD_COVERAGE_LIMIT,
    ContextCardCoverage,
    ContextCardLimitation,
    EntityContextCard,
)
from my_pa.domain.relationship.governance import EntityObservation

__all__ = ["EntityContextService"]

#: How many rows of each collection to ask the repository for: one past what the
#: card can carry.
#:
#: The extra row is the entire truncation indicator. Asking for exactly
#: `CONTEXT_CARD_COLLECTION_LIMIT` and reporting a limitation when a full page
#: came back would state "there are more aliases than this card carries" for an
#: entity holding exactly twenty-five -- a limitation that did not apply, which
#: `EntityContextCard.__post_init__` refuses outright. Asking for one more turns
#: the claim into an observation: the overflow row either exists or it does not.
_FETCH: int = CONTEXT_CARD_COLLECTION_LIMIT + 1


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

        # Every collection is read one row past what the card can carry. The
        # extra row is what makes the limitation *provable*: `len(fetched) >
        # CONTEXT_CARD_COLLECTION_LIMIT` is the overflow itself, not an
        # inference from a full page, and no second `COUNT` is issued to learn
        # it. `EntityReenrichmentService.after_merge` uses the same trick for the
        # same reason.
        aliases, alias_limit = _bounded(
            self._entities.aliases(principal_id, entity_id, limit=_FETCH)
        )
        identifiers, identifier_limit = _bounded(
            self._entities.external_identifiers(principal_id, entity_id, limit=_FETCH)
        )
        assignments, assignment_limit = _bounded(
            self._entities.assignments(principal_id, entity_id, active_only=False, limit=_FETCH)
        )
        relationships, relationship_limit = _bounded(
            self._entities.relationships(principal_id, entity_id, direction="any", limit=_FETCH)
        )
        # One row past the ceiling, so "there are exactly this many" and "there
        # are at least this many" are distinguishable without a second query.
        counted = self._entities.observations(
            principal_id, entity_id, limit=CONTEXT_CARD_COVERAGE_LIMIT + 1
        )
        sampled = len(counted) > CONTEXT_CARD_COVERAGE_LIMIT
        counted = counted[:CONTEXT_CARD_COVERAGE_LIMIT]
        observations, observation_limit = _bounded(counted)

        # Coverage is computed over every observation the ceiling admitted, not
        # over the twenty-five the card carries: "four sources contributed" is a
        # fact about the evidence, and reporting it from the displayed page
        # would understate it exactly when the card is most crowded. When the
        # ceiling itself bit, the card says so rather than presenting a partial
        # count as a complete one.
        coverage = _coverage(counted)

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
                (ContextCardLimitation.COVERAGE_COUNTED_A_BOUNDED_SAMPLE, sampled),
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
    """The first `CONTEXT_CARD_COLLECTION_LIMIT` records, and whether that bit.

    `records` is what a `_FETCH`-bounded read returned, so the second value is
    read off the overflow row rather than inferred from a full page: it is true
    exactly when the repository had one more row than the card can carry, and
    that is a fact the query already established. Nothing here issues a second
    query to learn it, which is what `EntityReenrichmentService.after_merge`
    does and why.
    """
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
