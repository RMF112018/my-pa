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
opposite. `ReenrichmentOutcome.reached_the_bound` says whether more work
remains, so a caller loops deliberately instead of assuming one pass finished.

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

from dataclasses import dataclass
from enum import StrEnum

from my_pa.application.entity_resolution import EntityResolutionService, ResolutionRequest
from my_pa.contracts.ports import EntitiesRepository
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.relationship.resolution import ResolutionOutcome

__all__ = [
    "REENRICHMENT_BOUND",
    "EntityReenrichmentService",
    "ReenrichmentOutcome",
    "ReenrichmentTrigger",
]

#: The most records one pass touches. Small on purpose: a caller that needs more
#: loops and can stop, where a caller handed an unbounded pass cannot.
REENRICHMENT_BOUND: int = 100


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
    reached_the_bound: bool = False

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
        """
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(merged_entity_id, IdKind.ENTITY)
        validate_identifier(retained_entity_id, IdKind.ENTITY)
        if merged_entity_id == retained_entity_id:
            raise ValueError("a merge re-enrichment names two distinct entities")

        stranded = self._entities.observations(principal_id, merged_entity_id)
        bounded = stranded[:REENRICHMENT_BOUND]
        for observation in bounded:
            self._entities.link_observation(
                principal_id, observation.observation_id, retained_entity_id
            )
        return ReenrichmentOutcome(
            trigger=ReenrichmentTrigger.IDENTITY_MERGED,
            observations_repointed=len(bounded),
            reached_the_bound=len(bounded) < len(stranded),
        )

    def after_alias(self, principal_id: str) -> ReenrichmentOutcome:
        """Re-offer every unresolved mention to the resolver.

        Links only what resolves exactly. A mention the resolver will not place
        stays where it is and is counted, because a queue that shrank without
        anything being decided would be the failure this whole plane is built to
        avoid.
        """
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        pending = self._entities.observations(principal_id, unresolved_only=True)
        bounded = pending[:REENRICHMENT_BOUND]

        linked = 0
        for observation in bounded:
            answer = self._resolving.resolve(
                principal_id, ResolutionRequest(raw_reference=observation.normalized_value)
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
            reached_the_bound=len(bounded) < len(pending),
        )
