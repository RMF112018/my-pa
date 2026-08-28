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

**What accepting a merge does, and does not do — and what it used to do.**
`WP-RI-06` applied the merge here: accepting a `merge_entities` proposal
redirected the merged-away entity at the survivor and wrote the lineage record,
and its argument was that an entity which still resolves as a `HISTORICAL_MATCH`
is how a merge stays reversible, section 15.3 asking a merge to preserve prior
identifiers as lineage. That half is still true and is now `WP-RI-B-06`'s to
honour. The other half was the defect: it made *accepting a proposal* be the
merge, so anything holding a reviewer's disposition held an identity-correction
authority, and the whole distance between a review decision and a permanent
identity join was one boolean this module asked its caller for.

So acceptance now records reviewed intent, and only that. Accepting a
`merge_entities` or a `split_identity` proposal writes the decision on the
proposal — who accepted it, when, and why — and touches neither entity's status,
redirect nor version. The identity change it asks for is a separate operator act
under `entity_identity_correction`: `entities.merge.preview` binds an operator to
exact entity versions and `entities.merge` applies what that preview bound. A
reviewer grant is not an identity-correction grant, and `review.decide` is not a
merge endpoint wearing another name.

**Stated plainly, because it bounds what this correction is:** no published
capability ever reached the applying code. The proposal methods here were called
by tests and by nothing else, so this closes an unpublished path before it is
published rather than withdrawing behaviour a caller could invoke.

**Promotion of the ordinary kinds is routed elsewhere and executed here, and
the division is deliberate.** `application.entity_promotion` answers *which*
canonical command an accepted proposal becomes, which record it changes, and
what evidence links have to follow it onto the fact it produces; that module
imports nothing that can reach a repository, so the routing cannot quietly
become the write. `accept` is where the write happens, through
`EntityAuthoringService`, `EntityDirectedService` and this module's own
`resolve_mention` -- the same three services a user's own request reaches, so
every protection they hold is inherited rather than reimplemented: Principal
isolation, the guarded `UPDATE` that enforces expected version, the active
partial uniques, evidence validation, the idempotency store, the mutation
ledger and the plane's stable errors.

**This module used to hold no authoring service, and that sentence was the
guard.** `WP-RI-B-05`'s first commit recorded it in as many words: "accepting a
proposal cannot itself write a canonical record" was a property of what this
module could reach. Making promotion execute changed that, and the honest
statement of what replaced it is narrower and stronger:

* *producing* still cannot reach a canonical write. `propose` and the five
  helpers it delegates to touch `record_proposal`,
  `record_proposal_evidence_link` and three reads, and nothing else;
  `tests/architecture/test_derivation_proposes_and_never_promotes` reads that
  off the source, and additionally requires the allowlist it measures against
  to be disjoint from every repository method that writes canonical fact.
* *accepting* can, and only through a service that requires a decided proposal
  in this Principal's partition and a `PromotionContext` the transport supplies.
* *identity correction* still cannot, from either. `merge_entities` and
  `split_identity` are refused by `promotion_for` and absent from its table, and
  `redirect_entity`/`record_merge` appear nowhere in this module -- which is the
  structural form of section 15 and is separately asserted.

**Promoted authority is `review_accepted` under `review_promotion`.** A promoted
alias recorded as `user_confirmed_assertion` would say the user asserted what a
source or a local model asserted; section 14 forbids exactly that, and the pair
travels on the write request so no writer has to be trusted to choose it.
`resolve_mention` derived the same pair from its `actor_class` before any of
this existed and is unchanged -- it is the precedent, not an exception.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, fields, replace
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any, Final

from my_pa.application.commands import (
    AddEntityAlias,
    BindEntityIdentifier,
    CreateEntity,
    CreateEntityAssignment,
    CreateEntityRelationship,
    EndEntityAssignment,
    EndEntityRelationship,
    ResolveUnresolvedMention,
    RetireEntityAlias,
    RetireEntityIdentifier,
    ReviseEntityAssignment,
    ReviseEntityRelationship,
    SupersedeEntityAlias,
    SupersedeEntityIdentifier,
    UpdateEntity,
)
from my_pa.application.entity_authoring import EntityAuthoringService
from my_pa.application.entity_directed import EntityDirectedService
from my_pa.application.entity_promotion import (
    PromotionCall,
    PromotionCommand,
    StaleTargetVersionError,
    UnpromotableProposalError,
    evidence_links_for,
    promotion_for,
    target_of,
)
from my_pa.contracts.ports import (
    DirectedReceipt,
    EntitiesRepository,
    EntityMutationAdmission,
    ProposalAdmissionConflictError,
    ProposalEvidenceConflictError,
    ProposalReviewScopeConflictError,
    ReviewDecisionRequest,
    ReviewRepository,
    SourceRepository,
)
from my_pa.domain.capture.proposal import ProposalState
from my_pa.domain.capture.review import (
    CorrectionPatch,
    Disposition,
    EntityProposalReviewDecision,
    ReviewConflictError,
    ReviewCorrectionError,
    ReviewDecision,
    ReviewNotFoundError,
)
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.operation import Capability
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.governance import (
    ACCEPTED_PROPOSAL_STATES,
    IDENTITY_CORRECTION_PROPOSAL_KINDS,
    OPEN_EQUIVALENT_PROPOSAL_STATES,
    UNDECIDED_PROPOSAL_STATES,
    ActorClass,
    EntityFactEvidenceLink,
    EntityGovernanceError,
    EntityMergeRecord,
    EntityMutationConflictError,
    EntityMutationEvent,
    EntityObservation,
    EntityProposal,
    EntityProposalEvidenceLink,
    EntityProposalKind,
    EntityProposalMethod,
    EntityProposalPayload,
    EntityProposalState,
    EntityResolutionDecision,
    EvidenceRole,
    MutationAuthority,
    MutationRecordFamily,
    ObservationAuthority,
    ObservationAuthorityError,
    ObservationKind,
    ObservationOrigin,
    ObservationState,
    ObservationTimeError,
    ResolutionDisposition,
    ReviewRequirement,
    StaleResolutionVersionError,
    capture_origin_triple,
    origin_of,
    requirement_for,
)
from my_pa.domain.relationship.normalization import NormalizationError, normalize_name
from my_pa.domain.relationship.proposal_payload import ProposalPayloadError, dedupe_digest
from my_pa.domain.relationship.resolution import EntityResolution, ResolutionOutcome
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "EntityGovernanceService",
    "EntityIdentityCorrectionHandoff",
    "EntityProposalReviewResult",
    "IdentityCorrectionHandoffState",
    "InvalidPromotionError",
    "MentionResolution",
    "ObservationAdmission",
    "ObserveCommand",
    "PromotionContext",
    "ProposalAdmission",
    "ProposalNotOpenError",
    "ProposalSuppressedError",
    "ProposedEvidence",
    "QuarantinedObservationError",
    "ResolutionNotPermittedError",
    "ResolveMentionCommand",
    "ReviewAuthorityError",
    "ReviewedPayloadSource",
    "UnknownEntityError",
    "UnknownObservationError",
]


class IdentityCorrectionHandoffState(StrEnum):
    """The sole honest state before a live, operator-bound preview exists."""

    OPERATOR_PREVIEW_REQUIRED = "operator_preview_required"


class ReviewedPayloadSource(StrEnum):
    """Which immutable review record supplies the effective intent."""

    PROPOSED = "proposed"
    CORRECTED = "corrected"


@dataclass(frozen=True, slots=True)
class EntityIdentityCorrectionHandoff:
    """Reviewed identity-correction intent awaiting a fresh operator preview.

    This is deliberately not an executable command. Proposal payloads carry no
    live versions, preview identifier, digest, idempotency key or authority, so
    acceptance cannot honestly claim the current world is still the world the
    producer observed. The separate operator-only preview owns those bindings
    and every stale/conflict refusal.

    ``effective_payload`` is the reviewer's validated correction for
    ``correct_and_accept`` and the producer's original payload otherwise. The
    stored proposal intentionally retains the original, so the effective value
    has to be captured while the decision service has both.
    """

    proposal_id: str
    proposal_kind: EntityProposalKind
    effective_payload: EntityProposalPayload = field(repr=False)
    effective_payload_source: ReviewedPayloadSource
    state: IdentityCorrectionHandoffState = IdentityCorrectionHandoffState.OPERATOR_PREVIEW_REQUIRED

    def __post_init__(self) -> None:
        validate_identifier(self.proposal_id, IdKind.ENTITY_PROPOSAL)
        if self.proposal_kind not in IDENTITY_CORRECTION_PROPOSAL_KINDS:
            raise ValueError("an identity-correction handoff names an identity-correction kind")
        if self.effective_payload.kind is not self.proposal_kind:
            raise ValueError("an identity-correction handoff carries its kind's payload")
        if not isinstance(self.effective_payload_source, ReviewedPayloadSource):
            raise ValueError("an identity-correction handoff names its reviewed payload source")
        if self.state is not IdentityCorrectionHandoffState.OPERATOR_PREVIEW_REQUIRED:
            raise ValueError("an identity-correction handoff always requires operator preview")


@dataclass(frozen=True, slots=True)
class EntityProposalReviewResult(ReviewDecision):
    """An Entity review decision plus its optional operator-only handoff."""

    identity_correction_handoff: EntityIdentityCorrectionHandoff | None = None


class UnknownObservationError(EntityGovernanceError):
    """No observation of that identifier exists in this Principal's partition.

    One error for "absent" and "somebody else's", because they have to be the
    same answer: an error that distinguished them would disclose that a foreign
    record exists to a caller who cannot read it.
    """


class UnknownEntityError(EntityGovernanceError):
    """No entity of that identifier exists in this Principal's partition.

    Separate from `UnknownObservationError` because the two name different
    fields, and a caller told the wrong one refreshes the wrong record. Foreign
    and absent are one answer here for the reason they are everywhere on this
    plane: an error that distinguished them would disclose that a record it
    cannot read exists.
    """


class QuarantinedObservationError(EntityGovernanceError):
    """A quarantined observation was asked to feed an identity decision.

    `ObservationState.QUARANTINED` says the observation itself is not
    trustworthy input, on the same terms `domain.extraction.quarantine` uses.
    Binding one to an entity would put untrusted input behind a canonical fact,
    so `link_existing` and `create_new` are refused on it while the three
    refusals stay available -- a quarantined mention can still be deferred,
    rejected, or quarantined again with a better reason.
    """


class ResolutionNotPermittedError(EntityGovernanceError):
    """The evidence does not support the disposition that was asked for.

    Carries `detail`, a short pre-categorised token naming *which* rule refused,
    so the transport can map it onto the contract's stable problem codes without
    parsing a sentence. The tokens are the contract's own:
    `ambiguous_identity`, `conflicted_identifier`, `historical_entity`,
    `review_required` and `evidence_invalid`.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ReviewAuthorityError(Exception):
    """A decision was attempted without the authority the proposal requires."""


class ProposalSuppressedError(EntityGovernanceError):
    """A proposal repeats a claim whose whole basis has already been refused.

    Its own error rather than a silent no-op or a dedupe answer, because the
    three are different facts and a producer told the wrong one behaves wrongly:
    "already open" means wait, "recorded" means a reviewer will see it, and this
    means the grounds were refused and re-offering the same ones will be refused
    again. Names the rule and never the pairing — the entity a citation was
    refused against is exactly the kind of detail a refusal must not disclose to
    a caller that could not otherwise read it.
    """


class ProposalNotOpenError(Exception):
    """A decision was attempted on a proposal that has already been decided.

    Its own error rather than a silent no-op, because "this was already
    accepted" and "this is now accepted" are different facts and a caller acting
    on the second when the first is true has lost track of who decided what.
    """


class InvalidPromotionError(EntityGovernanceError):
    """An acceptance asked to be promoted and this module cannot carry it out.

    Distinct from `entity_promotion.PromotionError` and its two subclasses,
    which say something about the *proposal*: that it names no canonical
    mutation, or that the record it changes has moved. This one says something
    about the *request to promote* -- a context missing the one thing a kind
    needs, most concretely a `resolve_mention` promotion with no fresh
    resolution to veto the binding with. Telling the two apart matters because
    only one of them is fixed by looking at the world again.
    """


@dataclass(frozen=True, slots=True)
class ProposedEvidence:
    """One exact record a producer offers in support of, or against, a proposal.

    A carrier rather than `EntityProposalEvidenceLink` itself, and the two
    fields it does *not* have are the reason: the proposal identifier is minted
    by `propose` after this is handed over, and `sequence` is the server's
    ordering. A producer that could choose either could file evidence against a
    proposal it did not make, or renumber somebody else's citation.

    `role` is the producer's to state, because a producer that read an
    observation contradicting its own candidate has said something worth
    recording and `EvidenceRole.COUNTEREVIDENCE` is where it goes. The record
    still refuses more or fewer than one named target.
    """

    role: EvidenceRole
    entity_observation_id: str | None = None
    capture_span_id: str | None = None
    knowledge_id: str | None = None


@dataclass(frozen=True, slots=True)
class PromotionContext:
    """What only the promoting transaction can supply, handed to `accept`.

    Absent from `PromotionCall` on purpose -- `entity_promotion`'s own docstring
    argues it, and the argument is that these belong to the moment of promotion
    rather than to the proposal. An idempotency key derived from the proposal
    would make a reviewer's second, corrected decision replay the first one's
    receipt; a correlation and an audit identifier belong to the request that is
    happening now.

    `resolve` is the fresh resolution `resolve_mention` runs *inside* this
    transaction, and it is required only for that one kind. It is a veto rather
    than a licence: it can refuse a binding against the state that exists now --
    a conflicted identifier, a historical match -- and it cannot license one. A
    `resolve_mention` promotion arriving without it is refused rather than
    performed unchecked, which is why the field is optional and its absence is
    an error rather than a default.

    Passing this to `accept` is what makes promotion happen; omitting it records
    the acceptance and writes no canonical record, which is the behaviour every
    caller had before promotion could execute.
    """

    correlation_id: str
    audit_id: str
    idempotency_key: str
    at: datetime
    resolve: _FreshResolution | None = None


@dataclass(frozen=True, slots=True)
class _PromotedRecord:
    """The canonical record one promotion produced, as the proposal will name it."""

    record_family: MutationRecordFamily
    record_id: str
    record_version: int


class EntityGovernanceService:
    """Records observations, proposes changes, and applies decided ones."""

    def __init__(self, entities: EntitiesRepository) -> None:
        self._entities = entities
        # Constructed rather than injected, because both are stateless routers
        # that take their repository per call -- there is no wiring for a
        # composition root to get wrong, and a constructor argument would make
        # every existing `EntityGovernanceService(unit_of_work.entities)` call
        # site have to know about promotion. They are held privately: nothing
        # outside `_execute` reaches either, and `propose` cannot reach them at
        # all, which the architecture guard reads off the source.
        self._authoring = EntityAuthoringService()
        self._directed = EntityDirectedService()

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

    def unresolved_mentions(
        self, principal_id: str, *, limit: int | None = None
    ) -> list[EntityObservation]:
        """Every observation nothing has linked to an entity.

        A first-class queue rather than a gap in the data (`RI-AC-006`): these
        are the references the system knows it has not placed, and being able to
        list them is what makes "unresolved" a state rather than an absence.

        `limit` defaults to `None`, which is genuinely unbounded and is the
        right default *here*: this is the queue, and a caller shown a truncated
        queue with nothing saying so would believe it had reached the end. Every
        other read of this table caps itself, because it is the one collection
        on this plane that grows with every source record that ever mentioned
        anyone. A caller that would rather page than wait passes a limit and
        knows it did.
        """
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        return self._entities.observations(principal_id, unresolved_only=True, limit=limit)

    def link(self, principal_id: str, observation_id: str, entity_id: str) -> None:
        """Attach one observation to the entity it turned out to refer to."""
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        self._entities.link_observation(principal_id, observation_id, entity_id)

    # --- proposal ---------------------------------------------------------

    def propose(
        self,
        principal_id: str,
        *,
        kind: EntityProposalKind,
        payload: Mapping[str, str | bool],
        observation_ids: tuple[str, ...],
        proposed_by: str,
        method: EntityProposalMethod,
        method_version: str,
        at: datetime,
        evidence: Sequence[ProposedEvidence] = (),
        model_id: str | None = None,
        model_version: str | None = None,
        expected_target_version: int | None = None,
    ) -> ProposalAdmission:
        """Record a proposed mutation, or hand back the open one that already says it.

        The application behaviour behind `entities.proposals.create`, and the
        only way a proposal is written. There is no second entry point that
        skips the checks below, because a producer path with a weaker sibling is
        a producer path whose rules are optional.

        **What the caller supplies is what a producer could legitimately have
        decided**: which mutation it is asking for, the fields of that mutation,
        which observations it read, and — from authenticated context rather than
        from a payload — what produced it. Everything else is decided here. The
        identifier is minted, the state is the initial one, the moment is the
        server's clock, and the dedupe digest is derived: a caller that could
        name the digest could name one nothing would collide with, and
        open-equivalent dedupe would then be over a value the proposer chose.
        `EntityProposalPayload` refuses the rest by field name, so a payload
        carrying `principal_id`, `method`, `authority` or an idempotency key is
        refused before this method has a proposal to record.

        **Evidence is checked against this Principal's partition before it is
        cited.** An observation that is absent and one that is somebody else's
        are the same refusal here for the reason they are everywhere on this
        plane. A quarantined observation is refused outright: `resolve_mention`
        already refuses to let one bind an entity, and a proposal *is* a request
        to bind one.

        **An open-equivalent proposal is returned rather than multiplied.** Two
        producers reaching the same conclusion have proposed the change once, and
        a reviewer shown it twice has to decide the same thing twice. The
        returned admission says `created=False`, so a caller can tell "recorded"
        from "already open" without the two being one answer.

        **A review case is opened here for every kind.** No automatic promoter is
        configured in this build, so a threshold-eligible proposal without a case
        would be stranded outside every executable path. The producer cannot
        supply the case identifier; the server mints and returns it as part of
        the canonical receipt so the proposal can be correlated with Review.

        No mutation-ledger row is written, and that is the ledger's own rule
        rather than an omission — `MutationRecordFamily` holds the six canonical
        families and deliberately excludes proposals, because a ledger that
        recorded requests would record the asking as if it were the doing.
        """
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        checked = EntityProposalPayload.of(kind, payload)
        typed_observation_ids = tuple(
            offered.entity_observation_id
            for offered in evidence
            if offered.entity_observation_id is not None
        )
        suppression_observation_ids = tuple(
            dict.fromkeys([*observation_ids, *typed_observation_ids])
        )
        self._admit_evidence(principal_id, suppression_observation_ids)
        # Suppression is decided before dedupe, and the order is deliberate: a
        # producer re-filing evidence a reviewer has already refused is told so,
        # rather than being told what is currently open in a queue it does not
        # decide.
        self._refuse_a_known_bad_proposal(principal_id, checked, suppression_observation_ids)
        digest = dedupe_digest(checked)
        open_equivalent = self._open_equivalent(principal_id, digest)
        if open_equivalent is not None:
            self._record_evidence(principal_id, open_equivalent, evidence, at=ensure_utc(at))
            return _admission(open_equivalent, created=False)
        proposal = EntityProposal(
            proposal_id=issue_identifier(IdKind.ENTITY_PROPOSAL),
            principal_id=principal_id,
            kind=kind,
            # Every producer proposal waits on the canonical Review plane. The
            # configured automatic promoter Phase B would need does not exist,
            # so leaving threshold-eligible kinds in `proposed` would strand
            # them outside every executable path.
            state=EntityProposalState.NEEDS_REVIEW,
            payload=checked,
            observation_ids=observation_ids,
            proposed_at=ensure_utc(at),
            proposed_by=proposed_by,
            method=method,
            method_version=method_version,
            dedupe_sha256=digest,
            model_id=model_id,
            model_version=model_version,
            expected_target_version=expected_target_version,
            review_case_id=_review_case_for(kind),
        )
        try:
            self._entities.record_proposal(principal_id, proposal)
        except ProposalAdmissionConflictError:
            concurrent = self._open_equivalent(principal_id, digest)
            if concurrent is None:
                raise
            self._record_evidence(principal_id, concurrent, evidence, at=proposal.proposed_at)
            return _admission(concurrent, created=False)
        self._record_evidence(principal_id, proposal, evidence, at=proposal.proposed_at)
        return _admission(proposal, created=True)

    def _record_evidence(
        self,
        principal_id: str,
        proposal: EntityProposal,
        evidence: Sequence[ProposedEvidence],
        *,
        at: datetime,
    ) -> None:
        """Write the exact records this proposal rests on, in the order it cited them.

        **Two sources, one table, and the numbering says which came first.**
        Every observation on `observation_ids` becomes a `DIRECT` link, because
        a producer citing an observation for its own candidate is saying "this
        is why" — the same role, for the same reason, that the canonical write
        path gives the evidence a caller attaches to its own write. Anything the
        producer states explicitly follows, keeping the role it stated, which is
        how a capture span, a knowledge record or a piece of counterevidence
        gets cited at all: `observation_ids` is a JSONB array of one identifier
        kind and can carry none of the three.

        The array is still written and is not replaced here. Dropping it is not
        an additive migration and every other writer of it belongs to Phase A;
        the table's own docstring records that the two surfaces coexist until
        those writers move.

        Each link is admitted by the repository against this Principal's
        partition before it is written — a foreign observation and an absent one
        answer alike — so a producer cannot cite its way into another
        partition's evidence.
        """
        cited = [
            ProposedEvidence(role=EvidenceRole.DIRECT, entity_observation_id=observation_id)
            for observation_id in proposal.observation_ids
        ]
        try:
            self._entities.merge_proposal_evidence_links(
                principal_id,
                proposal.proposal_id,
                (
                    EntityProposalEvidenceLink(
                        proposal_id=proposal.proposal_id,
                        principal_id=principal_id,
                        sequence=sequence,
                        role=offered.role,
                        created_at=at,
                        entity_observation_id=offered.entity_observation_id,
                        capture_span_id=offered.capture_span_id,
                        knowledge_id=offered.knowledge_id,
                    )
                    for sequence, offered in enumerate([*cited, *evidence], start=1)
                ),
            )
        except ProposalEvidenceConflictError as exc:
            raise ProposalNotOpenError(
                "this proposal stopped being open while evidence was appended"
            ) from exc

    def _admit_evidence(self, principal_id: str, observation_ids: tuple[str, ...]) -> None:
        """Refuse a citation this Principal cannot make. See `propose`."""
        for observation_id in observation_ids:
            held = self._entities.observation(principal_id, observation_id)
            if held is None:
                raise UnknownObservationError("no such observation in this scope")
            if held.state is ObservationState.QUARANTINED:
                raise QuarantinedObservationError(
                    "a quarantined observation does not evidence a proposal"
                )

    def _refuse_a_known_bad_proposal(
        self,
        principal_id: str,
        payload: EntityProposalPayload,
        observation_ids: tuple[str, ...],
    ) -> None:
        """Refuse a proposal every one of whose citations has already been refused.

        This is what makes a rejection do more than sit in a table.
        `OPEN_EQUIVALENT_PROPOSAL_STATES` deliberately excludes `REJECTED` and
        `INVALIDATED` so that a refused claim *can* be raised again — but only on
        new grounds, because a unique index cannot tell a producer that its basis
        has changed and only the evidence can.

        So the rule is over the evidence rather than over the digest: if this
        proposal names a target entity and every observation it cites is already
        recorded as counterevidence against that entity, it is the same claim on
        the same grounds and is refused. One citation that has not been refused
        is genuinely new grounds and the proposal is admitted — which is the
        whole of "unless genuinely new evidence invalidates the prior basis", and
        is why a proposal citing nothing is never suppressed: it has no basis to
        have been refused.
        """
        target = payload.as_mapping().get("entity_id")
        if not isinstance(target, str) or not observation_ids:
            return
        if all(
            target in self._refused_pairings(principal_id, observation_id)
            for observation_id in observation_ids
        ):
            raise ProposalSuppressedError(
                "this pairing has already been refused on every citation offered"
            )

    def _open_equivalent(self, principal_id: str, digest: str) -> EntityProposal | None:
        """The open proposal this digest already has, if any.

        One read, keyed on `(principal_id, dedupe_sha256)` — the columns
        `an_open_equivalent_proposal_is_raised_once` is already over. This was a
        loop over `proposals(principal_id, state)` for each of the three
        open-equivalent states with the digests compared in Python, which was
        correct and was a scan of every open proposal on every create; the
        repository read that replaced it changes the shape and not the answer.

        The states are passed rather than known by the port, so widening
        `OPEN_EQUIVALENT_PROPOSAL_STATES` is a change here and not a change to
        the port. The index remains the authority either way: this read is what
        turns a would-be integrity error into the open proposal the producer was
        going to be told about.
        """
        return self._entities.proposal_by_dedupe(
            principal_id, digest, sorted(OPEN_EQUIVALENT_PROPOSAL_STATES)
        )

    def open_proposals(self, principal_id: str) -> list[EntityProposal]:
        """Everything awaiting a decision, in both of the states that means.

        Two reads rather than one, because `EntitiesRepository.proposals`
        filters by a single state and `UNDECIDED_PROPOSAL_STATES` names two
        since `initial_state_for` began writing `NEEDS_REVIEW`. Reading only
        `proposed` would have made this method answer "everything awaiting a
        decision" with the subset of it that no person has to look at — the
        opposite of the queue a reviewer wants — and the states are what tells
        those two queues apart.

        Sorted by identifier so the concatenation of two partitioned reads is
        one stable order rather than one order per state.
        """
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        held = [
            proposal
            for state in UNDECIDED_PROPOSAL_STATES
            for proposal in self._entities.proposals(principal_id, state=state)
        ]
        return sorted(held, key=lambda proposal: proposal.proposal_id)

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

    def defer(
        self,
        principal_id: str,
        proposal_id: str,
        *,
        decided_by: str,
        decided_at: datetime,
        reason: str,
    ) -> EntityProposal:
        """Push a proposal out without refusing it. Needs no authority, like `reject`.

        `DEFERRED` is in `OPEN_EQUIVALENT_PROPOSAL_STATES` and not in
        `UNDECIDED_PROPOSAL_STATES`, and both memberships are the point: a
        producer cannot clear a deferral by re-filing the same candidate, and a
        reviewer cannot decide the same case twice. Reopening a deferred case is
        a widening of `UNDECIDED_PROPOSAL_STATES` that nothing in this package
        needs, so it is not made.
        """
        return self._decide(
            principal_id,
            proposal_id,
            state=EntityProposalState.DEFERRED,
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
        promotion: PromotionContext | None = None,
        corrected_payload: EntityProposalPayload | None = None,
    ) -> EntityProposal:
        """Record that a proposal was accepted, and carry it out if asked to.

        `has_operator_authority` is a parameter the caller must pass rather than
        anything this module can infer. A `REQUIRES_OPERATOR` proposal — today, a
        merge or a split — is refused without it, and that refusal is about who
        may *record the acceptance*: what the acceptance establishes is reviewed
        identity-correction intent, and the identity change it asks for is a
        separate act under a separate capability. See the module docstring for
        the division and for what this method used to do instead.

        **The decision is claimed before anything is written, and the order is
        the whole safety argument.** `_decide`'s guarded `UPDATE` is what makes
        deciding a one-time act; running it first means two reviewers racing on
        one proposal produce one decision and one promotion, and the loser
        writes nothing at all. Promoting first and deciding afterwards would let
        both write a canonical record and only then discover that one of them
        had no acceptance behind it.

        **`promotion` is what makes the acceptance execute.** Omitting it
        records the decision and writes no canonical record, which is what every
        caller got before promotion could execute and is still the right answer
        for a caller that only wants the decision. Supplying it routes the
        proposal through `entity_promotion` to the canonical Phase A service
        that performs its kind, under `review_accepted`/`review_promotion`, and
        then names the record it produced on the proposal.

        **An identity correction is not promoted, and supplying a context does
        not change that.** `merge_entities` and `split_identity` are refused by
        the routing and are skipped here before it is consulted, so a reviewer
        holding a promotion context still cannot reach a merge: section 15's
        division is a property of the kind rather than of what the caller asked
        for. The acceptance is recorded exactly as it was.

        **Everything a promotion writes is in this transaction.** The canonical
        write, the evidence links that follow the proposal onto the fact, and
        the `accepted_record_*` naming are three statements after the decision,
        and any of them failing takes the decision with it — so an acceptance
        that names no record is one nobody made, rather than one that half
        happened.

        **`corrected_payload` is what `correct_and_accept` promotes, and it never
        overwrites what was proposed.** The stored proposal keeps the producer's
        own payload: it is the assertion the decision was taken against, and
        `dedupe_sha256` is a digest over that kind and that payload, so writing
        the reviewer's version over it would leave the digest describing
        something nobody proposed and would rewrite the record the reviewer
        disagreed with. The decision ledger holds the correction; this promotes
        it; the state becomes `corrected_accepted`, which is how a later reader
        knows to look for one.
        """
        corrected = corrected_payload is not None
        if promotion is None:
            held_for_promotion = self._entities.proposal(principal_id, proposal_id)
            if (
                held_for_promotion is not None
                and held_for_promotion.kind not in IDENTITY_CORRECTION_PROPOSAL_KINDS
            ):
                raise InvalidPromotionError(
                    "an ordinary accepted proposal requires canonical promotion"
                )
        decided = self._decide(
            principal_id,
            proposal_id,
            state=(
                EntityProposalState.CORRECTED_ACCEPTED
                if corrected
                else EntityProposalState.ACCEPTED
            ),
            decided_by=decided_by,
            decided_at=decided_at,
            reason=reason,
            has_operator_authority=has_operator_authority,
        )
        if corrected_payload is not None and corrected_payload.kind is not decided.kind:
            # Checked after the decision rather than before it, because only the
            # stored proposal says what kind it is and a caller-stated kind would
            # be the caller choosing which schema its correction was checked
            # against. `EntityProposal` refuses the same mismatch on its own
            # payload; this is that rule applied to the reviewer's.
            raise InvalidPromotionError("a correction is a correction of its proposal's own kind")
        if promotion is None or decided.kind in IDENTITY_CORRECTION_PROPOSAL_KINDS:
            return decided
        promoted = self._promote(
            decided if corrected_payload is None else replace(decided, payload=corrected_payload),
            principal_id=principal_id,
            decided_by=decided_by,
            promotion=promotion,
        )
        self._entities.record_proposal_promotion(
            principal_id,
            decided.proposal_id,
            record_family=promoted.record_family,
            record_id=promoted.record_id,
            record_version=promoted.record_version,
        )
        return replace(
            decided,
            accepted_record_type=promoted.record_family,
            accepted_record_id=promoted.record_id,
            accepted_record_version=promoted.record_version,
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
    ) -> EntityProposal:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        held = self._entities.proposal(principal_id, proposal_id)
        if held is None:
            raise ProposalNotOpenError("no such proposal in this scope")
        if not held.is_open:
            raise ProposalNotOpenError("this proposal has already been decided")
        if not decided_by.strip():
            raise ValueError("a decision names who made it")

        # Both accepting states, and the widening is load-bearing rather than
        # tidy: `correct_and_accept` writes `corrected_accepted`, and a check
        # that named only `accepted` would have let a corrected acceptance of a
        # merge proposal past the operator gate that an ordinary acceptance of
        # the same proposal is refused by.
        accepting = state in ACCEPTED_PROPOSAL_STATES
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
            method=held.method,
            method_version=held.method_version,
            dedupe_sha256=held.dedupe_sha256,
            model_id=held.model_id,
            model_version=held.model_version,
            expected_target_version=held.expected_target_version,
            review_case_id=held.review_case_id,
            decided_by=decided_by,
            decided_at=ensure_utc(decided_at),
            decision_reason=reason,
        )
        # The decision, and no second write. There is no `_apply` step between
        # these two lines any more; the module docstring records what used to be
        # here and why it moved.
        self._entities.decide_proposal(principal_id, decided)
        return decided

    # --- promotion: carrying out what a reviewer accepted --------------------

    def _promote(
        self,
        proposal: EntityProposal,
        *,
        principal_id: str,
        decided_by: str,
        promotion: PromotionContext,
    ) -> _PromotedRecord:
        """Execute one accepted proposal through the service that owns its mutation.

        Four steps and no fifth. `promotion_for` says which canonical command
        this is and refuses anything that is not an accepted ordinary kind;
        `_promotion_arguments` supplies the versions and the key that only this
        moment can; the command's own constructor re-checks every value it was
        handed; `_execute` hands it to the canonical service. Nothing here
        decides what a duplicate is, what a stale version is, or whether an
        entity may be written — those live where they already lived.

        **The evidence follows the fact.** `evidence_links_for` builds the links
        that carry the proposal's cited observations onto the record it became,
        which is section 14's "evidence links must survive promotion", and they
        are written after the canonical write because the record they point at
        has to exist first. The `OBSERVATION` family is skipped rather than
        linked: a `resolve_mention` promotion's subject *is* an observation, and
        that decision's evidence is written by `resolve_mention` itself onto
        `entity_resolution_decisions.evidence_link_ids`.
        """
        call = promotion_for(proposal)
        arguments = self._promotion_arguments(principal_id, proposal, call, promotion=promotion)
        promoted = self._execute(
            call.command(**arguments),
            principal_id=principal_id,
            decided_by=decided_by,
            promotion=promotion,
        )
        if promoted.record_family is not MutationRecordFamily.OBSERVATION:
            for link in evidence_links_for(
                self._entities.proposal_evidence_for(principal_id, proposal.proposal_id),
                principal_id=principal_id,
                record_family=promoted.record_family,
                record_id=promoted.record_id,
                at=promotion.at,
            ):
                self._entities.record_fact_evidence_link(principal_id, link)
        return promoted

    def _promotion_arguments(
        self,
        principal_id: str,
        proposal: EntityProposal,
        call: PromotionCall,
        *,
        promotion: PromotionContext,
    ) -> dict[str, Any]:
        """The proposal's own fields, plus the versions and the key it may not carry.

        **Every expected version is read now, and none is replayed from proposal
        time.** A version a producer read when it filed a candidate and a
        reviewer accepted a week later is a stale-write check that has stopped
        checking: it would either refuse every promotion of an entity anybody
        else touched in between, or — if the record had moved back — pass while
        checking nothing. So the current version of each record the command
        expects is read inside this transaction, and the guarded `UPDATE` in the
        repository is still what settles a writer racing this one.

        **`expected_target_version` is the reviewer's stale check, and it is
        checked here rather than passed through.** Section 27: a stale target
        version prevents promotion. When the proposal states one it must equal
        the current version of the record its kind changes, and promotion is
        refused otherwise — which is a different answer from the canonical
        service's, and a better one, because it names the proposal's own
        expectation rather than a version the caller never chose. When the
        proposal states none the check has nothing to compare: `entity_proposals`
        makes the column nullable, `entities.proposals.create` publishes it as
        optional, and a creating kind has no record to have read a version of.

        **Which expectation is about which record is derived, not tabulated.**
        The names are read off the command's own fields, so a command that grows
        or loses one is answered here without a second table having to be
        edited in step. `expected_version` is the only ambiguous one and its two
        readings are exactly the two write planes: on the authoring plane the
        entity is the aggregate and its version is what every operation expects,
        including the child ones; on the directed plane it is the assignment's
        or the edge's own. `AssignmentWriteRequest` and `EntityWriteRequest` say
        so in those words, and `call.record_family` is what tells them apart.
        """
        arguments: dict[str, Any] = dict(call.fields)
        arguments["idempotency_key"] = promotion.idempotency_key
        target = target_of(proposal)
        target_version: int | None = None
        if target is not None:
            record, record_id = target
            target_version = self._current_version(
                principal_id, record.family, record_id, arguments
            )
            if (
                proposal.expected_target_version is not None
                and proposal.expected_target_version != target_version
            ):
                raise StaleTargetVersionError(
                    "the record this proposal changes has moved since it was proposed"
                )
        child_planes = (MutationRecordFamily.ASSIGNMENT, MutationRecordFamily.RELATIONSHIP)
        for expectation in (
            declared.name
            for declared in fields(call.command)
            if declared.name.startswith("expected_")
        ):
            if expectation == "expected_version":
                arguments[expectation] = (
                    target_version
                    if call.record_family in child_planes
                    else self._entity_version(principal_id, arguments["entity_id"])
                )
            elif expectation == "expected_entity_version":
                arguments[expectation] = self._optional_entity_version(
                    principal_id, arguments.get("entity_id")
                )
            elif expectation == "expected_scope_version":
                arguments[expectation] = self._optional_entity_version(
                    principal_id, arguments.get("scope_entity_id")
                )
            elif expectation == "expected_from_version":
                arguments[expectation] = self._entity_version(
                    principal_id, arguments["from_entity_id"]
                )
            elif expectation == "expected_to_version":
                arguments[expectation] = self._entity_version(
                    principal_id, arguments["to_entity_id"]
                )
            else:
                # `expected_identifier_version`, `expected_alias_version` and
                # `expected_resolution_version`: each is the version of the one
                # record its kind changes, which is what `target_of` names.
                arguments[expectation] = target_version
        return arguments

    def _current_version(
        self,
        principal_id: str,
        family: MutationRecordFamily,
        record_id: str,
        arguments: Mapping[str, Any],
    ) -> int:
        """The version the record this proposal changes carries right now.

        The parent entity is read from the payload for a child record rather
        than from the child, because the schemas for those kinds name both and
        a read that took the parent from the row would follow a redirect this
        method has no disposition for.
        """
        if family is MutationRecordFamily.ENTITY:
            return self._entity_version(principal_id, record_id)
        if family is MutationRecordFamily.IDENTIFIER:
            for identifier in self._entities.external_identifiers(
                principal_id, arguments["entity_id"]
            ):
                if identifier.identifier_id == record_id:
                    return identifier.version
            raise UnpromotableProposalError("no such external identifier in this scope")
        if family is MutationRecordFamily.ALIAS:
            for alias in self._entities.aliases(principal_id, arguments["entity_id"]):
                if alias.alias_id == record_id:
                    return alias.version
            raise UnpromotableProposalError("no such alias in this scope")
        if family is MutationRecordFamily.ASSIGNMENT:
            assignment = self._entities.assignment(principal_id, record_id)
            if assignment is None:
                raise UnpromotableProposalError("no such assignment in this scope")
            return assignment.version
        if family is MutationRecordFamily.RELATIONSHIP:
            relationship = self._entities.relationship(principal_id, record_id)
            if relationship is None:
                raise UnpromotableProposalError("no such relationship in this scope")
            return relationship.version
        held = self._entities.observation(principal_id, record_id)
        if held is None:
            raise UnknownObservationError("no such observation in this scope")
        return held.resolution_version

    def _entity_version(self, principal_id: str, entity_id: object) -> int:
        """The version of one entity this Principal holds, or a refusal naming the scope.

        A foreign entity and an absent one answer alike, which is the rule the
        rest of this plane follows and is why the read is Principal-scoped
        rather than filtered afterwards.
        """
        if not isinstance(entity_id, str):
            raise UnpromotableProposalError("a proposal names the entity it is about")
        entity = self._entities.get(principal_id, entity_id)
        if entity is None:
            raise UnknownEntityError("no such entity in this scope")
        return entity.version

    def _optional_entity_version(self, principal_id: str, entity_id: object) -> int | None:
        """`_entity_version`, or `None` where the command's field is optional."""
        return None if entity_id is None else self._entity_version(principal_id, entity_id)

    def _execute(
        self,
        command: PromotionCommand,
        *,
        principal_id: str,
        decided_by: str,
        promotion: PromotionContext,
    ) -> _PromotedRecord:
        """Hand one constructed command to the canonical service that performs it.

        **Fifteen branches and no mutation logic in any of them.** Each one
        forwards the command's fields to the service method whose capability
        performs that kind, adds the Principal and the request identities, and
        returns what the receipt says was written. That is deliberately the same
        shape `application.service`'s handlers have — the alternative was a
        promotion path that reached the repository directly, which is the second
        copy of the mutation section 14 forbids.

        **The authority pair is stamped once, here, and is the same for every
        branch.** `review_accepted` under `review_promotion`: a reviewer
        accepted somebody else's assertion, which is neither the user having
        asserted it nor a conclusion that could be recomputed.

        `resolve_mention` is this module's own method rather than one of the two
        services, and it derived the same pair from `actor_class` before any of
        this existed. It needs the fresh resolution the transport supplies,
        because that veto runs against the state that exists now rather than the
        state the queue was rendered from.
        """
        authoring: dict[str, Any] = {
            "principal_id": principal_id,
            "correlation_id": promotion.correlation_id,
            "audit_id": promotion.audit_id,
            "at": promotion.at,
            "authority": MutationAuthority.REVIEW_ACCEPTED,
            "actor_class": ActorClass.REVIEW_PROMOTION,
        }
        directed: dict[str, Any] = {
            "principal_id": principal_id,
            "audit_id": promotion.audit_id,
            "at": promotion.at,
            "authority": MutationAuthority.REVIEW_ACCEPTED,
            "actor_class": ActorClass.REVIEW_PROMOTION,
        }
        match command:
            case CreateEntity():
                return _from_receipt(
                    self._authoring.create(
                        self._entities,
                        entity_type=command.entity_type,
                        display_name=command.display_name,
                        # Always empty, and stated rather than forwarded.
                        # `create_entity`'s payload schema admits neither field,
                        # because a create carrying three aliases would put four
                        # separate assertions, each resting on its own evidence,
                        # under one reviewer's single accept.
                        aliases=(),
                        identifiers=(),
                        reason=command.reason,
                        idempotency_key=command.idempotency_key,
                        **authoring,
                    )
                )
            case UpdateEntity():
                return _from_receipt(
                    self._authoring.update(
                        self._entities,
                        entity_id=command.entity_id,
                        expected_version=command.expected_version,
                        display_name=command.display_name,
                        canonical_name=command.canonical_name,
                        status=command.status,
                        reason=command.reason,
                        idempotency_key=command.idempotency_key,
                        **authoring,
                    )
                )
            case BindEntityIdentifier():
                return _from_receipt(
                    self._authoring.bind_identifier(
                        self._entities,
                        entity_id=command.entity_id,
                        expected_version=command.expected_version,
                        namespace=command.namespace,
                        display_value=command.display_value,
                        effective_from=command.effective_from,
                        effective_to=command.effective_to,
                        evidence=command.evidence,
                        reason=command.reason,
                        idempotency_key=command.idempotency_key,
                        **authoring,
                    )
                )
            case RetireEntityIdentifier():
                return _from_receipt(
                    self._authoring.retire_identifier(
                        self._entities,
                        entity_id=command.entity_id,
                        expected_version=command.expected_version,
                        identifier_id=command.identifier_id,
                        expected_identifier_version=command.expected_identifier_version,
                        reason=command.reason,
                        idempotency_key=command.idempotency_key,
                        **authoring,
                    )
                )
            case SupersedeEntityIdentifier():
                return _from_receipt(
                    self._authoring.supersede_identifier(
                        self._entities,
                        entity_id=command.entity_id,
                        expected_version=command.expected_version,
                        identifier_id=command.identifier_id,
                        expected_identifier_version=command.expected_identifier_version,
                        namespace=command.namespace,
                        display_value=command.display_value,
                        effective_from=command.effective_from,
                        effective_to=command.effective_to,
                        evidence=command.evidence,
                        reason=command.reason,
                        idempotency_key=command.idempotency_key,
                        **authoring,
                    )
                )
            case AddEntityAlias():
                return _from_receipt(
                    self._authoring.add_alias(
                        self._entities,
                        entity_id=command.entity_id,
                        expected_version=command.expected_version,
                        alias_type=command.alias_type,
                        display_value=command.display_value,
                        effective_from=command.effective_from,
                        effective_to=command.effective_to,
                        evidence=command.evidence,
                        reason=command.reason,
                        idempotency_key=command.idempotency_key,
                        **authoring,
                    )
                )
            case RetireEntityAlias():
                return _from_receipt(
                    self._authoring.retire_alias(
                        self._entities,
                        entity_id=command.entity_id,
                        expected_version=command.expected_version,
                        alias_id=command.alias_id,
                        expected_alias_version=command.expected_alias_version,
                        reason=command.reason,
                        idempotency_key=command.idempotency_key,
                        **authoring,
                    )
                )
            case SupersedeEntityAlias():
                return _from_receipt(
                    self._authoring.supersede_alias(
                        self._entities,
                        entity_id=command.entity_id,
                        expected_version=command.expected_version,
                        alias_id=command.alias_id,
                        expected_alias_version=command.expected_alias_version,
                        alias_type=command.alias_type,
                        display_value=command.display_value,
                        effective_from=command.effective_from,
                        effective_to=command.effective_to,
                        evidence=command.evidence,
                        reason=command.reason,
                        idempotency_key=command.idempotency_key,
                        **authoring,
                    )
                )
            case CreateEntityAssignment():
                return _from_directed(
                    self._directed.create_assignment(self._entities, command, **directed)
                )
            case ReviseEntityAssignment():
                return _from_directed(
                    self._directed.revise_assignment(self._entities, command, **directed)
                )
            case EndEntityAssignment():
                return _from_directed(
                    self._directed.end_assignment(self._entities, command, **directed)
                )
            case CreateEntityRelationship():
                return _from_directed(
                    self._directed.create_relationship(self._entities, command, **directed)
                )
            case ReviseEntityRelationship():
                return _from_directed(
                    self._directed.revise_relationship(self._entities, command, **directed)
                )
            case EndEntityRelationship():
                return _from_directed(
                    self._directed.end_relationship(self._entities, command, **directed)
                )
            case ResolveUnresolvedMention():
                if promotion.resolve is None:
                    raise InvalidPromotionError(
                        "promoting a mention resolution needs a fresh resolution to check it"
                    )
                outcome = self.resolve_mention(
                    ResolveMentionCommand(
                        principal_id=principal_id,
                        observation_id=command.observation_id,
                        expected_resolution_version=command.expected_resolution_version,
                        disposition=command.disposition,
                        idempotency_key=command.idempotency_key,
                        entity_id=command.entity_id,
                        expected_entity_version=command.expected_entity_version,
                        entity_type=command.entity_type,
                        canonical_name=command.canonical_name,
                        display_name=command.display_name,
                        rejected_entity_id=command.rejected_entity_id,
                        reason=command.reason,
                    ),
                    resolve=promotion.resolve,
                    at=promotion.at,
                    correlation_id=promotion.correlation_id,
                    audit_id=promotion.audit_id,
                    decided_by=decided_by,
                    actor_class=ActorClass.REVIEW_PROMOTION,
                )
                return _PromotedRecord(
                    record_family=MutationRecordFamily.OBSERVATION,
                    record_id=outcome.observation_id,
                    record_version=outcome.resolution_version,
                )

    def merge_lineage(
        self, principal_id: str, entity_id: str | None = None
    ) -> list[EntityMergeRecord]:
        """Every merge recorded, or every merge touching one entity."""
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        return self._entities.merges(principal_id, entity_id)

    # --- WP-RI-A-04: observation ingest --------------------------------------

    def ingest(
        self,
        command: ObserveCommand,
        *,
        sources: SourceRepository,
        at: datetime,
        correlation_id: str,
        audit_id: str,
    ) -> ObservationAdmission:
        """Record one observation. Creates no entity, and cannot.

        The narrowest write on this plane, and its narrowness is structural
        rather than promised: the only repository calls below are
        `record_observation` and `record_mutation_event`, plus the reads that
        refuse. There is no `create`, no `bind_identifier` and no
        `link_observation` on any path, so "recording evidence does not create a
        canonical person" is a property of what this method can reach.

        **The origin is proved before the authority is granted.** A
        `SOURCE_OBSERVATION` has to name a source object this product has
        actually read -- `sources.source_of_object` has to return the source the
        command named -- and a product-owned capture may not claim it at all. A
        model conclusion has no source object version to name, which is why the
        rule is about the origin rather than about who is calling: a rule that
        asked the caller what it was would be satisfied by anything willing to
        answer.

        **Replay is decided by the mutation ledger and not by the observation
        identifier.** The identifier is minted here, so it differs on every
        attempt; `(principal_id, capability, idempotency_key)` does not, and the
        stored `request_digest` is what tells a retry from a second request
        wearing the first one's key.
        """
        validate_identifier(command.principal_id, IdKind.PRINCIPAL)
        principal_id = command.principal_id
        source_id, source_object_id, source_version_id = self._origin_triple(command)
        self._admit_authority(command, sources, source_id=source_id, object_id=source_object_id)
        observed_at = ensure_utc(command.observed_at)
        if observed_at > at:
            # Refused here rather than by `EntityObservation.__post_init__`,
            # which raises a bare `ValueError` and would reach the caller as
            # `internal_error` -- "this is our fault, retrying will not help" --
            # for a request that simply named a moment in the future. This layer
            # is the one holding the server clock, so it is the one that can
            # tell a mistyped date from a bug.
            raise ObservationTimeError("an observation cannot be observed after it is recorded")
        try:
            normalized = normalize_name(command.observed_value)
        except NormalizationError as failure:
            raise ObservationAuthorityError("an observation records a matchable value") from failure

        digest = _digest(
            {
                "kind": command.kind.value,
                "authority": command.authority.value,
                "observed_value_sha256": _text_digest(command.observed_value),
                "mention_display_name": command.mention_display_name,
                "source_id": source_id,
                "source_object_id": source_object_id,
                "source_version_id": source_version_id,
                "observed_at": observed_at.isoformat(),
                "entity_id": command.entity_id,
                "expected_entity_version": command.expected_entity_version,
            }
        )
        replayed = self._entities.mutation_event(
            principal_id,
            capability=Capability.ENTITIES_OBSERVE.value,
            idempotency_key=command.idempotency_key,
        )
        if replayed is not None:
            return self._replayed_observation(principal_id, replayed, digest, command)

        if command.entity_id is not None:
            # Already-justified binding only. The expected version is required
            # with it and checked here, so a caller binding an observation to an
            # entity it read a moment ago is refused when somebody else has
            # changed that entity since -- the same optimistic rule every other
            # state-dependent write on this plane applies.
            self._require_current_entity(
                principal_id, command.entity_id, command.expected_entity_version
            )

        observation = EntityObservation(
            observation_id=issue_identifier(IdKind.ENTITY_OBSERVATION),
            principal_id=principal_id,
            kind=command.kind,
            observed_value=command.observed_value,
            normalized_value=normalized,
            mention_display_name=command.mention_display_name,
            source_id=source_id,
            source_object_id=source_object_id,
            source_version_id=source_version_id,
            observed_at=observed_at,
            recorded_at=at,
            entity_id=command.entity_id,
            authority=command.authority,
            state=ObservationState.CURRENT,
        )
        self._entities.record_observation(principal_id, observation)
        # Minted before the admission rather than inside the ledger row, because
        # the admission carries it: it is the receipt this capability returns,
        # and a value the writer minted for itself could not be handed back.
        event_id = issue_identifier(IdKind.ENTITY_MUTATION_EVENT)
        admission = ObservationAdmission(
            observation_id=observation.observation_id,
            kind=observation.kind,
            authority=observation.authority,
            origin=origin_of(observation.source_id),
            state=observation.state,
            resolution_version=observation.resolution_version,
            entity_id=observation.entity_id,
            recorded_at=observation.recorded_at,
            idempotency_key=command.idempotency_key,
            created=True,
            mutation_event_id=event_id,
        )
        self._entities.record_mutation_event(
            principal_id,
            EntityMutationEvent(
                event_id=event_id,
                principal_id=principal_id,
                capability=Capability.ENTITIES_OBSERVE.value,
                record_family=MutationRecordFamily.OBSERVATION,
                record_id=observation.observation_id,
                new_version=1,
                authority=_MUTATION_AUTHORITY[command.authority],
                actor_class=_ACTOR_CLASS[command.authority],
                idempotency_key=command.idempotency_key,
                request_digest=digest,
                correlation_id=correlation_id,
                audit_id=audit_id,
                recorded_at=at,
                # The photograph carries identifiers, closed vocabulary members
                # and versions. It does not carry `observed_value` or
                # `normalized_value`: this ledger is read by operators and
                # rendered in failures, and a wholesale photograph of the row is
                # exactly where the observed text would end up.
                after_state=_observation_state(admission),
            ),
        )
        return admission

    # --- WP-RI-A-04: deciding what a mention refers to ------------------------

    def resolve_mention(
        self,
        command: ResolveMentionCommand,
        *,
        resolve: _FreshResolution,
        at: datetime,
        correlation_id: str,
        audit_id: str,
        decided_by: str,
        actor_class: ActorClass,
    ) -> MentionResolution:
        """Decide one unresolved mention, or refuse and record the refusal.

        **Nothing here chooses a candidate.** `link_existing` binds the entity
        the caller named and no other; `create_new` creates one and is admitted
        only on a fresh `NOT_FOUND`; the three refusals bind nothing. There is
        no branch that reads a candidate list and takes the first, the best, or
        the only one, which is the shape section 15.2 refuses -- an ambiguous
        mention stays unresolved rather than being forced into the nearest
        person.

        **The fresh resolution is a veto and not a requirement.** It is run
        inside this transaction, against the state that exists now rather than
        the state the queue was rendered from, and what it can do is *stop* a
        binding: a conflicted identifier, a historical match, or -- for
        `create_new` -- anything other than `NOT_FOUND`. It cannot license one.
        An unresolved mention frequently does not lexically match the entity it
        refers to; that is why it is on the queue, and requiring candidacy would
        make the queue unworkable while proving nothing.

        **The refusals a user has already recorded are read first and honoured.**
        `entity_fact_evidence_links` rows carrying
        `NEGATIVE_IDENTITY_EVIDENCE_ROLE` for this observation name the pairings
        already refused. They are withheld from the fresh resolution, so the
        same pairing is not proposed again, and a `link_existing` naming one of
        them is refused rather than quietly reversing a decision this plane has
        no disposition for.
        """
        validate_identifier(command.principal_id, IdKind.PRINCIPAL)
        principal_id = command.principal_id
        digest = _digest(
            {
                "observation_id": command.observation_id,
                "expected_resolution_version": command.expected_resolution_version,
                "disposition": command.disposition.value,
                "entity_id": command.entity_id,
                "expected_entity_version": command.expected_entity_version,
                "entity_type": None if command.entity_type is None else command.entity_type.value,
                "canonical_name_sha256": (
                    None if command.canonical_name is None else _text_digest(command.canonical_name)
                ),
                "display_name_sha256": (
                    None if command.display_name is None else _text_digest(command.display_name)
                ),
                "rejected_entity_id": command.rejected_entity_id,
                "reason_sha256": (None if command.reason is None else _text_digest(command.reason)),
            }
        )
        replayed = self._entities.mutation_event(
            principal_id,
            capability=Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE.value,
            idempotency_key=command.idempotency_key,
        )
        if replayed is not None:
            return self._replayed_resolution(replayed, digest, command)

        held = self._entities.observation(principal_id, command.observation_id)
        if held is None:
            raise UnknownObservationError("no such observation in this scope")
        if held.resolution_version != command.expected_resolution_version:
            # The guarded `UPDATE` below is still the authority -- it is what
            # decides a genuine race, under READ COMMITTED, between two writers
            # that both got past this line. This read is what stops an
            # *unraced* stale decision from creating an entity first and
            # relying on the transaction to take it back: `create_new` has to
            # insert the entity before the update that binds it, because the
            # column is a foreign key, so the cheap check belongs before the
            # expensive one.
            raise StaleResolutionVersionError("the expected resolution version is stale")

        refused = self._refused_pairings(principal_id, command.observation_id)
        binds = command.disposition in (
            ResolutionDisposition.LINK_EXISTING,
            ResolutionDisposition.CREATE_NEW,
        )
        if binds and held.state is ObservationState.QUARANTINED:
            raise QuarantinedObservationError("a quarantined observation does not bind an entity")

        entity_id: str | None = None
        if command.disposition is ResolutionDisposition.LINK_EXISTING:
            entity_id = self._admit_link(command, held, refused, resolve=resolve, at=at)
        elif command.disposition is ResolutionDisposition.CREATE_NEW:
            entity_id = self._admit_creation(command, held, refused, resolve=resolve, at=at)

        state = (
            ObservationState.QUARANTINED
            if command.disposition is ResolutionDisposition.QUARANTINE
            else None
        )
        advanced = self._entities.decide_observation(
            principal_id,
            command.observation_id,
            expected_resolution_version=command.expected_resolution_version,
            entity_id=entity_id,
            state=state,
            state_reason=command.reason if state is not None else None,
        )
        if not advanced:
            raise StaleResolutionVersionError("the expected resolution version is stale")

        evidence_link_ids = self._preserve_refusal(
            principal_id, command, at=at, actor_class=actor_class
        )
        resolution_version = command.expected_resolution_version + 1
        decision = EntityResolutionDecision(
            decision_id=issue_identifier(IdKind.ENTITY_RESOLUTION_DECISION),
            principal_id=principal_id,
            observation_id=command.observation_id,
            # The sequence is the decision's place in this observation's own
            # order and the version is what the decider checked against. They
            # advance together here and are still two facts: the unique
            # `(observation_id, sequence)` is what refuses a second writer that
            # somehow got past the version check.
            sequence=resolution_version,
            expected_resolution_version=command.expected_resolution_version,
            disposition=command.disposition,
            decided_by=decided_by,
            actor_class=actor_class,
            correlation_id=correlation_id,
            audit_id=audit_id,
            decided_at=at,
            entity_id=entity_id,
            reason=command.reason,
            evidence_link_ids=evidence_link_ids,
        )
        self._entities.record_resolution_decision(principal_id, decision)
        # Minted here for the reason `ingest` mints its own: the outcome carries
        # it, and it is the receipt this capability returns.
        event_id = issue_identifier(IdKind.ENTITY_MUTATION_EVENT)
        outcome = MentionResolution(
            decision_id=decision.decision_id,
            observation_id=command.observation_id,
            disposition=command.disposition,
            resolution_version=resolution_version,
            entity_id=entity_id,
            evidence_link_ids=evidence_link_ids,
            decided_at=at,
            idempotency_key=command.idempotency_key,
            created=True,
            mutation_event_id=event_id,
        )
        self._entities.record_mutation_event(
            principal_id,
            EntityMutationEvent(
                event_id=event_id,
                principal_id=principal_id,
                capability=Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE.value,
                record_family=MutationRecordFamily.OBSERVATION,
                record_id=command.observation_id,
                prior_version=(
                    command.expected_resolution_version
                    if command.expected_resolution_version >= 1
                    else None
                ),
                new_version=resolution_version,
                authority=(
                    MutationAuthority.REVIEW_ACCEPTED
                    if actor_class is ActorClass.REVIEW_PROMOTION
                    else MutationAuthority.USER_CONFIRMED_ASSERTION
                ),
                actor_class=actor_class,
                idempotency_key=command.idempotency_key,
                request_digest=digest,
                correlation_id=correlation_id,
                audit_id=audit_id,
                reason=command.reason,
                recorded_at=at,
                before_state={"resolution_version": command.expected_resolution_version},
                after_state=_resolution_state(outcome),
            ),
        )
        return outcome

    # --- what admits a disposition -------------------------------------------

    def _admit_link(
        self,
        command: ResolveMentionCommand,
        held: EntityObservation,
        refused: frozenset[str],
        *,
        resolve: _FreshResolution,
        at: datetime,
    ) -> str:
        """The entity a `link_existing` may bind, or a refusal naming why not."""
        if command.entity_id is None or command.expected_entity_version is None:
            raise ResolutionNotPermittedError("evidence_invalid")
        if command.entity_id in refused:
            # The user has already recorded that this observation does not refer
            # to this entity. Reversing that is not one of the five dispositions
            # this contract freezes, so the honest answer is a refusal rather
            # than a silent overwrite of a decision the plane keeps for ever.
            raise ResolutionNotPermittedError("evidence_invalid")
        entity = self._require_current_entity(
            command.principal_id, command.entity_id, command.expected_entity_version
        )
        answer = resolve(held, refused, at)
        if answer.outcome is ResolutionOutcome.CONFLICTED_IDENTIFIER:
            raise ResolutionNotPermittedError("conflicted_identifier")
        if answer.outcome is ResolutionOutcome.HISTORICAL_MATCH and any(
            candidate.entity_id == entity.entity_id for candidate in answer.candidates
        ):
            raise ResolutionNotPermittedError("historical_entity")
        return entity.entity_id

    def _admit_creation(
        self,
        command: ResolveMentionCommand,
        held: EntityObservation,
        refused: frozenset[str],
        *,
        resolve: _FreshResolution,
        at: datetime,
    ) -> str:
        """Create the entity a `create_new` asked for, on a fresh `NOT_FOUND` only."""
        if command.entity_type is None or command.canonical_name is None:
            raise ResolutionNotPermittedError("evidence_invalid")
        answer = resolve(held, refused, at)
        if answer.outcome is ResolutionOutcome.CONFLICTED_IDENTIFIER:
            raise ResolutionNotPermittedError("conflicted_identifier")
        if answer.outcome is not ResolutionOutcome.NOT_FOUND:
            # Anything else means this reference already matches something, and
            # creating a second record for it is exactly the duplicate identity
            # this plane exists to prevent. Ambiguity is a review's job.
            raise ResolutionNotPermittedError("ambiguous_identity")
        if answer.candidates_were_truncated:
            # `NOT_FOUND` here means every candidate this answer could see was
            # refused, and there were more it could not see. "We found nobody"
            # and "we refused everybody we could look at" are different facts,
            # and only the first licenses a creation.
            raise ResolutionNotPermittedError("review_required")
        try:
            normalized = normalize_name(command.canonical_name)
        except NormalizationError as failure:
            raise ResolutionNotPermittedError("evidence_invalid") from failure
        created = self._entities.create(
            command.principal_id,
            Entity(
                entity_id=issue_identifier(IdKind.ENTITY),
                principal_id=command.principal_id,
                entity_type=command.entity_type,
                canonical_name=normalized,
                display_name=command.display_name or command.canonical_name,
                status=EntityStatus.ACTIVE,
                created_at=at,
                updated_at=at,
                # A record nobody has changed yet. Stated rather than defaulted
                # so that `create_new` cannot quietly produce an entity whose
                # first `expected_version` disagrees with what a caller reads.
                version=1,
            ),
        )
        return created.entity_id

    def _preserve_refusal(
        self,
        principal_id: str,
        command: ResolveMentionCommand,
        *,
        at: datetime,
        actor_class: ActorClass,
    ) -> tuple[str, ...]:
        """Record the pairing a `reject` refused, so the refusal has an effect.

        Nothing is erased. The observation stays, its text stays, and the
        decision that refused it stays on an append-only table; what this adds
        is the one row that says *which entity* was refused, because
        `entity_resolution_decisions` cannot say it -- its own CHECK reserves
        `entity_id` for the two dispositions that bind one, so a rejection has
        nowhere else to name the other half of the pairing.

        `COUNTEREVIDENCE` is the role, and it is the role
        `EntityResolutionService` reads back. A link recorded as `SUPPORTING`
        would record the opposite of what was decided while still looking like a
        record of it.
        """
        if (
            command.disposition is not ResolutionDisposition.REJECT
            or command.rejected_entity_id is None
        ):
            return ()
        link = EntityFactEvidenceLink(
            link_id=issue_identifier(IdKind.ENTITY_FACT_EVIDENCE_LINK),
            principal_id=principal_id,
            role=EvidenceRole.COUNTEREVIDENCE,
            authority=(
                MutationAuthority.REVIEW_ACCEPTED
                if actor_class is ActorClass.REVIEW_PROMOTION
                else MutationAuthority.USER_CONFIRMED_ASSERTION
            ),
            created_at=at,
            entity_id=command.rejected_entity_id,
            entity_observation_id=command.observation_id,
        )
        self._entities.record_fact_evidence_link(principal_id, link)
        return (link.link_id,)

    def refused_pairings(self, principal_id: str, observation_id: str) -> frozenset[str]:
        """Every entity this observation has been decided *not* to refer to.

        Public because the resolution path outside this module needs the same
        answer, and two readers computing it from the same table with two
        filters is how the ledger and the resolver come to disagree.
        """
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        return self._refused_pairings(principal_id, observation_id)

    def _refused_pairings(self, principal_id: str, observation_id: str) -> frozenset[str]:
        return frozenset(
            link.entity_id
            for link in self._entities.fact_evidence_links(
                principal_id,
                entity_observation_id=observation_id,
                role=EvidenceRole.COUNTEREVIDENCE,
                limit=_UNBOUNDED_NEGATIVE_EVIDENCE,
            )
            if link.entity_id is not None
        )

    # --- what admits an authority --------------------------------------------

    def _origin_triple(self, command: ObserveCommand) -> tuple[str, str, str]:
        """The `(source, object, version)` triple this command's origin produces."""
        source_shape = (command.source_id, command.source_object_id, command.source_version_id)
        capture_shape = (command.capture_id, command.capture_version_id)
        if all(part is not None for part in source_shape) and all(
            part is None for part in capture_shape
        ):
            return (str(source_shape[0]), str(source_shape[1]), str(source_shape[2]))
        if all(part is not None for part in capture_shape) and all(
            part is None for part in source_shape
        ):
            return capture_origin_triple(str(capture_shape[0]), str(capture_shape[1]))
        raise ObservationAuthorityError(
            "an observation names one source object version or one product-owned capture"
        )

    def _admit_authority(
        self,
        command: ObserveCommand,
        sources: SourceRepository,
        *,
        source_id: str,
        object_id: str,
    ) -> None:
        """Refuse an authority the origin does not support.

        **This is where model output is kept out of `SOURCE_OBSERVATION`.** The
        claim is not checked against who is calling -- nothing here asks -- it is
        checked against whether a source object version exists that says what is
        being claimed. `sources.source_of_object` has to name the source the
        command named, which a conclusion drawn by a model cannot arrange: the
        product-owned capture path is the only one open to it, and that path
        cannot carry this authority at all.

        `USER_AUTHORED_STATEMENT` is the mirror image and is refused on a
        configured source, because a statement the user made is not quoting a
        mailbox, and letting it name a source version would put a fabricated
        provenance on the one authority a source can never falsify.
        """
        origin = origin_of(source_id)
        if origin is ObservationOrigin.CONFIGURED_SOURCE and (
            sources.source_of_object(object_id) != source_id
        ):
            # Asked of *every* configured-source origin rather than only of the
            # source-backed authority, and the difference matters: a triple
            # naming nothing is fabricated provenance whatever standing the
            # caller claimed for it, and a rule that only checked one authority
            # would leave `system_deterministic_observation` as the way around
            # it.
            raise ObservationAuthorityError(
                "an observation names a source object this product has read"
            )
        if command.authority is ObservationAuthority.SOURCE_OBSERVATION:
            if origin is not ObservationOrigin.CONFIGURED_SOURCE:
                raise ObservationAuthorityError(
                    "a product-owned capture is not a source observation"
                )
            return
        if command.authority is ObservationAuthority.USER_AUTHORED_STATEMENT:
            if origin is not ObservationOrigin.PRODUCT_OWNED_CAPTURE:
                raise ObservationAuthorityError(
                    "a user-authored statement is not quoting a configured source"
                )
            if command.kind is not ObservationKind.USER_STATEMENT:
                raise ObservationAuthorityError(
                    "a user-authored statement is recorded as a user statement"
                )

    def _require_current_entity(
        self, principal_id: str, entity_id: str, expected_version: int | None
    ) -> Entity:
        """The named entity, refusing an absent, foreign, stale or non-current one."""
        if expected_version is None:
            raise ResolutionNotPermittedError("evidence_invalid")
        entity = self._entities.get(principal_id, entity_id)
        if entity is None:
            raise UnknownEntityError("no such entity in this scope")
        if entity.version != expected_version:
            raise ResolutionNotPermittedError("stale_version")
        if entity.status is not EntityStatus.ACTIVE:
            raise ResolutionNotPermittedError("historical_entity")
        return entity

    # --- replay ---------------------------------------------------------------

    def _replayed_observation(
        self,
        principal_id: str,
        replayed: EntityMutationEvent,
        digest: str,
        command: ObserveCommand,
    ) -> ObservationAdmission:
        """The first admission's own receipt, read back rather than recomputed."""
        if replayed.request_digest != digest:
            raise EntityMutationConflictError("an entity mutation key is held for another request")
        observation = self._entities.observation(principal_id, replayed.record_id)
        if observation is None:
            raise UnknownObservationError("the replayed observation is no longer readable")
        return ObservationAdmission(
            observation_id=observation.observation_id,
            kind=observation.kind,
            authority=observation.authority,
            origin=origin_of(observation.source_id),
            state=observation.state,
            resolution_version=observation.resolution_version,
            entity_id=observation.entity_id,
            recorded_at=observation.recorded_at,
            idempotency_key=command.idempotency_key,
            created=False,
            mutation_event_id=replayed.event_id,
        )

    def _replayed_resolution(
        self, replayed: EntityMutationEvent, digest: str, command: ResolveMentionCommand
    ) -> MentionResolution:
        if replayed.request_digest != digest:
            raise EntityMutationConflictError("an entity mutation key is held for another request")
        stored = dict(replayed.after_state or {})
        cited = stored.get("evidence_link_ids")
        return MentionResolution(
            decision_id=str(stored.get("decision_id", "")),
            observation_id=replayed.record_id,
            disposition=ResolutionDisposition(str(stored.get("disposition"))),
            resolution_version=replayed.new_version,
            entity_id=None if stored.get("entity_id") is None else str(stored["entity_id"]),
            evidence_link_ids=(
                tuple(str(item) for item in cited) if isinstance(cited, list) else ()
            ),
            decided_at=replayed.recorded_at,
            idempotency_key=command.idempotency_key,
            created=False,
            mutation_event_id=replayed.event_id,
        )


# --- WP-RI-A-04: recording evidence, and deciding what it refers to ----------
#
# Two use cases and one rule they share: neither of them is allowed to decide
# who somebody is on its own. `ingest` records what was observed and creates no
# entity, because section 12.2 says a source record "does not become the
# canonical person by itself". `resolve_mention` decides, and every path through
# it either names an entity the *caller* named or refuses -- there is no branch
# that picks a candidate.


#: How many refusals one observation may accumulate before this plane stops
#: reading them. `None` -- genuinely unbounded, and the one place on this plane
#: where that is the safe choice rather than the lazy one: the set is read in
#: order to *withhold* candidates, so a truncated read would silently start
#: proposing a pairing the user has already refused. It grows only by deliberate
#: user decisions about one mention, which is not a collection that runs away.
_UNBOUNDED_NEGATIVE_EVIDENCE: int | None = None


#: The two dispositions that make a case terminal wherever it lives.
_ACCEPTING: Final[frozenset[Disposition]] = frozenset(
    {Disposition.ACCEPT, Disposition.CORRECT_AND_ACCEPT}
)


class EntityProposalReviewService:
    """One Entity proposal decided on the one canonical Review surface.

    **This is not a second review plane, and the shape is what says so.** It
    opens no case, keeps no state of its own and publishes no listing: the case
    was opened by `propose`, the listing is `review.list`, and the vocabulary is
    the shared `Disposition`. What lives here is the *ordering* of one decision,
    which had to be application code for a reason section 14 fixes: an accepted
    ordinary proposal is executed through the canonical Phase A mutation
    services, and the other three subject kinds on this surface promote inside
    their own SQL because everything their promotion does is SQL. Ordering it in
    `infrastructure` would have meant either a second copy of those mutations or
    an import direction the architecture forbids.

    **The order is claim, execute, append, and each step is why the next one is
    safe.** `EntityGovernanceService`'s guarded `UPDATE` is what makes deciding a
    one-time act, so it runs first and two racing reviewers produce one decision.
    The promotion runs second, inside the same transaction, so a refusal takes
    the decision back with it. The ledger row is appended last, and
    `UNIQUE (review_case_id, sequence)` is what makes two reviewers who both read
    version 0 produce one row rather than two.

    **A reviewer grant is not an identity-correction grant.** Accepting a
    `merge_entities` or `split_identity` proposal records reviewed intent and
    lineage and mutates no identity — `EntityGovernanceService.accept` skips the
    routing for those kinds before it is consulted, and `promotion_for` refuses
    them anyway. Nothing here re-opens that door, and there is a test that holds
    both entities' status and version unchanged across an acceptance taken
    through this service with an operator's authority and a promotion context in
    hand.
    """

    def __init__(self, entities: EntitiesRepository, reviews: ReviewRepository) -> None:
        self._entities = entities
        self._reviews = reviews
        self._governance = EntityGovernanceService(entities)

    def decide(
        self,
        request: ReviewDecisionRequest,
        *,
        decided_by: str,
        has_operator_authority: bool = False,
        resolve: _FreshResolution | None = None,
    ) -> ReviewDecision:
        """Append one disposition to an Entity proposal's case and perform it.

        `decided_by`, `has_operator_authority` and `resolve` come from the
        authenticated request rather than from the review request, for the reason
        section 26 gives about every server-owned field: a caller that could name
        its own authority would name the one it needed.

        **The promotion's idempotency key is this decision's identifier**, which
        is what `relationship_memory_review` uses for the same reason: the
        admitting act of a promoted write is the reviewer's decision, a
        synthesized key would name nothing, and a key derived from the *proposal*
        would make a second, corrected decision replay the first one's receipt.
        """
        decision_id = issue_identifier(IdKind.REVIEW_DECISION)
        promotion = PromotionContext(
            correlation_id=request.correlation_id,
            audit_id=request.audit_id,
            idempotency_key=decision_id,
            at=request.decided_at,
            resolve=resolve,
        )
        correction_patch = (
            None if request.correction_patch is None else request.correction_patch.as_mapping()
        )
        try:
            held = self._entities.serialize_entity_proposal_review_scope(
                request.principal_id,
                request.review_case_id,
                correction_patch=correction_patch,
            )
        except ProposalReviewScopeConflictError as exc:
            raise ReviewConflictError(
                "this proposal changed while the review request was in flight"
            ) from exc
        except ProposalPayloadError as exc:
            raise ReviewCorrectionError(str(exc)) from exc
        if held is None:
            raise ReviewNotFoundError("the request names no stored review case")
        case = self._reviews.entity_proposal_case(request.principal_id, request.review_case_id)
        if case is None or case.proposal_id != held.proposal_id:
            raise ReviewNotFoundError("the request names no stored review case")
        ledger = self._reviews.entity_proposal_decisions(
            request.principal_id, request.review_case_id
        )
        if any(disposition in _ACCEPTING for disposition in ledger):
            raise ReviewConflictError("an accepted review case is terminal")
        if len(ledger) != request.expected_review_version:
            raise ReviewConflictError("the expected review version is stale")
        if not held.is_open:
            raise ReviewConflictError("this proposal has already been decided")

        escalated = Disposition.ESCALATE in ledger
        corrected = self._corrected_payload(held, request)
        state = self._perform(
            request,
            held,
            escalated=escalated,
            corrected=corrected,
            decided_by=decided_by,
            has_operator_authority=has_operator_authority,
            promotion=promotion,
        )
        self._reviews.record_entity_proposal_decision(
            request.principal_id,
            EntityProposalReviewDecision(
                decision_id=decision_id,
                proposal_id=held.proposal_id,
                review_case_id=request.review_case_id,
                principal_id=request.principal_id,
                sequence=len(ledger) + 1,
                disposition=request.disposition,
                correlation_id=request.correlation_id,
                audit_id=request.audit_id,
                decided_at=request.decided_at,
                reason=request.reason,
                corrected_payload=(
                    None if corrected is None else CorrectionPatch.of(corrected.as_mapping())
                ),
            ),
        )
        handoff = None
        if request.disposition in _ACCEPTING and held.kind in IDENTITY_CORRECTION_PROPOSAL_KINDS:
            effective_payload = held.payload if corrected is None else corrected
            handoff = EntityIdentityCorrectionHandoff(
                proposal_id=held.proposal_id,
                proposal_kind=held.kind,
                effective_payload=effective_payload,
                effective_payload_source=(
                    ReviewedPayloadSource.PROPOSED
                    if corrected is None
                    else ReviewedPayloadSource.CORRECTED
                ),
            )
        return EntityProposalReviewResult(
            decision_id=decision_id,
            review_case_id=request.review_case_id,
            sequence=len(ledger) + 1,
            disposition=request.disposition,
            principal_id=request.principal_id,
            correlation_id=request.correlation_id,
            audit_id=request.audit_id,
            decided_at=request.decided_at,
            proposal_state=state,
            identity_correction_handoff=handoff,
        )

    def _corrected_payload(
        self, held: EntityProposal, request: ReviewDecisionRequest
    ) -> EntityProposalPayload | None:
        """The reviewer's correction, checked against the target command's schema.

        **The check is `EntityProposalPayload`'s and there is no second copy of
        it.** `schema_for(kind)` is derived from the one canonical command that
        would carry the mutation out, so constructing the payload against the
        proposal's own kind *is* validating the patch against the target command
        schema — the same validator the producer's payload went through, applied
        to the reviewer's. That is what section 13's "validate patch against
        target command schema before commit" asks for, and writing a second,
        weaker check here would be the failure that module's own docstring names.

        A patch is refused for a subject that has no such schema, which today
        means it is refused for every case that is not an Entity proposal: this
        method is only reached for one, and `ReviewDecisionRequest` refuses a
        patch and a `corrected_value` together, so a capture reviewer's single
        bounded string is untouched by any of this.
        """
        if request.disposition is not Disposition.CORRECT_AND_ACCEPT:
            return None
        if request.correction_patch is None:
            raise ReviewCorrectionError("an entity correction is a typed patch, not one value")
        try:
            return EntityProposalPayload.of(held.kind, request.correction_patch.as_mapping())
        except ProposalPayloadError as exc:
            raise ReviewCorrectionError(str(exc)) from exc

    def _perform(
        self,
        request: ReviewDecisionRequest,
        held: EntityProposal,
        *,
        escalated: bool,
        corrected: EntityProposalPayload | None,
        decided_by: str,
        has_operator_authority: bool,
        promotion: PromotionContext | None,
    ) -> ProposalState:
        """Do what the disposition says, and return the state the case now presents.

        Eight branches and no default, so a disposition added to the vocabulary
        is a type error here rather than a decision that quietly records itself
        and does nothing.
        """
        principal_id = request.principal_id
        match request.disposition:
            case Disposition.ACCEPT | Disposition.CORRECT_AND_ACCEPT:
                self._require_the_ceiling(held, escalated=escalated, granted=has_operator_authority)
                decided = self._governance.accept(
                    principal_id,
                    held.proposal_id,
                    decided_by=decided_by,
                    decided_at=request.decided_at,
                    reason=request.reason or _ACCEPTANCE_REASON,
                    has_operator_authority=has_operator_authority,
                    promotion=promotion,
                    corrected_payload=corrected,
                )
                return ProposalState(decided.state.value)
            case Disposition.REJECT:
                self._governance.reject(
                    principal_id,
                    held.proposal_id,
                    decided_by=decided_by,
                    decided_at=request.decided_at,
                    reason=self._stated(request),
                )
                return ProposalState.REJECTED
            case Disposition.DEFER:
                self._governance.defer(
                    principal_id,
                    held.proposal_id,
                    decided_by=decided_by,
                    decided_at=request.decided_at,
                    reason=self._stated(request),
                )
                return ProposalState.DEFERRED
            case Disposition.INVALIDATE:
                # Through the Review port rather than through
                # `EntityGovernanceService`, because the whole of an invalidation
                # is one guarded `UPDATE` that has to set the state and the
                # reason together: `an_invalidated_proposal_records_why` fires on
                # the row that writes `invalidated`, and `decide_proposal` --
                # which is what every other disposition on this plane goes
                # through -- carries no `invalidated_reason`.
                #
                # Distinct from `reject` in what it claims, and that is the point
                # of having both. A rejection says a reviewer read the request
                # and refused it. An invalidation says the ground moved: the
                # entity a proposal named was merged away, the evidence it rested
                # on was withdrawn. Recording the second as the first would
                # attribute a judgement to somebody who never made one. Nothing
                # canonical is written either way, and the proposal, its evidence
                # links and its case all stay readable.
                if not self._reviews.invalidate_entity_proposal(
                    principal_id,
                    held.proposal_id,
                    reason=self._stated(request),
                    decided_by=decided_by,
                    decided_at=request.decided_at,
                ):
                    raise ReviewConflictError(
                        "this proposal was decided while the request was in flight"
                    )
                return ProposalState.INVALIDATED
            case Disposition.MARK_UNRESOLVED:
                # Nothing is written to the proposal, and that is what the
                # disposition means: section 13 says "preserve unresolved
                # state/evidence". `EntityProposalState` declares no `unresolved`
                # member -- it is what the schema's CHECK is generated from, so
                # inventing one would be a schema change this package is not the
                # owner of, and borrowing `invalidated` would report the evidence
                # as withdrawn when a reviewer only declined to settle it. The
                # ledger row is the record, exactly as it is on the memory plane.
                self._stated(request)
                return ProposalState.UNRESOLVED
            case Disposition.ESCALATE:
                # Also writes nothing to the proposal. Escalation raises the
                # *ceiling*, and the ceiling is read from the ledger: the next
                # acceptance on this case is refused without operator authority,
                # whatever its kind's own requirement says. It performs no
                # identity correction and touches no entity -- section 15's
                # division is not something a disposition can move.
                self._stated(request)
                return ProposalState(held.state.value)
            case Disposition.REPROCESS:
                return self._reprocess(request, held, decided_by=decided_by)

    def _require_the_ceiling(self, held: EntityProposal, *, escalated: bool, granted: bool) -> None:
        """Refuse an acceptance below the ceiling this case now stands at.

        Two ways to reach the operator ceiling and only one of them is the kind's
        own: `requirement_for` puts identity correction there permanently, and an
        `escalate` decision puts this one case there for good. `accept` re-checks
        the first for itself; the second exists only in the ledger, so it is
        checked here and the check is the whole of what escalation *does*.

        **Only an acceptance is gated, and that is deliberate.** A reviewer may
        still reject, defer or mark an escalated case unresolved, because none of
        those writes a canonical record — the ceiling exists to stop a change
        being made below it, not to strand the case. Gating every disposition
        would mean an escalation nobody with operator authority ever looked at
        could not even be withdrawn.
        """
        if granted:
            return
        if escalated:
            raise ReviewAuthorityError(
                "this case was escalated and the caller declared no operator authority"
            )
        if held.requirement is ReviewRequirement.REQUIRES_OPERATOR:
            raise ReviewAuthorityError(
                "this proposal requires operator authority and the caller declared none"
            )

    def _stated(self, request: ReviewDecisionRequest) -> str:
        """The reason this disposition states, required for all five of them here.

        `ReviewDecisionRequest` requires one for `escalate` and `invalidate` only,
        because the other three have callers on planes that never asked for one
        and refusing them would be a regression rather than a rule. This plane
        has no such caller, so it requires what section 13 actually says.
        """
        if request.reason is None:
            raise ReviewCorrectionError("this disposition states the reason for it")
        return request.reason

    def _reprocess(
        self, request: ReviewDecisionRequest, held: EntityProposal, *, decided_by: str
    ) -> ProposalState:
        """Supersede this proposal and raise its successor against current evidence.

        **Three statements in one transaction, and the order is forced.** The
        successor cannot be inserted while the predecessor is open, because
        `dedupe_sha256` is a digest over the kind and the payload and not over
        the method -- so a successor restating the same request collides with the
        predecessor on `an_open_equivalent_proposal_is_raised_once`. And the
        successor pointer cannot be written before the successor exists, because
        its foreign key is immediate. Supersede, insert, then point is the only
        order that satisfies both, which is why
        `EntitiesRepository.supersede_proposal` -- one statement doing the first
        and the third together -- cannot be used here and is left for a
        supersession whose successor already exists.

        **A stale reprocess creates nothing.** The supersession is a guarded
        `UPDATE`; when it matches no row the proposal was decided while this was
        in flight, and the refusal is raised *before* the successor is built, so
        there is nothing to roll back rather than something the transaction has
        to take away.

        **What the successor carries.** The
        same kind and payload -- the request has not changed, only the moment it
        is being asked at -- with `method` and `method_version` re-stamped from
        the predecessor and its evidence copied. Existing-target kinds bind the
        target's version read in this transaction now; replaying the
        predecessor's old expectation would turn reprocess into a stale request.
        The read precedes supersession, so a missing target creates nothing.
        """
        evidence = self._offered_again(request.principal_id, held)
        expected_target_version: int | None = None
        target = target_of(held)
        if target is not None:
            descriptor, record_id = target
            expected_target_version = self._entities.proposal_target_version(
                request.principal_id, descriptor.family, record_id
            )
            if expected_target_version is None:
                raise ReviewConflictError("the proposal target no longer exists")
        if not self._reviews.supersede_entity_proposal(
            request.principal_id, held.proposal_id, at=request.decided_at
        ):
            raise ReviewConflictError("this proposal was decided while the reprocess was in flight")
        successor = self._governance.propose(
            request.principal_id,
            kind=held.kind,
            payload=held.payload.as_mapping(),
            observation_ids=held.observation_ids,
            proposed_by=held.proposed_by,
            method=held.method,
            method_version=held.method_version,
            at=request.decided_at,
            evidence=evidence,
            model_id=held.model_id,
            model_version=held.model_version,
            expected_target_version=expected_target_version,
        )
        self._reviews.name_entity_proposal_successor(
            request.principal_id,
            held.proposal_id,
            successor_proposal_id=successor.proposal_id,
        )
        return ProposalState.SUPERSEDED

    def _offered_again(self, principal_id: str, held: EntityProposal) -> list[ProposedEvidence]:
        """The predecessor's evidence, minus what `propose` will re-derive itself.

        `propose` writes one `DIRECT` link per cited observation from
        `observation_ids`, so copying those forward would give the successor each
        of them twice. Everything else -- a capture span, a knowledge record, a
        piece of counterevidence -- exists only in the link table and would be
        lost by a reprocess that did not carry it, which would make the successor
        rest on less than the proposal it replaced.
        """
        cited = set(held.observation_ids)
        return [
            ProposedEvidence(
                role=link.role,
                entity_observation_id=link.entity_observation_id,
                capture_span_id=link.capture_span_id,
                knowledge_id=link.knowledge_id,
            )
            for link in self._entities.proposal_evidence_links(principal_id, held.proposal_id)
            if not (link.role is EvidenceRole.DIRECT and link.entity_observation_id in cited)
        ]


#: What `decision_reason` records for an acceptance, which states no reason of
#: its own. Section 13 gives a reason to the five dispositions that depart from
#: what was proposed and to none of the three that carry it out, but
#: `entity_proposals` requires a decision to say something -- so this says the
#: true thing rather than echoing a caller's words that were never asked for.
_ACCEPTANCE_REASON: Final = "accepted on review"


@dataclass(frozen=True, slots=True)
class ObserveCommand:
    """One observation to record, with the Principal already resolved.

    **The origin is one of two shapes and never both.** Either the three
    `source_*` fields name a source object version this product has actually
    read, or `capture_id`/`capture_version_id` name a record of the product's
    own. `entity_observations` stores one triple either way -- those three
    columns are `NOT NULL`, carry no foreign key and no identifier-shape CHECK,
    and `MYPA-RI-COMP-04` does not relax them -- so the product-owned shape is
    mapped onto the triple by `capture_origin_triple` and read back out by
    `origin_of`.

    **`authority` is checked against the origin rather than taken on trust.**
    That check is the whole of the anti-laundering rule: see `_admit_authority`.

    Everything the server owns is absent rather than validated. There is no
    `observation_id`, no `normalized_value`, no `recorded_at`, no `state`, no
    `resolution_version` and no `principal_id` field, so a payload naming one
    is refused by the constructor before any of this runs.
    """

    principal_id: str
    kind: ObservationKind
    authority: ObservationAuthority
    observed_value: str = field(repr=False)
    observed_at: datetime
    idempotency_key: str = field(repr=False)
    mention_display_name: str | None = field(default=None, repr=False)
    source_id: str | None = None
    source_object_id: str | None = None
    source_version_id: str | None = None
    capture_id: str | None = None
    capture_version_id: str | None = None
    entity_id: str | None = None
    expected_entity_version: int | None = None

    @property
    def origin(self) -> ObservationOrigin:
        """Which of the two origin shapes this command carries."""
        if self.capture_id is not None:
            return ObservationOrigin.PRODUCT_OWNED_CAPTURE
        return ObservationOrigin.CONFIGURED_SOURCE


@dataclass(frozen=True, slots=True)
class ResolveMentionCommand:
    """One disposition of one unresolved mention, with the Principal resolved."""

    principal_id: str
    observation_id: str
    expected_resolution_version: int
    disposition: ResolutionDisposition
    idempotency_key: str = field(repr=False)
    entity_id: str | None = None
    expected_entity_version: int | None = None
    entity_type: EntityType | None = None
    canonical_name: str | None = field(default=None, repr=False)
    display_name: str | None = field(default=None, repr=False)
    rejected_entity_id: str | None = None
    reason: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ObservationAdmission:
    """What one admitted observation is, without the text it observed.

    No `observed_value` and no `normalized_value`. A receipt acknowledges that a
    record is durable; one that echoed the observation would put a name or an
    address on a second surface for no gain, and a *replayed* receipt would put
    an earlier caller's text on this one.
    """

    observation_id: str
    kind: ObservationKind
    authority: ObservationAuthority
    origin: ObservationOrigin
    state: ObservationState
    resolution_version: int
    entity_id: str | None
    recorded_at: datetime
    idempotency_key: str = field(repr=False)
    created: bool
    #: The `entity_mutation_events` row this admission wrote, which is the
    #: receipt every capability on this plane returns. The stored `receipt_id`
    #: column is null on all of them: it exists for a separate receipt record
    #: this build does not keep, and the ledger row is what a caller is handed
    #: back. See `EntityMutationEvent` for the whole argument.
    mutation_event_id: str


@dataclass(frozen=True, slots=True)
class ProposalAdmission:
    """What one admitted proposal is, without the mutation it asks for.

    No payload, on `ObservationAdmission`'s terms: the fields a proposal carries
    are a display name, an address or a reason read out of somebody's mail, and a
    receipt that echoed them would put them on a second surface for no gain — and
    a *deduped* admission would put the earlier producer's text on this one.

    `requirement` is derived from the kind and is here because it is the answer a
    producer needs next: whether what it proposed will wait for a person, wait
    for the operator, or may clear a threshold. Reading it off the admission is
    how a producer learns that without guessing from the kind.

    The server-minted review case identifier and its initial version are included
    so the proposal receipt can be correlated with the canonical Review plane.
    """

    proposal_id: str
    kind: EntityProposalKind
    state: EntityProposalState
    requirement: ReviewRequirement
    dedupe_sha256: str
    observation_ids: tuple[str, ...]
    proposed_at: datetime
    review_case_id: str
    review_version: int
    #: False when an open-equivalent proposal already said this, in which case
    #: every other field describes *that* proposal. The producer's request was
    #: understood and nothing was written.
    created: bool


def _review_case_for(kind: EntityProposalKind) -> str:
    """A freshly issued canonical Review case for every producer proposal."""
    requirement_for(kind)  # totality guard for a future kind
    return issue_identifier(IdKind.REVIEW_CASE)


def _admission(proposal: EntityProposal, *, created: bool) -> ProposalAdmission:
    if proposal.review_case_id is None:
        raise ValueError("a producer proposal belongs to the canonical Review plane")
    return ProposalAdmission(
        proposal_id=proposal.proposal_id,
        kind=proposal.kind,
        state=proposal.state,
        requirement=proposal.requirement,
        dedupe_sha256=proposal.dedupe_sha256,
        observation_ids=proposal.observation_ids,
        proposed_at=proposal.proposed_at,
        review_case_id=proposal.review_case_id,
        review_version=0,
        created=created,
    )


@dataclass(frozen=True, slots=True)
class MentionResolution:
    """What one resolution decision decided, and what it left behind."""

    decision_id: str
    observation_id: str
    disposition: ResolutionDisposition
    resolution_version: int
    entity_id: str | None
    evidence_link_ids: tuple[str, ...]
    decided_at: datetime
    idempotency_key: str = field(repr=False)
    created: bool
    #: The ledger row this decision wrote, on `ObservationAdmission`'s terms.
    mutation_event_id: str


def _digest(payload: Mapping[str, object]) -> str:
    """The sha256 over canonical JSON that makes a replay decidable.

    Minted identifiers, the correlation identifier and the receipt time are
    excluded by every caller, because they differ on every attempt by
    construction and including any of them would make each retry a conflict.
    The observed text is present only as its own digest, so a payload digest can
    be computed without the name or address passing through a second value that
    is compared, stored and rendered in failures.
    """
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _text_digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


#: Which mutation authority each observation authority implies, and which class
#: of actor performed it. A mapping rather than a branch at the writer, because
#: the ledger and the observation have to agree about one act and two spellings
#: of the same rule are two chances to disagree.
_MUTATION_AUTHORITY: Mapping[ObservationAuthority, MutationAuthority] = {
    ObservationAuthority.SOURCE_OBSERVATION: MutationAuthority.SYSTEM_DETERMINISTIC,
    ObservationAuthority.SYSTEM_DETERMINISTIC_OBSERVATION: MutationAuthority.SYSTEM_DETERMINISTIC,
    ObservationAuthority.USER_AUTHORED_STATEMENT: MutationAuthority.USER_CONFIRMED_ASSERTION,
}

_ACTOR_CLASS: Mapping[ObservationAuthority, ActorClass] = {
    ObservationAuthority.SOURCE_OBSERVATION: ActorClass.SYSTEM_DETERMINISTIC,
    ObservationAuthority.SYSTEM_DETERMINISTIC_OBSERVATION: ActorClass.SYSTEM_DETERMINISTIC,
    ObservationAuthority.USER_AUTHORED_STATEMENT: ActorClass.USER,
}


#: How the resolution path is handed to this module: one call that answers
#: "who, if anyone, does this observation refer to *now*", given the pairings
#: already refused and the moment being asked about.
#:
#: A callable rather than the repository, because this module must not be able
#: to reach a second read of the entity plane through it, and rather than
#: `EntityResolutionService` itself, because the request that service takes is
#: built out of the observation and the refusals -- and building it here would
#: put the resolver's own vocabulary in a module whose subject is governance.
type _FreshResolution = Callable[[EntityObservation, frozenset[str], datetime], EntityResolution]


def _from_receipt(admission: EntityMutationAdmission) -> _PromotedRecord:
    """What one authoring-plane promotion produced, read off its receipt.

    **The version is the child's where there is a child and the entity's
    otherwise, and that is not a choice between two numbers that mean the same
    thing.** `accepted_record_id` names the record the proposal became, so the
    version beside it has to be that record's own — an alias promoted at the
    entity's version would answer "what version of this alias did the review
    produce" with a number about a different row. `EntityMutationReceipt`
    carries both because the entity is the aggregate and every child write
    advances it too; this reads the one the family names.

    A replayed admission is not a special case here. It carries the same record
    and the same version as the write it replays, which is the whole point of
    an idempotency store, and a promotion answered from one has still named the
    record its acceptance produced.
    """
    receipt = admission.receipt
    if receipt.record_family is MutationRecordFamily.ENTITY:
        return _PromotedRecord(
            record_family=receipt.record_family,
            record_id=receipt.record_id,
            record_version=receipt.entity_version,
        )
    if receipt.child_version is None:
        raise UnpromotableProposalError("a promoted child record carries its own version")
    return _PromotedRecord(
        record_family=receipt.record_family,
        record_id=receipt.record_id,
        record_version=receipt.child_version,
    )


def _from_directed(receipt: DirectedReceipt) -> _PromotedRecord:
    """What one directed-plane promotion produced. `version` is the record's own."""
    return _PromotedRecord(
        record_family=receipt.record_family,
        record_id=receipt.record_id,
        record_version=receipt.version,
    )


def _observation_state(admission: ObservationAdmission) -> dict[str, object]:
    """The photograph one admitted observation leaves on the mutation ledger.

    Identifiers, closed vocabulary members and versions. **No `observed_value`
    and no `normalized_value`**, and that omission is the rule rather than the
    current contents: a wholesale photograph of an `entity_observations` row is
    exactly how a name or a mail envelope reaches a ledger operators read,
    export and see rendered in failures.
    """
    return {
        "observation_id": admission.observation_id,
        "kind": admission.kind.value,
        "authority": admission.authority.value,
        "origin": admission.origin.value,
        "state": admission.state.value,
        "resolution_version": admission.resolution_version,
        "entity_id": admission.entity_id,
    }


def _resolution_state(outcome: MentionResolution) -> dict[str, object]:
    """The photograph one decision leaves, and what a replay is rebuilt from."""
    return {
        "decision_id": outcome.decision_id,
        "observation_id": outcome.observation_id,
        "disposition": outcome.disposition.value,
        "resolution_version": outcome.resolution_version,
        "entity_id": outcome.entity_id,
        "evidence_link_ids": list(outcome.evidence_link_ids),
    }
