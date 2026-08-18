"""Propose a change to the entity plane, and decide one.

**The rule this module exists to make structural.** Specification section 21.4:
a model may not "create a canonical person without governed identity rules" or
"merge identities autonomously". Section 8.6: extracted data "begins as
proposals". `RI-AC-039` says the same in one line.

So `propose` writes a proposal and nothing else — it cannot apply a mutation,
because it never calls a write other than `record_proposal`. And `decide`
requires an actor and a disposition from its caller: there is no default, no
"accept if confident", and no threshold in this module at all. A proposal
becomes a change when something outside it says so, with its name attached.

**`REQUIRES_OPERATOR` is enforced here and not left to a caller.** Section 8.4
says identity merges are "not eligible for default bulk acceptance"; section 8.2
of `AGENTS.md` reserves irreversible identity decisions to the operator. So
`decide` refuses to accept a merge unless the caller declares operator
authority, and the declaration is a parameter rather than a flag on the
proposal — a proposal that could name its own authority level could name the
lowest one.

**What accepting a merge does, and does not do.** It redirects the merged-away
entity at the survivor and writes a lineage record. It does *not* delete the
merged entity, rewrite its identifiers, or move its observations: section 15.3
asks a merge to preserve prior identifiers as lineage, and an entity that still
resolves as a `HISTORICAL_MATCH` is how a merge stays reversible. Re-pointing
the records that referred to it is re-enrichment, and re-enrichment is
`WP-RI-08`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from my_pa.contracts.ports import EntitiesRepository
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.relationship.governance import (
    EntityMergeRecord,
    EntityObservation,
    EntityProposal,
    EntityProposalKind,
    EntityProposalState,
    ReviewRequirement,
)

__all__ = [
    "EntityGovernanceService",
    "ProposalNotOpenError",
    "ReviewAuthorityError",
]


class ReviewAuthorityError(Exception):
    """A decision was attempted without the authority the proposal requires."""


class ProposalNotOpenError(Exception):
    """A decision was attempted on a proposal that has already been decided.

    Its own error rather than a silent no-op, because "this was already
    accepted" and "this is now accepted" are different facts and a caller acting
    on the second when the first is true has lost track of who decided what.
    """


class EntityGovernanceService:
    """Records observations, proposes changes, and applies decided ones."""

    def __init__(self, entities: EntitiesRepository) -> None:
        self._entities = entities

    # --- observation ------------------------------------------------------

    def observe(self, principal_id: str, observation: EntityObservation) -> None:
        """Record what a source said. Creates no entity and links to none.

        The narrowest method here on purpose: section 12.2 says a source record
        "does not become the canonical person by itself", and the way to make
        that true is for the method that records one to be unable to do anything
        else.
        """
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        self._entities.record_observation(principal_id, observation)

    def unresolved_mentions(self, principal_id: str) -> list[EntityObservation]:
        """Every observation nothing has linked to an entity.

        A first-class queue rather than a gap in the data (`RI-AC-006`): these
        are the references the system knows it has not placed, and being able to
        list them is what makes "unresolved" a state rather than an absence.
        """
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        return self._entities.observations(principal_id, unresolved_only=True)

    def link(self, principal_id: str, observation_id: str, entity_id: str) -> None:
        """Attach one observation to the entity it turned out to refer to."""
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        self._entities.link_observation(principal_id, observation_id, entity_id)

    # --- proposal ---------------------------------------------------------

    def propose(
        self,
        principal_id: str,
        *,
        proposal_id: str,
        kind: EntityProposalKind,
        payload: Mapping[str, str],
        observation_ids: tuple[str, ...],
        proposed_by: str,
        proposed_at: datetime,
    ) -> EntityProposal:
        """Record a proposed mutation. Applies nothing.

        Returns the proposal so a caller can read `requirement` and know what
        would have to happen next, rather than discovering it when `decide`
        refuses.
        """
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        proposal = EntityProposal(
            proposal_id=proposal_id,
            principal_id=principal_id,
            kind=kind,
            state=EntityProposalState.PROPOSED,
            payload=tuple(sorted((str(k), str(v)) for k, v in payload.items())),
            observation_ids=observation_ids,
            proposed_at=ensure_utc(proposed_at),
            proposed_by=proposed_by,
        )
        self._entities.record_proposal(principal_id, proposal)
        return proposal

    def open_proposals(self, principal_id: str) -> list[EntityProposal]:
        """Everything awaiting a decision."""
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        return self._entities.proposals(principal_id, state=EntityProposalState.PROPOSED)

    def reject(
        self,
        principal_id: str,
        proposal_id: str,
        *,
        decided_by: str,
        decided_at: datetime,
        reason: str,
    ) -> EntityProposal:
        """Refuse a proposal. Needs no authority beyond naming who refused.

        Asymmetric with `accept` deliberately: refusing changes nothing, so the
        gate that protects a change has nothing to protect here. Refusing is
        still *recorded*, because section 10.11 keeps rejected evidence.
        """
        return self._decide(
            principal_id,
            proposal_id,
            state=EntityProposalState.REJECTED,
            decided_by=decided_by,
            decided_at=decided_at,
            reason=reason,
            has_operator_authority=False,
        )

    def accept(
        self,
        principal_id: str,
        proposal_id: str,
        *,
        decided_by: str,
        decided_at: datetime,
        reason: str,
        has_operator_authority: bool = False,
        merge_id: str | None = None,
    ) -> EntityProposal:
        """Accept a proposal and apply what it asked for.

        `has_operator_authority` is a parameter the caller must pass rather than
        anything this module can infer. A `REQUIRES_OPERATOR` proposal — today,
        every merge — is refused without it.
        """
        return self._decide(
            principal_id,
            proposal_id,
            state=EntityProposalState.ACCEPTED,
            decided_by=decided_by,
            decided_at=decided_at,
            reason=reason,
            has_operator_authority=has_operator_authority,
            merge_id=merge_id,
        )

    def _decide(
        self,
        principal_id: str,
        proposal_id: str,
        *,
        state: EntityProposalState,
        decided_by: str,
        decided_at: datetime,
        reason: str,
        has_operator_authority: bool,
        merge_id: str | None = None,
    ) -> EntityProposal:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        held = self._entities.proposal(principal_id, proposal_id)
        if held is None:
            raise ProposalNotOpenError("no such proposal in this scope")
        if not held.is_open:
            raise ProposalNotOpenError("this proposal has already been decided")
        if not decided_by.strip():
            raise ValueError("a decision names who made it")

        accepting = state is EntityProposalState.ACCEPTED
        if (
            accepting
            and held.requirement is ReviewRequirement.REQUIRES_OPERATOR
            and not has_operator_authority
        ):
            raise ReviewAuthorityError(
                "this proposal requires operator authority and the caller declared none"
            )

        decided = EntityProposal(
            proposal_id=held.proposal_id,
            principal_id=held.principal_id,
            kind=held.kind,
            state=state,
            payload=held.payload,
            observation_ids=held.observation_ids,
            proposed_at=held.proposed_at,
            proposed_by=held.proposed_by,
            decided_by=decided_by,
            decided_at=ensure_utc(decided_at),
            decision_reason=reason,
        )
        if accepting:
            self._apply(principal_id, decided, merge_id=merge_id)
        self._entities.decide_proposal(principal_id, decided)
        return decided

    # --- applying an accepted proposal -------------------------------------

    def _apply(self, principal_id: str, proposal: EntityProposal, *, merge_id: str | None) -> None:
        """Perform what an accepted proposal asked for.

        Only merges are applied here. The other five kinds name mutations whose
        arguments are whole domain records rather than the string pairs a
        proposal payload carries, and reconstructing an `ExternalIdentifier` from
        flattened strings would be a second, weaker constructor for a type that
        already has one. Those kinds are recorded and decided here and applied by
        the caller that holds the record — which is the honest division until
        something produces them, and is stated here rather than discovered.
        """
        if proposal.kind is not EntityProposalKind.MERGE_ENTITIES:
            return
        payload = dict(proposal.payload)
        merged = payload.get("merged_entity_id")
        retained = payload.get("retained_entity_id")
        if not merged or not retained:
            raise ValueError("a merge proposal names the entity kept and the entity merged away")
        if merge_id is None:
            raise ValueError("accepting a merge records its lineage, which needs an identifier")

        self._entities.redirect_entity(principal_id, merged, retained)
        self._entities.record_merge(
            principal_id,
            EntityMergeRecord(
                merge_id=merge_id,
                principal_id=principal_id,
                retained_entity_id=retained,
                merged_entity_id=merged,
                proposal_id=proposal.proposal_id,
                decided_by=proposal.decided_by or "",
                reason=proposal.decision_reason or "",
                decided_at=proposal.decided_at or proposal.proposed_at,
            ),
        )

    def merge_lineage(
        self, principal_id: str, entity_id: str | None = None
    ) -> list[EntityMergeRecord]:
        """Every merge recorded, or every merge touching one entity."""
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        return self._entities.merges(principal_id, entity_id)
