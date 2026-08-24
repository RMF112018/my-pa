"""The proposal plane's fake repository, extended for the promotion path.

**This belongs in `tests/conftest.py` beside `_Entities`, and is here because
that file is frozen for `WP-RI-B-05`.** The Phase B orchestration assigns
`tests/conftest.py` to nobody this wave, so a worker that needs the shared fake
to grow records the requirement rather than editing it. The requirement is in
this worker's handoff, and the four methods below are exactly what has to move
there: they are written against `World` and against the same rules the SQL
repository enforces, so moving them is a cut and a paste rather than a rewrite.

Every method here mirrors `SqlEntityRepository`, and the mirroring is the whole
value of the fake. `tests/conftest.py` says why in its own words: a unit test
that proves a rule against a fake with no such rule proves the opposite of what
the server does. So `decide_proposal` carries the same undecided-state predicate
the guarded `UPDATE` carries, `record_proposal_promotion` refuses a proposal
that is not accepted or already names a record, and every read and write is
partitioned before anything else happens.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime

from my_pa.contracts.ports import UnknownScopeError
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.relationship.governance import (
    ACCEPTED_PROPOSAL_STATES,
    UNDECIDED_PROPOSAL_STATES,
    EntityProposal,
    EntityProposalEvidenceLink,
    EntityProposalState,
    MutationRecordFamily,
)
from tests.conftest import _Entities

#: Where the evidence links live until `World` grows a field for them.
#:
#: On the `World` rather than on the repository instance, because the existing
#: `_entities(world)` helpers in these test modules build a fresh `_Entities`
#: on every call and share their state through the `World` alone. A list on the
#: instance would make "the links this proposal has" depend on which of those
#: identical repositories asked.
_EVIDENCE_FIELD = "_wp_ri_b_05_proposal_evidence"


class ProposalEntities(_Entities):
    """`_Entities` with the proposal-plane methods `WP-RI-B-05` added."""

    @property
    def proposal_evidence(self) -> list[EntityProposalEvidenceLink]:
        held: list[EntityProposalEvidenceLink] | None = getattr(self._world, _EVIDENCE_FIELD, None)
        if held is None:
            held = []
            setattr(self._world, _EVIDENCE_FIELD, held)
        return held

    # --- the open-equivalent read the partial unique index is over ---------

    def proposal_by_dedupe(
        self,
        principal_id: str,
        dedupe_sha256: str,
        states: Iterable[EntityProposalState],
    ) -> EntityProposal | None:
        wanted = set(states)
        if not wanted:
            return None
        ordered = sorted(self._world.entity_proposals, key=lambda held: held.proposal_id)
        return next(
            (
                held
                for held in ordered
                if held.principal_id == principal_id
                and held.dedupe_sha256 == dedupe_sha256
                and held.state in wanted
            ),
            None,
        )

    # --- the evidence table that had no writer -----------------------------

    def record_proposal_evidence_link(
        self, principal_id: str, link: EntityProposalEvidenceLink
    ) -> None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if link.principal_id != principal_id:
            raise ValueError("proposal evidence belongs to the acting Principal")
        if self.proposal(principal_id, link.proposal_id) is None:
            raise UnknownScopeError("proposal evidence names a proposal in this scope")
        if link.entity_observation_id is not None and (
            self.observation(principal_id, link.entity_observation_id) is None
        ):
            raise UnknownScopeError("proposal evidence cites a record outside this scope")
        self.proposal_evidence.append(link)

    def proposal_evidence_links(
        self, principal_id: str, proposal_id: str
    ) -> list[EntityProposalEvidenceLink]:
        return sorted(
            (
                link
                for link in self.proposal_evidence
                if link.principal_id == principal_id and link.proposal_id == proposal_id
            ),
            key=lambda link: link.sequence,
        )

    # --- deciding, and naming what the decision produced -------------------

    def decide_proposal(self, principal_id: str, proposal: EntityProposal) -> None:
        """`_Entities.decide_proposal`, with the widened predicate.

        The shared fake mirrors `state = 'proposed'`, which is what the guarded
        `UPDATE` carried before `initial_state_for` began writing
        `needs_review`. Overridden rather than left inherited, because a fake
        that refuses a decision on a `needs_review` proposal would make every
        promotion test prove the wrong thing.
        """
        self._world.fail("entities.decide_proposal")
        if proposal.principal_id != principal_id:
            raise ValueError("a proposal belongs to the acting Principal")
        for index, held in enumerate(self._world.entity_proposals):
            if held.proposal_id == proposal.proposal_id and held.principal_id == principal_id:
                if held.state not in UNDECIDED_PROPOSAL_STATES:
                    raise UnknownScopeError("a decision names an open proposal in this scope")
                self._world.entity_proposals[index] = proposal
                return
        raise UnknownScopeError("a decision names an open proposal in this scope")

    def record_proposal_promotion(
        self,
        principal_id: str,
        proposal_id: str,
        *,
        record_family: MutationRecordFamily,
        record_id: str,
        record_version: int,
    ) -> None:
        for index, held in enumerate(self._world.entity_proposals):
            if held.proposal_id != proposal_id or held.principal_id != principal_id:
                continue
            if held.state not in ACCEPTED_PROPOSAL_STATES or held.accepted_record_id is not None:
                break
            self._world.entity_proposals[index] = replace(
                held,
                accepted_record_type=record_family,
                accepted_record_id=record_id,
                accepted_record_version=record_version,
            )
            return
        raise UnknownScopeError("a promotion names an accepted proposal in this scope")

    def supersede_proposal(
        self,
        principal_id: str,
        proposal_id: str,
        *,
        successor_proposal_id: str,
        at: datetime,
    ) -> bool:
        for index, held in enumerate(self._world.entity_proposals):
            if held.proposal_id != proposal_id or held.principal_id != principal_id:
                continue
            if held.state not in UNDECIDED_PROPOSAL_STATES:
                return False
            self._world.entity_proposals[index] = replace(
                held,
                state=EntityProposalState.SUPERSEDED,
                superseded_at=ensure_utc(at),
                superseded_by_proposal_id=successor_proposal_id,
            )
            return True
        return False
