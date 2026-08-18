"""A bounded assembly of what is recorded about one entity.

The specification calls this a **context packet** (section 26.3) and asks it to
carry its purpose, its included and excluded sources, its redactions, its size
budget, its citations, and its invalidation rule. This is the first half: the
records themselves, bounded and with every omission named. Coverage, freshness,
and the disclosure route arrive with the work package that has sources to
disclose (`WP-RI-07`); a card that claimed them now would be claiming them about
records nothing has observed.

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
from enum import StrEnum

from my_pa.domain.relationship.entity import (
    Assignment,
    Entity,
    EntityAlias,
    EntityRelationship,
    ExternalIdentifier,
)

__all__ = [
    "CONTEXT_CARD_COLLECTION_LIMIT",
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


@dataclass(frozen=True, slots=True)
class EntityContextCard:
    """One entity and the records around it, bounded and self-describing."""

    entity: Entity
    aliases: tuple[EntityAlias, ...] = ()
    identifiers: tuple[ExternalIdentifier, ...] = ()
    assignments: tuple[Assignment, ...] = ()
    relationships: tuple[EntityRelationship, ...] = ()
    limitations: tuple[ContextCardLimitation, ...] = ()

    def __post_init__(self) -> None:
        for collection, limitation in (
            (self.aliases, ContextCardLimitation.MORE_ALIASES_THAN_THIS_CARD_CARRIES),
            (self.identifiers, ContextCardLimitation.MORE_IDENTIFIERS_THAN_THIS_CARD_CARRIES),
            (self.assignments, ContextCardLimitation.MORE_ASSIGNMENTS_THAN_THIS_CARD_CARRIES),
            (
                self.relationships,
                ContextCardLimitation.MORE_RELATIONSHIPS_THAN_THIS_CARD_CARRIES,
            ),
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

    @property
    def is_complete(self) -> bool:
        """Whether the card carries everything recorded, or only what fits."""
        return not self.limitations
