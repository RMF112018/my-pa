"""Application orchestration for durable Relationship Intelligence re-enrichment."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Protocol

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
]


class ReenrichmentWorkRepository(Protocol):
    def register(self, binding: ReenrichmentBinding, *, at: datetime) -> ReenrichmentWork: ...

    def apply_claimed(
        self,
        principal_id: str,
        work_id: str,
        *,
        owner: str,
        current: CurrentReenrichmentBindings,
        apply: ReenrichmentApplication,
        at: datetime,
    ) -> BindingCurrency: ...


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
    "sources.enroll": (ReenrichmentTrigger.SOURCE_VERSION_CHANGE,),
    "entities.proposals.create": (ReenrichmentTrigger.MODEL_OR_RULE_VERSION_CHANGE,),
    "capture.revise": (ReenrichmentTrigger.ACCEPTED_QUICK_CAPTURE_CORRECTION,),
    "entities.unresolved_mentions.resolve": (ReenrichmentTrigger.CONTRADICTION_RESOLUTION,),
    "review.decide": (ReenrichmentTrigger.CONTRADICTION_RESOLUTION,),
    "context.feedback": (ReenrichmentTrigger.POLICY_CHANGE,),
}


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
