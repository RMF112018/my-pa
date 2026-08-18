"""Redo the work an accepted change invalidated, boundedly and idempotently.

Specification section 27.4 lists nine re-enrichment triggers -- a corrected
identity, a new alias, a role change, a source version change, and so on. Two of
them are reachable today, and this module does those two:

* **an identity was merged** — every observation that pointed at the merged-away
  entity now points at a redirect, and section 15.3 asks a merge to "trigger
  bounded re-enrichment where appropriate". Re-pointing them at the survivor is
  what makes the merge finished rather than merely recorded (`RI-AC-059`).
* **an alias was recorded** — a name the system could not place before may now
  resolve, so the unresolved mentions are re-offered to the resolver.

The other seven need observations from sources this product does not yet read.
Listing them here rather than implying completeness, because a re-enrichment
pass that silently covered two of nine would look like a pass that covered all
of them.

**Bounded, and the bound is disclosed.** Section 27.4 asks re-enrichment to
"reuse stable extraction where possible rather than repeating expensive
processing"; a pass that walked every observation a Principal has would be the
opposite. `ReenrichmentOutcome.more_remains` says whether work is left over,
so a caller loops deliberately instead of assuming one pass finished. Named for
what a caller does with it: the earlier `reached_the_bound` read as a property
of the pass, and a caller could reasonably have taken `False` to mean "stopped
early, nothing more to do" *or* "never hit the cap" -- which are the same fact
here but were not obviously so at the call site.

**Idempotent, per section 27.2.** Re-pointing an observation already pointing at
the survivor writes the same value; re-offering a mention that still does not
resolve links nothing. Running the same pass twice produces the same rows, which
is what makes it safe to retry after a failure that may or may not have
committed.

**It never resolves an ambiguity.** A mention is linked only when resolution
answers `RESOLVED_EXACT`. `AMBIGUOUS`, `CONFLICTED_IDENTIFIER` and
`HISTORICAL_MATCH` all leave it unresolved, because a background pass with
nobody watching is the last place a doubtful identity join should be made.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from my_pa.application.entity_resolution import EntityResolutionService, ResolutionRequest
from my_pa.contracts.ports import EntitiesRepository
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.relationship.entity import EntityType
from my_pa.domain.relationship.governance import ObservationKind
from my_pa.domain.relationship.resolution import ResolutionOutcome

__all__ = [
    "KIND_IMPLIES_ENTITY_TYPE",
    "REENRICHMENT_BOUND",
    "EntityReenrichmentService",
    "ReenrichmentOutcome",
    "ReenrichmentTrigger",
]

#: The most records one pass touches. Small on purpose: a caller that needs more
#: loops and can stop, where a caller handed an unbounded pass cannot.
REENRICHMENT_BOUND: int = 100

#: The entity type an observation of each kind can only be about, where the kind
#: settles it.
#:
#: A contact row, a message participant and a calendar attendee are all records
#: *of a person*; nothing in this product produces one about a project. Passing
#: the constraint into resolution is not an optimisation -- without it, a
#: `message_participant` observation carrying the text "Harbour Tower" links to
#: the *project* of that name, and a background pass with nobody watching has
#: made a person-to-project join that no operator ever saw.
#:
#: `DOCUMENT_MENTION` and `USER_STATEMENT` are deliberately absent: a document
#: or a sentence can name a person, an organization or a project with equal
#: ease, and inventing a constraint there would be this module guessing. They
#: resolve unconstrained, which means they resolve less often -- the trade this
#: plane makes everywhere.
#:
#: The mapping has a cost worth naming: a shared mailbox or a room resource is a
#: `MESSAGE_PARTICIPANT` or a `CALENDAR_ATTENDEE` that is *not* a person, and
#: this pass will now never link one. That is a mention left on the queue for a
#: human, which is the direction this module errs in on purpose.
#:
#: A read-only mapping, so a caller cannot widen the constraint at runtime --
#: which would be a person-to-project join arranged from outside this module.
KIND_IMPLIES_ENTITY_TYPE: Final[Mapping[ObservationKind, EntityType]] = MappingProxyType(
    {
        ObservationKind.CONTACT_RECORD: EntityType.PERSON,
        ObservationKind.MESSAGE_PARTICIPANT: EntityType.PERSON,
        ObservationKind.CALENDAR_ATTENDEE: EntityType.PERSON,
    }
)


class ReenrichmentTrigger(StrEnum):
    """Why a re-enrichment pass ran.

    A closed set naming only the triggers this module implements. Section 27.4
    lists seven more; each arrives with the observation source that makes it
    detectable, and adding one here without the work behind it would be a
    trigger that never fires.
    """

    IDENTITY_MERGED = "identity_merged"
    ALIAS_RECORDED = "alias_recorded"


@dataclass(frozen=True, slots=True)
class ReenrichmentOutcome:
    """What one pass did, including what it declined to do.

    `mentions_left_unresolved` is reported rather than inferred from the
    difference, because "considered and not linked" is the interesting number:
    it is the count of references the system looked at again and still would not
    guess about.
    """

    trigger: ReenrichmentTrigger
    observations_repointed: int = 0
    mentions_linked: int = 0
    mentions_left_unresolved: int = 0
    more_remains: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.trigger, ReenrichmentTrigger):
            raise ValueError("a re-enrichment outcome names a closed trigger")
        for count in (
            self.observations_repointed,
            self.mentions_linked,
            self.mentions_left_unresolved,
        ):
            if count < 0:
                raise ValueError("a re-enrichment outcome counts what it did")

    @property
    def changed_anything(self) -> bool:
        return bool(self.observations_repointed or self.mentions_linked)


class EntityReenrichmentService:
    """Re-does the bounded work an accepted change invalidated."""

    def __init__(self, entities: EntitiesRepository) -> None:
        self._entities = entities
        self._resolving = EntityResolutionService(entities)

    def after_merge(
        self, principal_id: str, merged_entity_id: str, retained_entity_id: str
    ) -> ReenrichmentOutcome:
        """Re-point the merged-away entity's observations at the survivor.

        The observations are *moved*, not copied: they were always observations
        of one person, and the merge is the decision that said which person. The
        merged-away entity remains, still holding its identifiers and aliases as
        lineage — what changes is which entity the evidence hangs off.

        **A recorded merge is a precondition, not an assumption.** This method's
        entire authority to re-point someone's evidence at a different person
        comes from a merge decision an operator made (section 8.4). Called with
        two identifiers no decision connects, it would perform exactly the
        false join `RI-RISK-001` names — silently, in the background, with no
        proposal, no record, and no actor. So it reads the lineage first and
        refuses when nothing is there.
        """
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(merged_entity_id, IdKind.ENTITY)
        validate_identifier(retained_entity_id, IdKind.ENTITY)
        if merged_entity_id == retained_entity_id:
            raise ValueError("a merge re-enrichment names two distinct entities")
        recorded = any(
            record.merged_entity_id == merged_entity_id
            and record.retained_entity_id == retained_entity_id
            for record in self._entities.merges(principal_id, merged_entity_id)
        )
        if not recorded:
            raise ValueError("a merge re-enrichment follows a recorded merge")

        # One past the bound, so `more_remains` is answerable without a second
        # query and without fetching rows this pass will not touch. Slicing an
        # unbounded read afterwards would have paid for every stranded
        # observation to move a hundred of them.
        stranded = self._entities.observations(
            principal_id, merged_entity_id, limit=REENRICHMENT_BOUND + 1
        )
        bounded = stranded[:REENRICHMENT_BOUND]
        for observation in bounded:
            self._entities.link_observation(
                principal_id, observation.observation_id, retained_entity_id
            )
        return ReenrichmentOutcome(
            trigger=ReenrichmentTrigger.IDENTITY_MERGED,
            observations_repointed=len(bounded),
            more_remains=len(bounded) < len(stranded),
        )

    def after_alias(self, principal_id: str) -> ReenrichmentOutcome:
        """Re-offer every unresolved mention to the resolver.

        Links only what resolves exactly. A mention the resolver will not place
        stays where it is and is counted, because a queue that shrank without
        anything being decided would be the failure this whole plane is built to
        avoid.

        Each mention carries its `kind` into the request as an `entity_type`
        constraint where the kind settles it (`KIND_IMPLIES_ENTITY_TYPE`). The
        pass used to ask only "who is called this", which let a calendar
        attendee link to a project sharing the name.
        """
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        pending = self._entities.observations(
            principal_id, unresolved_only=True, limit=REENRICHMENT_BOUND + 1
        )
        bounded = pending[:REENRICHMENT_BOUND]

        linked = 0
        for observation in bounded:
            answer = self._resolving.resolve(
                principal_id,
                ResolutionRequest(
                    raw_reference=observation.normalized_value,
                    entity_type=KIND_IMPLIES_ENTITY_TYPE.get(observation.kind),
                ),
            )
            if answer.outcome is not ResolutionOutcome.RESOLVED_EXACT:
                continue
            resolved = answer.resolved_entity_id
            if resolved is None:  # pragma: no cover - the type forbids it
                continue
            self._entities.link_observation(principal_id, observation.observation_id, resolved)
            linked += 1

        return ReenrichmentOutcome(
            trigger=ReenrichmentTrigger.ALIAS_RECORDED,
            mentions_linked=linked,
            mentions_left_unresolved=len(bounded) - linked,
            more_remains=len(bounded) < len(pending),
        )
