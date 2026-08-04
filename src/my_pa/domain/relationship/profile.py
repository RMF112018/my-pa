"""Deterministic relationship profile and timeline read models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.relationship.identity import Alias

__all__ = [
    "CoverageDomain",
    "EvidenceAuthority",
    "EvidenceItem",
    "OrganizationProfile",
    "PersonProfile",
    "ProfileIndicator",
    "RelationshipFreshness",
    "TimelineItem",
]


class EvidenceAuthority(StrEnum):
    SOURCE_OBSERVATION = "source_observation"
    ACCEPTED_ASSERTION = "accepted_assertion"
    USER_AUTHORED_PRIVATE_NOTE = "user_authored_private_note"
    PUBLIC_ASSERTION = "public_assertion"
    MODEL_INFERENCE = "model_inference"
    UNRESOLVED_CLAIM = "unresolved_claim"
    CONTRADICTION = "contradiction"
    STALE_ASSERTION = "stale_assertion"


class RelationshipFreshness(StrEnum):
    UNKNOWN = "unknown"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class CoverageDomain:
    domain: str
    state: CoverageState
    observation_ids: tuple[str, ...]
    observed_at: datetime | None
    as_of: datetime
    freshness: RelationshipFreshness
    limitation: str | None = None
    zero_result_basis: str | None = None

    def __post_init__(self) -> None:
        if not self.domain.strip():
            raise ValueError("a coverage domain is not blank")
        for observation_id in self.observation_ids:
            validate_identifier(observation_id, IdKind.IDENTITY_OBSERVATION)
        if self.observed_at is not None:
            ensure_utc(self.observed_at)
        ensure_utc(self.as_of)
        if self.observed_at is not None and self.observed_at > self.as_of:
            raise ValueError("coverage cannot observe evidence after its as-of time")
        if self.state is CoverageState.UNAVAILABLE and self.limitation is None:
            raise ValueError("unavailable coverage states why")
        if self.state is CoverageState.PROCESSED and self.observed_at is None:
            raise ValueError("processed coverage records when the search completed")
        if (
            self.state is CoverageState.PROCESSED
            and not self.observation_ids
            and not (self.zero_result_basis and self.zero_result_basis.strip())
        ):
            raise ValueError("processed empty coverage states its zero-result basis")
        if self.observation_ids and self.zero_result_basis is not None:
            raise ValueError("a zero-result basis belongs only to an empty result")
        if self.state is CoverageState.UNAVAILABLE and (
            self.observation_ids or self.observed_at is not None
        ):
            raise ValueError("unavailable coverage carries no observed evidence")
        if self.state is CoverageState.UNAVAILABLE and self.zero_result_basis is not None:
            raise ValueError("unavailable coverage cannot claim a successful zero-result search")
        if (self.state is CoverageState.UNAVAILABLE) is not (
            self.freshness is RelationshipFreshness.UNAVAILABLE
        ):
            raise ValueError("unavailable coverage has unavailable freshness")


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    evidence_id: str
    authority: EvidenceAuthority
    observation_ids: tuple[str, ...]
    effective_at: datetime | None
    recorded_at: datetime

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("an evidence identifier is not blank")
        for observation_id in self.observation_ids:
            validate_identifier(observation_id, IdKind.IDENTITY_OBSERVATION)
        if self.authority is EvidenceAuthority.SOURCE_OBSERVATION and not self.observation_ids:
            raise ValueError("a source observation cites an observation")
        if self.effective_at is not None:
            ensure_utc(self.effective_at)
        ensure_utc(self.recorded_at)


@dataclass(frozen=True, slots=True)
class ProfileIndicator:
    name: str
    value: int | str
    calculation_basis: str
    window_start: datetime
    window_end: datetime

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.calculation_basis.strip():
            raise ValueError("an indicator names its calculation basis")
        ensure_utc(self.window_start)
        ensure_utc(self.window_end)
        if self.window_end < self.window_start:
            raise ValueError("an indicator window ends after it starts")


@dataclass(frozen=True, slots=True)
class TimelineItem:
    timeline_item_id: str
    person_id: str
    occurred_at: datetime
    observation_ids: tuple[str, ...]
    authority: EvidenceAuthority

    def __post_init__(self) -> None:
        validate_identifier(self.timeline_item_id, IdKind.TIMELINE_ITEM)
        validate_identifier(self.person_id, IdKind.PERSON)
        ensure_utc(self.occurred_at)
        if not self.observation_ids:
            raise ValueError("a timeline item cites its exact observation set")
        for observation_id in self.observation_ids:
            validate_identifier(observation_id, IdKind.IDENTITY_OBSERVATION)


@dataclass(frozen=True, slots=True)
class PersonProfile:
    person_id: str
    display_name: str
    observation_ids: tuple[str, ...]
    coverage: tuple[CoverageDomain, ...]
    evidence: tuple[EvidenceItem, ...]
    timeline: tuple[TimelineItem, ...]
    aliases: tuple[Alias, ...] = ()
    indicators: tuple[ProfileIndicator, ...] = ()
    completeness_claimed: bool = False

    def __post_init__(self) -> None:
        validate_identifier(self.person_id, IdKind.PERSON)
        if self.completeness_claimed:
            raise ValueError("a relationship profile never claims completeness")
        exact = set(self.observation_ids)
        for observation_id in self.observation_ids:
            validate_identifier(observation_id, IdKind.IDENTITY_OBSERVATION)
        disclosed = {item for domain in self.coverage for item in domain.observation_ids}
        if disclosed != exact:
            raise ValueError("profile coverage names the exact observation set")
        if not self.coverage:
            raise ValueError("a profile discloses coverage, including unavailable domains")


@dataclass(frozen=True, slots=True)
class OrganizationProfile:
    organization_id: str
    display_name: str
    affiliations: tuple[tuple[str, str | None, datetime | None, datetime | None], ...]
    observation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_identifier(self.organization_id, IdKind.ORGANIZATION)
        for person_id, _role, effective_from, effective_to in self.affiliations:
            validate_identifier(person_id, IdKind.PERSON)
            if effective_from is not None:
                ensure_utc(effective_from)
            if effective_to is not None:
                ensure_utc(effective_to)
            if (
                effective_from is not None
                and effective_to is not None
                and effective_to < effective_from
            ):
                raise ValueError("an organization affiliation is time-aware")
        for observation_id in self.observation_ids:
            validate_identifier(observation_id, IdKind.IDENTITY_OBSERVATION)
