"""Application orchestration for durable Relationship Intelligence re-enrichment."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Final

from my_pa.contracts.ports import ReenrichmentWorkRepository
from my_pa.domain.capture.proposal import ProposalState
from my_pa.domain.capture.review import Disposition
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.relationship.proposal_payload import EntityProposalKind
from my_pa.domain.relationship.reenrichment import (
    DEFAULT_MAX_REENRICHMENT_ATTEMPTS,
    MAX_REENRICHMENT_SUBJECTS,
    MAX_REENRICHMENT_VERSIONS,
    BindingCurrency,
    BindingVersion,
    CurrentReenrichmentBindings,
    ReenrichmentBinding,
    ReenrichmentLimitation,
    ReenrichmentState,
    ReenrichmentSubject,
    ReenrichmentSubjectKind,
    ReenrichmentTrigger,
    ReenrichmentWork,
    StaleBindingReason,
    assess_currency,
)

__all__ = [
    "DEFAULT_MAX_REENRICHMENT_ATTEMPTS",
    "MAX_REENRICHMENT_SUBJECTS",
    "MAX_REENRICHMENT_VERSIONS",
    "TRIGGERS_BY_ACCEPTED_PROPOSAL_KIND",
    "TRIGGERS_BY_MUTATION_CAPABILITY",
    "BindingCurrency",
    "BindingVersion",
    "CurrentReenrichmentBindings",
    "EntityReenrichmentService",
    "ProductionReenrichmentCaller",
    "ReenrichmentApplication",
    "ReenrichmentBinding",
    "ReenrichmentLimitation",
    "ReenrichmentState",
    "ReenrichmentSubject",
    "ReenrichmentSubjectKind",
    "ReenrichmentTrigger",
    "ReenrichmentWork",
    "ReenrichmentWorkRepository",
    "StaleBindingReason",
    "assess_currency",
    "reenrichment_trigger_for_review_decision",
    "register_mutation_reenrichment",
    "register_producer_version_observation",
    "register_source_version_observation",
]

REENRICHMENT_PRODUCER_VERSION = "relationship-intelligence-v0.2"
SOURCE_PIPELINE_VERSION = "sources.fetch.v1"


type ReenrichmentApplication = Callable[[ReenrichmentBinding, str], None]


# Generic handler-attested mutation callers only. Capabilities whose handlers
# register a more precise subject binding directly are deliberately absent, so
# one mutation cannot also create Principal-wide generic work. Together with
# those direct callers and the source/producer observers, all nine v0.2 section
# 27.4 triggers remain closed and tested.
TRIGGERS_BY_MUTATION_CAPABILITY: Mapping[str, tuple[ReenrichmentTrigger, ...]] = {
    "entities.aliases.supersede": (ReenrichmentTrigger.NEW_ALIAS,),
    "entities.update": (ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,),
    "entities.unresolved_mentions.resolve": (ReenrichmentTrigger.CONTRADICTION_RESOLUTION,),
    "context.feedback": (ReenrichmentTrigger.POLICY_CHANGE,),
}


#: The dispositions that accept, and the states an accepted proposal lands in.
#: Both halves are required: `review.decide` can append an accepting disposition
#: whose promotion did not land -- a span fault invalidates the proposal instead
#: -- and re-enrichment must follow the mutation that actually happened, not the
#: intention that was recorded.
_ACCEPTING_DISPOSITIONS: Final = frozenset({Disposition.ACCEPT, Disposition.CORRECT_AND_ACCEPT})
#: A tuple rather than a `frozenset` deliberately. `tests/architecture/
#: test_no_revision_derives_a_closed_set_from_an_enum.py` harvests every
#: module-level `frozenset` of strings and keys it by *value set*, because
#: "the emitted DDL carries no trace of which enum produced it". These two
#: values collide exactly with `f1c6b904a2d7`'s literal
#: `a_memory_proposal_names_its_result_exactly_when_accepted` vocabulary, so
#: declaring them as a frozenset made that old, unchanged revision report as
#: deriving its CHECK from live code. Membership is all this needs.
_ACCEPTED_PROPOSAL_STATES: Final = (ProposalState.ACCEPTED, ProposalState.CORRECTED_ACCEPTED)


#: What an *accepted* Entity proposal of each kind actually changed, expressed
#: as the trigger the equivalent direct mutation already registers.
#:
#: RI v0.2 section 10.11 defines a contradiction as two or more relevant
#: **assertions** in conflict, which "the user may accept one for current use,
#: retain multiple time-bounded truths, mark disputed, or defer". That is one
#: review outcome, not every review outcome, and `ConsequentialClass` says the
#: same thing structurally by listing `IDENTITY_MERGE` and `CONTRADICTION` as
#: distinct members. `TRIGGERS_BY_MUTATION_CAPABILITY` above is the repository's
#: own authoritative statement of which mutation implies which trigger:
#: `entities.unresolved_mentions.resolve` is the only one that reaches
#: `CONTRADICTION_RESOLUTION`, `entities.aliases.supersede` reaches `NEW_ALIAS`,
#: and `entities.update` reaches `ROLE_OR_ORGANIZATION_CHANGE`. Accepting a
#: proposal executes that same mutation, so it registers that same trigger.
#:
#: **The seven absent kinds are absent because accepting them registers
#: nothing, and each absence has its own reason.**
#:
#: `MERGE_ENTITIES` and `SPLIT_IDENTITY` execute nothing at review time: an
#: acceptance emits an `EntityIdentityCorrectionHandoff` in
#: `OPERATOR_PREVIEW_REQUIRED` and stops there. The later operator
#: `entities.merge` / `entities.split` registers `CORRECTED_IDENTITY` itself.
#: Registering here would name an identity correction that has not happened and
#: may never be authorized.
#:
#: `CREATE_ENTITY`, `BIND_IDENTIFIER`, `RETIRE_IDENTIFIER` and
#: `SUPERSEDE_IDENTIFIER` have no entry in `TRIGGERS_BY_MUTATION_CAPABILITY`
#: either: their direct `entities.*` capabilities register no re-enrichment, so
#: naming a trigger for the reviewed form would make the reviewed path claim an
#: invalidation the direct path does not.
TRIGGERS_BY_ACCEPTED_PROPOSAL_KIND: Mapping[EntityProposalKind, ReenrichmentTrigger] = {
    EntityProposalKind.RESOLVE_MENTION: ReenrichmentTrigger.CONTRADICTION_RESOLUTION,
    EntityProposalKind.RECORD_ALIAS: ReenrichmentTrigger.NEW_ALIAS,
    EntityProposalKind.SUPERSEDE_ALIAS: ReenrichmentTrigger.NEW_ALIAS,
    EntityProposalKind.RETIRE_ALIAS: ReenrichmentTrigger.NEW_ALIAS,
    EntityProposalKind.UPDATE_ENTITY: ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,
    EntityProposalKind.RECORD_ASSIGNMENT: ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,
    EntityProposalKind.REVISE_ASSIGNMENT: ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,
    EntityProposalKind.END_ASSIGNMENT: ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,
    EntityProposalKind.RECORD_RELATIONSHIP: ReenrichmentTrigger.PROJECT_MAPPING_CHANGE,
    EntityProposalKind.REVISE_RELATIONSHIP: ReenrichmentTrigger.PROJECT_MAPPING_CHANGE,
    EntityProposalKind.END_RELATIONSHIP: ReenrichmentTrigger.PROJECT_MAPPING_CHANGE,
}


def reenrichment_trigger_for_review_decision(
    *,
    proposed_kind: EntityProposalKind | None,
    disposition: Disposition,
    proposal_state: ProposalState,
) -> ReenrichmentTrigger | None:
    """Which invalidation one committed review decision implies, or none.

    Pure and total: it reads three closed values a decision already carries and
    returns a trigger or `None`. It reads no payload, because
    `EntityProposalReviewCase` deliberately withholds payload values as a
    disclosure control and a predicate that needed them would have to defeat it.

    `proposed_kind` is `None` for the three review subject kinds that are not
    Entity proposals -- `capture_proposal`, `goodnotes_region` and
    `relationship_memory`. They reach the decision handler with no proposed
    Entity mutation, so there is no equivalent direct mutation whose trigger
    this could name, and it names none. That is narrower than the behaviour it
    replaces, which registered `CONTRADICTION_RESOLUTION` for all four subject
    kinds and all eight dispositions; see the module note in
    `tests/unit/test_entity_reenrichment.py` for what that leaves open.
    """
    if proposed_kind is None:
        return None
    if disposition not in _ACCEPTING_DISPOSITIONS:
        return None
    if proposal_state not in _ACCEPTED_PROPOSAL_STATES:
        return None
    return TRIGGERS_BY_ACCEPTED_PROPOSAL_KIND.get(proposed_kind)


def register_source_version_observation(
    repository: ReenrichmentWorkRepository,
    *,
    principal_id: str,
    source_object_id: str,
    source_version_id: str,
    policy_version: str,
    at: datetime,
) -> ReenrichmentWork | None:
    """Register an exact source-version advance after a verified fetch."""
    moment = ensure_utc(at)
    watermark_key = f"source_{hashlib.sha256(source_object_id.encode()).hexdigest()[:40]}"
    observation = repository.observe_version(
        principal_id,
        namespace="input",
        key=watermark_key,
        version=source_version_id,
        at=moment,
    )
    if not observation.changed:
        return None
    repository.observe_version(
        principal_id,
        namespace="producer",
        key="source_pipeline",
        version=SOURCE_PIPELINE_VERSION,
        at=moment,
    )
    repository.observe_version(
        principal_id,
        namespace="policy",
        key="current",
        version=policy_version,
        at=moment,
    )
    return repository.register(
        ReenrichmentBinding(
            principal_id=principal_id,
            trigger=ReenrichmentTrigger.SOURCE_VERSION_CHANGE,
            cause_record_id=source_version_id,
            subjects=(
                ReenrichmentSubject(
                    ReenrichmentSubjectKind.SOURCE_OBJECT,
                    source_object_id,
                    source_version_id,
                ),
                ReenrichmentSubject(
                    ReenrichmentSubjectKind.SOURCE_VERSION,
                    source_version_id,
                    source_version_id,
                ),
            ),
            input_versions=(BindingVersion(watermark_key, source_version_id),),
            producer_versions=(BindingVersion("source_pipeline", SOURCE_PIPELINE_VERSION),),
            policy_version=policy_version,
        ),
        at=moment,
    )


def register_producer_version_observation(
    repository: ReenrichmentWorkRepository,
    *,
    principal_id: str,
    proposal_id: str,
    proposal_version: str,
    method: str,
    method_version: str,
    model_id: str | None,
    model_version: str | None,
    policy_version: str,
    at: datetime,
) -> ReenrichmentWork | None:
    """Register an exact authenticated proposal-producer advance."""
    moment = ensure_utc(at)
    observed = {
        "method": method,
        "method_version": method_version,
        "model_id": model_id,
        "model_version": model_version,
    }
    digest = hashlib.sha256(
        json.dumps(observed, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    observation = repository.observe_version(
        principal_id,
        namespace="producer",
        key="entity_proposal",
        version=digest,
        at=moment,
    )
    if not observation.changed:
        return None
    repository.observe_version(
        principal_id,
        namespace="policy",
        key="current",
        version=policy_version,
        at=moment,
    )
    return repository.register(
        ReenrichmentBinding(
            principal_id=principal_id,
            trigger=ReenrichmentTrigger.MODEL_OR_RULE_VERSION_CHANGE,
            cause_record_id=proposal_id,
            subjects=(
                ReenrichmentSubject(
                    ReenrichmentSubjectKind.PROPOSAL,
                    proposal_id,
                    proposal_version,
                ),
            ),
            input_versions=(),
            producer_versions=(BindingVersion("entity_proposal", digest),),
            policy_version=policy_version,
        ),
        at=moment,
    )


def register_mutation_reenrichment(
    repository: ReenrichmentWorkRepository,
    *,
    principal_id: str,
    capability: str,
    cause_record_id: str,
    policy_version: str,
    at: datetime,
) -> tuple[ReenrichmentWork, ...]:
    """Register every invalidation implied by one committed mutation.

    The Principal is the deliberately minimal affected subject. More specific
    affected records remain inputs to the downstream derivation; this hook does
    not reimplement or infer the authoritative mutation's result.
    """
    moment = ensure_utc(at)
    triggers = TRIGGERS_BY_MUTATION_CAPABILITY.get(capability, ())
    if not triggers:
        return ()
    repository.observe_version(
        principal_id,
        namespace="producer",
        key="relationship_intelligence",
        version=REENRICHMENT_PRODUCER_VERSION,
        at=moment,
    )
    repository.observe_version(
        principal_id,
        namespace="policy",
        key="current",
        version=policy_version,
        at=moment,
    )
    return tuple(
        repository.register(
            ReenrichmentBinding(
                principal_id=principal_id,
                trigger=trigger,
                cause_record_id=cause_record_id,
                subjects=(
                    ReenrichmentSubject(
                        ReenrichmentSubjectKind.PRINCIPAL,
                        principal_id,
                        "1",
                    ),
                ),
                input_versions=(),
                producer_versions=(
                    BindingVersion(
                        "relationship_intelligence",
                        REENRICHMENT_PRODUCER_VERSION,
                    ),
                ),
                policy_version=policy_version,
            ),
            at=moment,
        )
        for trigger in triggers
    )


class ProductionReenrichmentCaller:
    """The nine production event callers, sharing one exact binding builder."""

    def __init__(
        self,
        repository: ReenrichmentWorkRepository,
        *,
        principal_id: str,
        policy_version: str,
        producer_version: str = REENRICHMENT_PRODUCER_VERSION,
    ) -> None:
        self._repository = repository
        self._principal_id = principal_id
        self._policy_version = policy_version
        self._producer_version = producer_version

    def corrected_identity(
        self, cause: str, subjects: Sequence[ReenrichmentSubject], *, at: datetime
    ) -> ReenrichmentWork:
        return self._register(ReenrichmentTrigger.CORRECTED_IDENTITY, cause, subjects, at=at)

    def new_alias(
        self, cause: str, subjects: Sequence[ReenrichmentSubject], *, at: datetime
    ) -> ReenrichmentWork:
        return self._register(ReenrichmentTrigger.NEW_ALIAS, cause, subjects, at=at)

    def project_mapping_change(
        self, cause: str, subjects: Sequence[ReenrichmentSubject], *, at: datetime
    ) -> ReenrichmentWork:
        return self._register(ReenrichmentTrigger.PROJECT_MAPPING_CHANGE, cause, subjects, at=at)

    def role_or_organization_change(
        self, cause: str, subjects: Sequence[ReenrichmentSubject], *, at: datetime
    ) -> ReenrichmentWork:
        return self._register(
            ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE, cause, subjects, at=at
        )

    def source_version_change(
        self, cause: str, subjects: Sequence[ReenrichmentSubject], *, at: datetime
    ) -> ReenrichmentWork:
        return self._register(ReenrichmentTrigger.SOURCE_VERSION_CHANGE, cause, subjects, at=at)

    def model_or_rule_version_change(
        self, cause: str, subjects: Sequence[ReenrichmentSubject], *, at: datetime
    ) -> ReenrichmentWork:
        return self._register(
            ReenrichmentTrigger.MODEL_OR_RULE_VERSION_CHANGE, cause, subjects, at=at
        )

    def accepted_quick_capture_correction(
        self, cause: str, subjects: Sequence[ReenrichmentSubject], *, at: datetime
    ) -> ReenrichmentWork:
        return self._register(
            ReenrichmentTrigger.ACCEPTED_QUICK_CAPTURE_CORRECTION, cause, subjects, at=at
        )

    def contradiction_resolution(
        self, cause: str, subjects: Sequence[ReenrichmentSubject], *, at: datetime
    ) -> ReenrichmentWork:
        return self._register(ReenrichmentTrigger.CONTRADICTION_RESOLUTION, cause, subjects, at=at)

    def policy_change(
        self, cause: str, subjects: Sequence[ReenrichmentSubject], *, at: datetime
    ) -> ReenrichmentWork:
        return self._register(ReenrichmentTrigger.POLICY_CHANGE, cause, subjects, at=at)

    def register(
        self,
        trigger: ReenrichmentTrigger,
        cause: str,
        subjects: Sequence[ReenrichmentSubject],
        *,
        at: datetime,
    ) -> ReenrichmentWork:
        """Register one closed trigger without dynamic attribute dispatch."""
        return self._register(trigger, cause, subjects, at=at)

    def observe_process_versions(
        self, principal_id: str, *, cause: str, at: datetime
    ) -> tuple[ReenrichmentWork, ...]:
        """Register startup work only when the server policy advanced."""
        moment = ensure_utc(at)
        subject = (ReenrichmentSubject(ReenrichmentSubjectKind.PRINCIPAL, principal_id, "1"),)
        policy = self._repository.observe_version(
            principal_id,
            namespace="policy",
            key="current",
            version=self._policy_version,
            at=moment,
        )
        registered: list[ReenrichmentWork] = []
        if policy.changed:
            registered.append(self.policy_change(cause, subject, at=moment))
        return tuple(registered)

    def _register(
        self,
        trigger: ReenrichmentTrigger,
        cause: str,
        subjects: Sequence[ReenrichmentSubject],
        *,
        at: datetime,
    ) -> ReenrichmentWork:
        moment = ensure_utc(at)
        principal_id = self._principal_id
        self._repository.observe_version(
            principal_id,
            namespace="producer",
            key="relationship_intelligence",
            version=self._producer_version,
            at=moment,
        )
        self._repository.observe_version(
            principal_id,
            namespace="policy",
            key="current",
            version=self._policy_version,
            at=moment,
        )
        return self._repository.register(
            ReenrichmentBinding(
                principal_id=principal_id,
                trigger=trigger,
                cause_record_id=cause,
                subjects=tuple(subjects),
                input_versions=(),
                producer_versions=(
                    BindingVersion("relationship_intelligence", self._producer_version),
                ),
                policy_version=self._policy_version,
            ),
            at=moment,
        )


class EntityReenrichmentService:
    """Register work and gate one claimed attempt on exact current versions."""

    def __init__(self, repository: ReenrichmentWorkRepository) -> None:
        self._repository = repository

    def register(self, binding: ReenrichmentBinding, *, at: datetime) -> ReenrichmentWork:
        return self._repository.register(binding, at=ensure_utc(at))

    def apply_claimed(
        self,
        work: ReenrichmentWork,
        *,
        owner: str,
        current: CurrentReenrichmentBindings,
        apply: ReenrichmentApplication,
        at: datetime,
    ) -> BindingCurrency:
        """Apply under the repository's transaction and exclusive work lock.

        The callback receives the binding digest as its mandatory idempotency
        identity. The repository revalidates lease and currency while holding
        the work/Principal locks and completes in the same transaction, so a
        reclaim cannot overlap or preserve a partial derived mutation.
        """
        if work.state is not ReenrichmentState.RUNNING or work.lease_owner != owner:
            raise ValueError("re-enrichment application requires this worker's live claim")
        moment = ensure_utc(at)
        if work.lease_expires_at is None or work.lease_expires_at <= moment:
            raise ValueError("re-enrichment application requires this worker's live claim")
        return self._repository.apply_claimed(
            work.binding.principal_id,
            work.work_id,
            owner=owner,
            current=current,
            apply=apply,
            at=moment,
        )
