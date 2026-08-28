"""Application orchestration for durable Relationship Intelligence re-enrichment."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Protocol

from my_pa.domain.common.time import ensure_utc
from my_pa.domain.relationship.reenrichment import (
    DEFAULT_MAX_REENRICHMENT_ATTEMPTS,
    MAX_REENRICHMENT_SUBJECTS,
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
]


class ReenrichmentWorkRepository(Protocol):
    def register(self, binding: ReenrichmentBinding, *, at: datetime) -> ReenrichmentWork: ...

    def mark_stale(
        self,
        principal_id: str,
        work_id: str,
        *,
        owner: str,
        reasons: Sequence[StaleBindingReason],
        at: datetime,
    ) -> bool: ...

    def complete(self, principal_id: str, work_id: str, *, owner: str, at: datetime) -> bool: ...


type ReenrichmentApplication = Callable[[ReenrichmentBinding], None]


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
        """Apply only a current claimed binding; stale work mutates nothing."""
        if work.state is not ReenrichmentState.RUNNING or work.lease_owner != owner:
            raise ValueError("re-enrichment application requires this worker's live claim")
        moment = ensure_utc(at)
        if work.lease_expires_at is None or work.lease_expires_at <= moment:
            raise ValueError("re-enrichment application requires this worker's live claim")
        currency = assess_currency(work.binding, current)
        if not currency.is_current:
            if not self._repository.mark_stale(
                work.binding.principal_id,
                work.work_id,
                owner=owner,
                reasons=currency.reasons,
                at=moment,
            ):
                raise RuntimeError("the re-enrichment lease was lost before stale completion")
            return currency
        apply(work.binding)
        if not self._repository.complete(
            work.binding.principal_id, work.work_id, owner=owner, at=moment
        ):
            raise RuntimeError("the re-enrichment lease was lost before completion")
        return currency
