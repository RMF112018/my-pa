"""Application orchestration for durable Relationship Intelligence re-enrichment."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime

from my_pa.contracts.ports import ReenrichmentWorkRepository
from my_pa.domain.common.time import ensure_utc
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
    "register_mutation_reenrichment",
    "register_producer_version_observation",
    "register_source_version_observation",
]

REENRICHMENT_PRODUCER_VERSION = "relationship-intelligence-v0.2"


type ReenrichmentApplication = Callable[[ReenrichmentBinding, str], None]


# Every v0.2 section 27.4 trigger is attached to an already-authorized mutation
# path.  One mutation may intentionally invalidate more than one derivation.
# The mapping is closed and tested; adding a trigger without a caller fails.
TRIGGERS_BY_MUTATION_CAPABILITY: Mapping[str, tuple[ReenrichmentTrigger, ...]] = {
    "entities.merge": (ReenrichmentTrigger.CORRECTED_IDENTITY,),
    "entities.split": (ReenrichmentTrigger.CORRECTED_IDENTITY,),
    "entities.aliases.add": (ReenrichmentTrigger.NEW_ALIAS,),
    "entities.aliases.supersede": (ReenrichmentTrigger.NEW_ALIAS,),
    "entities.assignments.create": (ReenrichmentTrigger.PROJECT_MAPPING_CHANGE,),
    "entities.assignments.revise": (ReenrichmentTrigger.PROJECT_MAPPING_CHANGE,),
    "entities.assignments.end": (ReenrichmentTrigger.PROJECT_MAPPING_CHANGE,),
    "entities.update": (ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,),
    "capture.revise": (ReenrichmentTrigger.ACCEPTED_QUICK_CAPTURE_CORRECTION,),
    "entities.unresolved_mentions.resolve": (ReenrichmentTrigger.CONTRADICTION_RESOLUTION,),
    "review.decide": (ReenrichmentTrigger.CONTRADICTION_RESOLUTION,),
    "context.feedback": (ReenrichmentTrigger.POLICY_CHANGE,),
}


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
            input_versions=(BindingVersion("source_version", source_version_id),),
            producer_versions=(BindingVersion("source_pipeline", "sources.fetch.v1"),),
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
    producer_versions = [
        BindingVersion("proposal_method", method),
        BindingVersion("proposal_pipeline", method_version),
    ]
    if model_id is not None and model_version is not None:
        producer_versions.extend(
            (
                BindingVersion("model_id", model_id),
                BindingVersion("model_version", model_version),
            )
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
            producer_versions=tuple(producer_versions),
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
    triggers = TRIGGERS_BY_MUTATION_CAPABILITY.get(capability, ())
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
                        policy_version,
                    ),
                ),
                input_versions=(BindingVersion("mutation_capability", capability),),
                producer_versions=(BindingVersion("ri_contract", "v0.2"),),
                policy_version=policy_version,
            ),
            at=at,
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
