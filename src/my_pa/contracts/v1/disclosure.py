"""The mandatory disclosure envelope.

Every successful or partial result states its scope, coverage, freshness, trust,
truncation, limitations, source references, and unavailable evidence. Counts are
scoped to the authorized enrollment and never imply global coverage
(`docs/specs`, section 8.3).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from my_pa.contracts.v1.base import StrictModel, UtcDatetime
from my_pa.domain.common.classification import Classification, is_cloud_eligible
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.provenance import TrustLevel

__all__ = [
    "Coverage",
    "CoverageState",
    "Disclosure",
    "Freshness",
    "FreshnessState",
    "Scope",
    "SourceReference",
    "Truncation",
    "Trust",
]


class CoverageState(StrEnum):
    """Distinct coverage states; none of them collapses into "empty"."""

    NOT_ENROLLED = "not_enrolled"
    ELIGIBLE = "eligible"
    QUEUED = "queued"
    PROCESSED = "processed"
    PARTIALLY_PROCESSED = "partially_processed"
    UNSUPPORTED = "unsupported"
    QUARANTINED = "quarantined"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    SUPERSEDED = "superseded"


class FreshnessState(StrEnum):
    """How current the observed state is."""

    CURRENT_FOR_OBSERVED_VERSION = "current_for_observed_version"
    STALE = "stale"
    UNKNOWN = "unknown"


def _validate_ids(values: tuple[str, ...], kind: IdKind) -> tuple[str, ...]:
    for value in values:
        validate_identifier(value, kind)
    return values


class Scope(StrictModel):
    """The authorized scope a result was produced within."""

    source_ids: tuple[str, ...] = ()
    enrollment_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check_identifiers(self) -> Scope:
        _validate_ids(self.source_ids, IdKind.SOURCE)
        _validate_ids(self.enrollment_ids, IdKind.ENROLLMENT)
        return self


class Coverage(StrictModel):
    """Bounded counts for the stated scope."""

    state: CoverageState
    eligible: int = Field(default=0, ge=0)
    processed: int = Field(default=0, ge=0)
    quarantined: int = Field(default=0, ge=0)
    unsupported: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check_totals(self) -> Coverage:
        accounted = self.processed + self.quarantined + self.unsupported
        if accounted > self.eligible:
            raise ValueError("processed, quarantined and unsupported cannot exceed eligible")
        return self


class Freshness(StrictModel):
    """When the reported state was observed."""

    observed_at: UtcDatetime
    state: FreshnessState


class Trust(StrictModel):
    """How much authority the result carries and why."""

    level: TrustLevel
    basis: tuple[str, ...] = ()


class Truncation(StrictModel):
    """Explicit truncation, never an unmarked complete-looking response."""

    is_truncated: bool = False
    reason: str | None = None
    next_cursor: str | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> Truncation:
        if self.is_truncated and not self.reason:
            raise ValueError("a truncated result must state a reason")
        if not self.is_truncated and (self.reason or self.next_cursor):
            raise ValueError("an untruncated result cannot carry truncation details")
        return self


class SourceReference(StrictModel):
    """Opaque binding to the source state a result came from."""

    source_id: str
    source_object_id: str
    version_id: str

    @model_validator(mode="after")
    def _check_identifiers(self) -> SourceReference:
        validate_identifier(self.source_id, IdKind.SOURCE)
        validate_identifier(self.source_object_id, IdKind.SOURCE_OBJECT)
        validate_identifier(self.version_id, IdKind.VERSION)
        return self


class Disclosure(StrictModel):
    """The mandatory envelope accompanying every success or partial result."""

    scope: Scope
    coverage: Coverage
    freshness: Freshness
    trust: Trust
    truncation: Truncation = Truncation()
    limitations: tuple[str, ...] = ()
    source_references: tuple[SourceReference, ...] = ()
    unavailable_evidence: tuple[str, ...] = ()
    partial_result: bool = False
    classification: Classification = Classification.PRIVATE_LOCAL
    cloud_eligible: bool = False

    @model_validator(mode="after")
    def _check_partial_is_truthful(self) -> Disclosure:
        partial_states = {
            CoverageState.PARTIALLY_PROCESSED,
            CoverageState.QUARANTINED,
            CoverageState.UNSUPPORTED,
            CoverageState.UNAVAILABLE,
            CoverageState.STALE,
        }
        if self.coverage.state in partial_states and not self.partial_result:
            raise ValueError(f"coverage state {self.coverage.state} requires partial_result=True")
        if self.truncation.is_truncated and not self.partial_result:
            raise ValueError("a truncated result must set partial_result=True")
        return self

    @model_validator(mode="after")
    def _check_cloud_eligibility(self) -> Disclosure:
        """Reject a disclosure claiming eligibility the classification denies.

        Without this the mandatory envelope could assert that restricted local
        content may leave the trust boundary, contradicting the domain rule it
        is supposed to be reporting.
        """
        if self.cloud_eligible and not is_cloud_eligible(self.classification):
            raise ValueError(f"classification {self.classification} is never cloud eligible")
        return self
