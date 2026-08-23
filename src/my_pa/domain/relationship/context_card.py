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

`RM-API-AC-013` adds Relationship Memory to the card, and it is the collection
where the "partial answer must not read as a complete one" rule has teeth,
because the records are what one person wrote about another. A memory can be
missing from a card for four unrelated reasons, and the card names all four
apart:

* there are more memories than it carries (`MORE_MEMORIES_THAN_THIS_CARD_CARRIES`);
* some were withheld by classification policy and will not be carried at any
  page size (`MEMORIES_WERE_WITHHELD_BY_CLASSIFICATION`);
* the store was read and holds none (`NO_MEMORY_HAS_BEEN_RECORDED`);
* the plane was never read at all, so the card knows nothing either way
  (`THE_MEMORY_PLANE_IS_UNAVAILABLE`).

**The failure this prevents is one sentence: a reader concluding "nothing is
recorded about this person" from a card that simply did not look.** An empty
`memories` list is the same bytes in all four cases, and three of them are not
facts about the person -- one is a page size, one is a policy decision, and one
is which switches this build was started with. So the empty list is never the
statement: `NO_MEMORY_HAS_BEEN_RECORDED` is, it is assertable only by a card
that actually queried the store and was answered with nothing withheld, and
`EntityContextCard.__post_init__` refuses every arrangement in which those two
could disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from my_pa.domain.common.classification import Classification
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
from my_pa.domain.relationship.memory import RelationshipMemory, RelationshipMemoryVersion

__all__ = [
    "CONTEXT_CARD_COLLECTION_LIMIT",
    "CONTEXT_CARD_COVERAGE_LIMIT",
    "ContextCardCoverage",
    "ContextCardLimitation",
    "ContextCardMemory",
    "EntityContextCard",
]

#: The most records of any one kind a card carries. Per-collection rather than
#: one budget over the whole card, because a person with forty edges and two
#: aliases should not lose the aliases to the edges.
CONTEXT_CARD_COLLECTION_LIMIT: int = 25

#: The most observations the card will *read* to compute coverage, as distinct
#: from the `CONTEXT_CARD_COLLECTION_LIMIT` it will carry.
#:
#: Higher than the collection limit on purpose: coverage says which sources
#: contributed and how recently, and computing it from the twenty-five rows the
#: card happens to show would report "one source" for an entity with four. But
#: it is a ceiling rather than no limit at all, because observations are the one
#: collection here that grows with every source record that ever mentioned
#: someone -- a heavily observed entity would otherwise pull an unbounded result
#: set into memory to answer a single read.
#:
#: When the ceiling bites, the card says so (`COVERAGE_COUNTED_A_BOUNDED_SAMPLE`)
#: rather than presenting a partial count as a complete one.
CONTEXT_CARD_COVERAGE_LIMIT: int = 500


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
    #: Coverage was computed from the first `CONTEXT_CARD_COVERAGE_LIMIT`
    #: observations rather than from all of them. The sources named are real;
    #: the counts are floors and there may be sources not named at all. Stated
    #: because a coverage figure a reader takes for complete is worse than no
    #: coverage figure -- it is the "four sources agree" the card exists to make
    #: trustworthy, computed from a sample nobody was told about.
    COVERAGE_COUNTED_A_BOUNDED_SAMPLE = "coverage_counted_a_bounded_sample"
    #: There are more memories about this entity than the card carries. The
    #: ordinary truncation, and the only one of the memory limitations a larger
    #: page would fix -- which is why it is the only one `is_complete` reads.
    MORE_MEMORIES_THAN_THIS_CARD_CARRIES = "more_memories_than_this_card_carries"
    #: Memories on the page the card read were withheld by classification
    #: policy, and no page size will produce them.
    #:
    #: Stated rather than left as a shorter list, and it is the disclosure the
    #: whole memory summary turns on: a `restricted_local` memory is exactly the
    #: kind of thing a reader most needs to know exists -- "do not raise the
    #: Riverside dispute" -- and a card that dropped it silently would read as a
    #: card about someone with nothing sensitive recorded. That is not a smaller
    #: answer to the question; it is the opposite answer.
    #:
    #: It discloses *that* something is withheld and never what: the card is one
    #: entity the caller already named and already reads, so the existence of a
    #: withheld row about that entity tells them nothing the read did not
    #: already tell them. A search count would be different, and
    #: `RelationshipMemoryRepository.search` accordingly reports none.
    MEMORIES_WERE_WITHHELD_BY_CLASSIFICATION = "memories_were_withheld_by_classification"
    #: The store was read and holds no memory about this entity.
    #:
    #: The only member of the four that is a fact about the *person*, and the
    #: reason the other three exist: without them a caller would read this one
    #: off an empty list and be right by accident three-quarters of the time.
    #: `EntityContextCard.__post_init__` refuses it on a card that did not reach
    #: the plane and on a card that withheld something, so it cannot be stated
    #: by a card that does not know it.
    NO_MEMORY_HAS_BEEN_RECORDED = "no_memory_has_been_recorded"
    #: This build has not composed the Relationship Memory plane, so the card
    #: says nothing about memories in either direction.
    #:
    #: Section 6.8's rule applied to composition rather than to evidence: "no
    #: memory plane" and "no memories" look identical in the payload and differ
    #: in everything else. A caller that reads this knows to stop concluding,
    #: rather than to ask again with a bigger page -- which is why it is not a
    #: truncation and why `is_complete` does not read it.
    THE_MEMORY_PLANE_IS_UNAVAILABLE = "the_memory_plane_is_unavailable"


#: The limitations that say something about the world rather than admit the card
#: ran out of room. `is_complete` subtracts them, and every member is here for
#: one shared reason: none of them would be answered differently by asking again.
#:
#: A caller reads `is_complete is False` as "there is more of this shape, ask
#: for it", and three of these four would send them into a request that returns
#: the same card forever -- an unobserved entity stays unobserved, a withheld
#: memory stays withheld at any page size, and a plane this build did not
#: compose does not appear because someone paged. The fourth,
#: `NO_MEMORY_HAS_BEEN_RECORDED`, is the plainest case of all: it is a *complete*
#: answer that happens to be empty.
#:
#: They remain in `limitations`, which is where a reader learns them. This set
#: decides only what the word "complete" means, and it means "the card carries
#: everything a larger card would have carried".
_NOT_A_TRUNCATION: frozenset[ContextCardLimitation] = frozenset(
    {
        ContextCardLimitation.NO_SOURCE_HAS_BEEN_OBSERVED,
        ContextCardLimitation.NO_MEMORY_HAS_BEEN_RECORDED,
        ContextCardLimitation.MEMORIES_WERE_WITHHELD_BY_CLASSIFICATION,
        ContextCardLimitation.THE_MEMORY_PLANE_IS_UNAVAILABLE,
    }
)


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
class ContextCardMemory:
    """One memory the card carries: the aggregate, and the version in force.

    Both halves, because neither answers the question on its own and neither is
    derivable from the other here. `pinned` and the lifecycle belong to the
    aggregate; the statement, its authority, its classification and the window it
    applies to belong to the version. A card holding only versions could not say
    which memory the user pinned, and one holding only aggregates would carry no
    statement at all.

    **It is the shape `contracts.MemoryDetail` already has, and it is restated
    here rather than imported**, because `domain` may depend on neither
    `contracts` nor `application` -- `test_dependency_direction` enforces that,
    and importing the port's result type into the domain would invert the one
    direction the layering exists to fix. The application maps one to the other
    at the boundary, which is the trip every other port result already makes.

    A card memory is never `restricted_local`, and that is a constructor
    invariant rather than a query filter. `summaries_for_context` does exclude
    them, but "the card discloses no restricted memory" is a property of the
    product and not of one `WHERE` clause: a second reader, a cache, or a
    rewrite of that query would each be a place to lose it silently. Here it
    cannot be lost, because a card carrying one cannot be built.
    """

    memory: RelationshipMemory
    current_version: RelationshipMemoryVersion

    def __post_init__(self) -> None:
        if self.current_version.memory_id != self.memory.memory_id:
            raise ValueError("a card memory pairs a memory with a version of itself")
        if self.current_version.memory_version_id != self.memory.current_version_id:
            raise ValueError("a card memory carries the version its memory calls current")
        if self.current_version.principal_id != self.memory.principal_id:
            raise ValueError("a card memory's two halves belong to one Principal")
        if self.current_version.classification is Classification.RESTRICTED_LOCAL:
            raise ValueError("a context card carries no restricted memory")


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
    memories: tuple[ContextCardMemory, ...] = ()
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
        self._check_memories()

    def _check_memories(self) -> None:
        """The memory summary is bounded, is about this entity, and says which.

        Separate from the five collections above rather than folded into their
        loop, and the reason is the one thing memories do that no other
        collection does: **rows can leave the page without leaving the store.**
        The loop's "claims a limitation that did not apply" rule reads a short
        list as proof that nothing was dropped, which is sound for aliases and
        wrong here -- a card that read twenty-five rows, was refused three by
        classification policy and found a twenty-sixth waiting is correctly
        truncated while carrying twenty-two. Folding memories into that loop
        would have made the honest card the one arrangement that raised.

        So truncation is refused only when nothing could have thinned the page,
        and the four memory limitations are checked against each other instead,
        because they are the assertion this collection exists to make.
        """
        stated = set(self.limitations)
        consulted = ContextCardLimitation.THE_MEMORY_PLANE_IS_UNAVAILABLE not in stated
        withheld = ContextCardLimitation.MEMORIES_WERE_WITHHELD_BY_CLASSIFICATION in stated
        crowded = ContextCardLimitation.MORE_MEMORIES_THAN_THIS_CARD_CARRIES in stated
        silent = ContextCardLimitation.NO_MEMORY_HAS_BEEN_RECORDED in stated
        if len(self.memories) > CONTEXT_CARD_COLLECTION_LIMIT:
            raise ValueError("a context card holds a bounded number of each record")
        for held in self.memories:
            if held.memory.subject_entity_id != self.entity.entity_id:
                raise ValueError("a context card holds only memories about the entity it names")
        carried = [held.memory.memory_id for held in self.memories]
        if len(set(carried)) != len(carried):
            raise ValueError("a context card carries each memory once")
        if crowded and not withheld and len(self.memories) < CONTEXT_CARD_COLLECTION_LIMIT:
            raise ValueError("a context card claims a limitation that did not apply")
        # A card that never reached the plane knows nothing about memories, so
        # it may state nothing about them -- not their absence, not a
        # withholding, not a truncation, and above all not a memory. This is the
        # invariant that makes `THE_MEMORY_PLANE_IS_UNAVAILABLE` mean what it
        # says rather than being a label a populated card could also wear.
        if not consulted and (self.memories or withheld or crowded or silent):
            raise ValueError("a card that did not reach the memory plane states no memory fact")
        # And the other direction: a card that *did* reach it says "nothing is
        # recorded" exactly when it came back with nothing and nothing was
        # withheld. Not one case looser -- an all-withheld page is the case this
        # closes, and reading it as absence is the disclosure failure the whole
        # collection is arranged around.
        if consulted and silent != (not self.memories and not withheld):
            raise ValueError("a context card says so exactly when no memory has been recorded")

    @property
    def is_complete(self) -> bool:
        """Whether the card carries everything recorded, or only what fits.

        `NO_SOURCE_HAS_BEEN_OBSERVED` does not make a card incomplete: it is a
        fact about the evidence, not an admission that the card ran out of room.
        Conflating the two would report a fully assembled card about an
        unobserved person as truncated.

        **The three memory limitations that are not truncations are exempt for
        the same reason, and the decision is worth stating because two of them
        look like incompleteness.** A withheld memory *is* a record the card does
        not carry, and an unavailable plane means the card cannot speak for a
        whole collection -- so why is either one "complete"?

        Because of what the caller does with the answer. This property is the
        `Truncation` the `entities.context` handler publishes, its wire reason is
        `card_collection_limit_reached`, and a caller reading `is_truncated`
        asks again for the rest. Only `MORE_MEMORIES_THAN_THIS_CARD_CARRIES`
        rewards that: the other two return the identical card however many times
        it is requested, so reporting them as truncation would be an invitation
        to a loop that cannot terminate -- and it would attach a reason naming a
        collection limit to a card whose collection limit never bit, which is a
        false statement about which bound applied.

        What the caller must not do is conclude anything about memories from a
        complete card without reading `limitations`, and no arrangement of this
        property could have protected them from that: `is_complete` is one bit
        and the four states it would have to carry are four. The limitations
        carry them, `__post_init__` keeps them from disagreeing, and this
        property stays the narrow question it has always answered -- did the card
        run out of room.
        """
        return not (set(self.limitations) - _NOT_A_TRUNCATION)

    @property
    def most_recent_observation_at(self) -> datetime | None:
        """The freshest evidence behind this card, or `None` if there is none."""
        if not self.coverage:
            return None
        return max(entry.most_recent_observation_at for entry in self.coverage)
