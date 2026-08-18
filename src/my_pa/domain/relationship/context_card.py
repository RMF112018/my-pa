"""A bounded assembly of what is recorded about one entity.

The specification calls this a **context packet** (section 26.3) and asks it to
carry its purpose, its included and excluded sources, its redactions, its size
budget, its citations, and its invalidation rule.

`WP-RI-05` delivered the records, bounded, with every omission named.
`WP-RI-07` adds the half that could not exist before observations did: which
sources contributed, how many observations each supplied, and how recent the
most recent one is. `RI-AC-013` asks for coverage and freshness *before*
synthesis, and section 6.8 asks that "lack of indexed evidence must never be
presented as evidence of absence" -- so a card whose coverage is empty says so
in a field rather than by looking the same as a card nobody built.

Still absent, and named rather than implied: the disclosure route and
sensitivity classification (no model route exists to disclose to), redactions
(nothing here is redacted -- the card returns the Principal's own records to the
Principal), and the invalidation rule (there is no cache to invalidate).

**Every collection is bounded, and a bound that bit is stated.** Section 26.4
requires a partial answer not to read as a complete one, and a context card is
exactly the shape that failure takes: a caller reads "three assignments" and
concludes there are three. `limitations` is how the card says otherwise, and it
is the reason the card is a record rather than four lists.

**It holds the domain records themselves** rather than flattened copies. A
flattened copy is a second vocabulary to keep in step with the first, and the
`Entity`/`EntityAlias`/`ExternalIdentifier`/`Assignment`/`EntityRelationship`
types already carry their own invariants -- a card assembled from them cannot
contain a shape those types would refuse.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.relationship.entity import (
    Assignment,
    Entity,
    EntityAlias,
    EntityRelationship,
    ExternalIdentifier,
)
from my_pa.domain.relationship.governance import EntityObservation

__all__ = [
    "CONTEXT_CARD_COLLECTION_LIMIT",
    "ContextCardCoverage",
    "ContextCardLimitation",
    "EntityContextCard",
]

#: The most records of any one kind a card carries. Per-collection rather than
#: one budget over the whole card, because a person with forty edges and two
#: aliases should not lose the aliases to the edges.
CONTEXT_CARD_COLLECTION_LIMIT: int = 25


class ContextCardLimitation(StrEnum):
    """What the card left out, in a closed vocabulary.

    Named per collection rather than as one "truncated" flag, because "there are
    more assignments than these" and "there are more edges than these" call for
    different next requests, and a single flag would make the caller guess which.
    """

    MORE_ALIASES_THAN_THIS_CARD_CARRIES = "more_aliases_than_this_card_carries"
    MORE_IDENTIFIERS_THAN_THIS_CARD_CARRIES = "more_identifiers_than_this_card_carries"
    MORE_ASSIGNMENTS_THAN_THIS_CARD_CARRIES = "more_assignments_than_this_card_carries"
    MORE_RELATIONSHIPS_THAN_THIS_CARD_CARRIES = "more_relationships_than_this_card_carries"
    MORE_OBSERVATIONS_THAN_THIS_CARD_CARRIES = "more_observations_than_this_card_carries"
    #: No source has been observed for this entity at all. Stated rather than
    #: left as an empty coverage list, because section 6.8 refuses to let a lack
    #: of indexed evidence read as evidence of absence -- "nothing observed this
    #: person" and "nothing looked" are different, and only one of them is a
    #: fact about the person.
    NO_SOURCE_HAS_BEEN_OBSERVED = "no_source_has_been_observed"


@dataclass(frozen=True, slots=True)
class ContextCardCoverage:
    """What one source has contributed about this entity, and how recently.

    Per source rather than one total, because "forty observations, all from one
    mailbox in 2023" and "forty observations across four systems this week" are
    different pictures and a single count cannot tell them apart.
    """

    source_id: str
    observation_count: int
    most_recent_observation_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.source_id, IdKind.SOURCE)
        if self.observation_count < 1:
            raise ValueError("a coverage entry names a source that contributed something")
        ensure_utc(self.most_recent_observation_at)


@dataclass(frozen=True, slots=True)
class EntityContextCard:
    """One entity and the records around it, bounded and self-describing."""

    entity: Entity
    assembled_at: datetime
    aliases: tuple[EntityAlias, ...] = ()
    identifiers: tuple[ExternalIdentifier, ...] = ()
    assignments: tuple[Assignment, ...] = ()
    relationships: tuple[EntityRelationship, ...] = ()
    observations: tuple[EntityObservation, ...] = ()
    coverage: tuple[ContextCardCoverage, ...] = ()
    limitations: tuple[ContextCardLimitation, ...] = ()

    def __post_init__(self) -> None:
        ensure_utc(self.assembled_at)
        for collection, limitation in (
            (self.aliases, ContextCardLimitation.MORE_ALIASES_THAN_THIS_CARD_CARRIES),
            (self.identifiers, ContextCardLimitation.MORE_IDENTIFIERS_THAN_THIS_CARD_CARRIES),
            (self.assignments, ContextCardLimitation.MORE_ASSIGNMENTS_THAN_THIS_CARD_CARRIES),
            (
                self.relationships,
                ContextCardLimitation.MORE_RELATIONSHIPS_THAN_THIS_CARD_CARRIES,
            ),
            (self.observations, ContextCardLimitation.MORE_OBSERVATIONS_THAN_THIS_CARD_CARRIES),
        ):
            if len(collection) > CONTEXT_CARD_COLLECTION_LIMIT:
                raise ValueError("a context card holds a bounded number of each record")
            if len(collection) < CONTEXT_CARD_COLLECTION_LIMIT and limitation in self.limitations:
                raise ValueError("a context card claims a limitation that did not apply")
        for limitation in self.limitations:
            if not isinstance(limitation, ContextCardLimitation):
                raise ValueError("a context card limitation is from the closed vocabulary")
        if len(set(self.limitations)) != len(self.limitations):
            raise ValueError("a context card states each limitation once")
        owned: tuple[EntityAlias | ExternalIdentifier | Assignment, ...] = (
            *self.aliases,
            *self.identifiers,
            *self.assignments,
        )
        for record in owned:
            if record.entity_id != self.entity.entity_id:
                raise ValueError("a context card holds only records of the entity it names")
        for edge in self.relationships:
            if self.entity.entity_id not in (edge.from_entity_id, edge.to_entity_id):
                raise ValueError("a context card holds only edges touching the entity it names")
        for observation in self.observations:
            if observation.entity_id != self.entity.entity_id:
                raise ValueError("a context card holds only observations of the entity it names")
        sources = [entry.source_id for entry in self.coverage]
        if len(set(sources)) != len(sources):
            raise ValueError("a context card states each source's coverage once")
        empty = ContextCardLimitation.NO_SOURCE_HAS_BEEN_OBSERVED in self.limitations
        if empty != (not self.coverage):
            raise ValueError("a context card says so exactly when no source has been observed")

    @property
    def is_complete(self) -> bool:
        """Whether the card carries everything recorded, or only what fits.

        `NO_SOURCE_HAS_BEEN_OBSERVED` does not make a card incomplete: it is a
        fact about the evidence, not an admission that the card ran out of room.
        Conflating the two would report a fully assembled card about an
        unobserved person as truncated.
        """
        return not (set(self.limitations) - {ContextCardLimitation.NO_SOURCE_HAS_BEEN_OBSERVED})

    @property
    def most_recent_observation_at(self) -> datetime | None:
        """The freshest evidence behind this card, or `None` if there is none."""
        if not self.coverage:
            return None
        return max(entry.most_recent_observation_at for entry in self.coverage)
