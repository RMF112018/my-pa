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

**Promotion of the ordinary kinds is elsewhere, and deliberately.**
`application.entity_promotion` holds the routing from an accepted proposal to
the canonical Phase A command that performs its mutation, and the Review path
deciding the case is what executes it. This module holds no authoring service
and no directed-write service, so "accepting a proposal cannot itself write a
canonical record" is a property of what it can reach rather than a rule it
promises to follow.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256

from my_pa.contracts.ports import EntitiesRepository, SourceRepository
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.operation import Capability
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.governance import (
    OPEN_EQUIVALENT_PROPOSAL_STATES,
    ActorClass,
    EntityFactEvidenceLink,
    EntityGovernanceError,
    EntityMergeRecord,
    EntityMutationConflictError,
    EntityMutationEvent,
    EntityObservation,
    EntityProposal,
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
)
from my_pa.domain.relationship.normalization import NormalizationError, normalize_name
from my_pa.domain.relationship.proposal_payload import dedupe_digest
from my_pa.domain.relationship.resolution import EntityResolution, ResolutionOutcome
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "EntityGovernanceService",
    "MentionResolution",
    "ObservationAdmission",
    "ObserveCommand",
    "ProposalAdmission",
    "ProposalNotOpenError",
    "ProposalSuppressedError",
    "QuarantinedObservationError",
    "ResolutionNotPermittedError",
    "ResolveMentionCommand",
    "ReviewAuthorityError",
    "UnknownEntityError",
    "UnknownObservationError",
]


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

        No review case is opened here and none is named: the Review plane owns
        that, and a producer that could name a case could name one already
        decided. No mutation-ledger row is written either, and that is the
        ledger's own rule rather than an omission — `MutationRecordFamily` holds
        the six canonical families and deliberately excludes proposals, because a
        ledger that recorded requests would record the asking as if it were the
        doing.
        """
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        checked = EntityProposalPayload.of(kind, payload)
        self._admit_evidence(principal_id, observation_ids)
        # Suppression is decided before dedupe, and the order is deliberate: a
        # producer re-filing evidence a reviewer has already refused is told so,
        # rather than being told what is currently open in a queue it does not
        # decide.
        self._refuse_a_known_bad_proposal(principal_id, checked, observation_ids)
        digest = dedupe_digest(checked)
        open_equivalent = self._open_equivalent(principal_id, digest)
        if open_equivalent is not None:
            return _admission(open_equivalent, created=False)
        proposal = EntityProposal(
            proposal_id=issue_identifier(IdKind.ENTITY_PROPOSAL),
            principal_id=principal_id,
            kind=kind,
            state=EntityProposalState.PROPOSED,
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
        )
        self._entities.record_proposal(principal_id, proposal)
        return _admission(proposal, created=True)

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

        Read state by state rather than through one predicate, because
        `EntitiesRepository.proposals` filters by a single state and
        `OPEN_EQUIVALENT_PROPOSAL_STATES` names three. A repository read keyed on
        `(principal_id, dedupe_sha256)` — the columns the partial unique index is
        already over — would answer this in one statement; it does not exist yet,
        and adding it is a port change. The index is the authority either way:
        this read is what turns a would-be integrity error into the open proposal
        the producer was going to be told about.
        """
        for state in sorted(OPEN_EQUIVALENT_PROPOSAL_STATES):
            for held in self._entities.proposals(principal_id, state):
                if held.dedupe_sha256 == digest:
                    return held
        return None

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
    ) -> EntityProposal:
        """Record that a proposal was accepted. Mutates nothing else.

        `has_operator_authority` is a parameter the caller must pass rather than
        anything this module can infer. A `REQUIRES_OPERATOR` proposal — today, a
        merge or a split — is refused without it, and that refusal is about who
        may *record the acceptance*: what the acceptance establishes is reviewed
        identity-correction intent, and the identity change it asks for is a
        separate act under a separate capability. See the module docstring for
        the division and for what this method used to do instead.
        """
        return self._decide(
            principal_id,
            proposal_id,
            state=EntityProposalState.ACCEPTED,
            decided_by=decided_by,
            decided_at=decided_at,
            reason=reason,
            has_operator_authority=has_operator_authority,
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

    No review case identifier and no review version. The Review plane opens the
    case, and a producer handed a case identifier by the path that created the
    proposal would hold half of a reviewer's read.
    """

    proposal_id: str
    kind: EntityProposalKind
    state: EntityProposalState
    requirement: ReviewRequirement
    dedupe_sha256: str
    observation_ids: tuple[str, ...]
    proposed_at: datetime
    #: False when an open-equivalent proposal already said this, in which case
    #: every other field describes *that* proposal. The producer's request was
    #: understood and nothing was written.
    created: bool


def _admission(proposal: EntityProposal, *, created: bool) -> ProposalAdmission:
    return ProposalAdmission(
        proposal_id=proposal.proposal_id,
        kind=proposal.kind,
        state=proposal.state,
        requirement=proposal.requirement,
        dedupe_sha256=proposal.dedupe_sha256,
        observation_ids=proposal.observation_ids,
        proposed_at=proposal.proposed_at,
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
