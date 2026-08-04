"""Durable identities remain distinct from source observations.

The constructors deliberately offer no observation-to-person promotion and no
person merge. Those transitions are represented only by :class:`IdentityResolution`,
which requires a completed review and retains the inverse mapping needed to split.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "Affiliation",
    "Alias",
    "DuplicateCandidateSet",
    "IdentityCandidateSet",
    "IdentityObservation",
    "IdentityResolution",
    "IdentityResolutionError",
    "Organization",
    "Person",
    "ResolutionAction",
    "UnresolvedMention",
]


class IdentityResolutionError(ValueError):
    """A canonical identity transition failed closed."""


class ResolutionAction(StrEnum):
    LINK_OBSERVATION = "link_observation"
    MERGE_PERSON = "merge_person"
    SPLIT_PERSON = "split_person"


@dataclass(frozen=True, slots=True)
class Person:
    person_id: str
    display_name: str
    created_at: datetime
    superseded_by_person_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.person_id, IdKind.PERSON)
        if self.superseded_by_person_id is not None:
            validate_identifier(self.superseded_by_person_id, IdKind.PERSON)
            if self.superseded_by_person_id == self.person_id:
                raise IdentityResolutionError("a person cannot supersede itself")
        if not self.display_name.strip():
            raise IdentityResolutionError("a person display name is not blank")
        ensure_utc(self.created_at)


@dataclass(frozen=True, slots=True)
class Organization:
    organization_id: str
    display_name: str
    created_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.organization_id, IdKind.ORGANIZATION)
        if not self.display_name.strip():
            raise IdentityResolutionError("an organization display name is not blank")
        ensure_utc(self.created_at)


@dataclass(frozen=True, slots=True)
class IdentityObservation:
    observation_id: str
    source_id: str
    source_object_id: str
    source_version: str
    observed_at: datetime
    display_name: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.observation_id, IdKind.IDENTITY_OBSERVATION)
        validate_identifier(self.source_id, IdKind.SOURCE)
        validate_identifier(self.source_object_id, IdKind.SOURCE_OBJECT)
        if not self.source_version.strip():
            raise IdentityResolutionError("a source version is not blank")
        if len(self.source_version) > 72:
            raise IdentityResolutionError("a source version is bounded")
        ensure_utc(self.observed_at)


@dataclass(frozen=True, slots=True)
class Alias:
    alias_id: str
    person_id: str
    value: str
    observation_id: str

    def __post_init__(self) -> None:
        validate_identifier(self.alias_id, IdKind.ALIAS)
        validate_identifier(self.person_id, IdKind.PERSON)
        validate_identifier(self.observation_id, IdKind.IDENTITY_OBSERVATION)
        if not self.value.strip():
            raise IdentityResolutionError("an alias is not blank")


@dataclass(frozen=True, slots=True)
class Affiliation:
    affiliation_id: str
    person_id: str
    organization_id: str
    observation_id: str
    role: str | None
    effective_from: datetime | None
    effective_to: datetime | None

    def __post_init__(self) -> None:
        validate_identifier(self.affiliation_id, IdKind.AFFILIATION)
        validate_identifier(self.person_id, IdKind.PERSON)
        validate_identifier(self.organization_id, IdKind.ORGANIZATION)
        validate_identifier(self.observation_id, IdKind.IDENTITY_OBSERVATION)
        if self.effective_from is not None:
            ensure_utc(self.effective_from)
        if self.effective_to is not None:
            ensure_utc(self.effective_to)
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise IdentityResolutionError("an affiliation cannot end before it begins")


@dataclass(frozen=True, slots=True)
class UnresolvedMention:
    unresolved_mention_id: str
    source_object_id: str
    source_version: str
    observed_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.unresolved_mention_id, IdKind.UNRESOLVED_MENTION)
        validate_identifier(self.source_object_id, IdKind.SOURCE_OBJECT)
        if not self.source_version.strip():
            raise IdentityResolutionError("a source version is not blank")
        if len(self.source_version) > 72:
            raise IdentityResolutionError("a source version is bounded")
        ensure_utc(self.observed_at)


@dataclass(frozen=True, slots=True)
class IdentityCandidateSet:
    candidate_set_id: str
    person_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.candidate_set_id, IdKind.DUPLICATE_SET)
        if not self.person_ids and not self.observation_ids:
            raise IdentityResolutionError("an identity candidate set is not empty")
        if len(self.person_ids) != len(set(self.person_ids)):
            raise IdentityResolutionError("an identity candidate set repeats no person")
        if len(self.observation_ids) != len(set(self.observation_ids)):
            raise IdentityResolutionError("an identity candidate set repeats no observation")
        for person_id in self.person_ids:
            validate_identifier(person_id, IdKind.PERSON)
        for observation_id in self.observation_ids:
            validate_identifier(observation_id, IdKind.IDENTITY_OBSERVATION)
        ensure_utc(self.created_at)


@dataclass(frozen=True, slots=True)
class DuplicateCandidateSet(IdentityCandidateSet):
    """An explicit ambiguous/duplicate set, never a singleton resolution seed."""

    def __post_init__(self) -> None:
        super(DuplicateCandidateSet, self).__post_init__()
        if len(self.person_ids) + len(self.observation_ids) < 2:
            raise IdentityResolutionError("a duplicate set contains at least two candidates")


@dataclass(frozen=True, slots=True)
class IdentityResolution:
    """A reviewed, reversible identity action.

    `review_case_id` and `decision_id` are mandatory. A merge records both the
    retained and prior canonical IDs; a split can therefore restore the prior ID
    without reconstructing it from source content.
    """

    resolution_id: str
    action: ResolutionAction
    review_case_id: str
    decision_id: str
    retained_person_id: str
    prior_person_id: str | None
    observation_ids: tuple[str, ...]
    decided_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.resolution_id, IdKind.IDENTITY_RESOLUTION)
        validate_identifier(self.review_case_id, IdKind.REVIEW_CASE)
        validate_identifier(self.decision_id, IdKind.REVIEW_DECISION)
        validate_identifier(self.retained_person_id, IdKind.PERSON)
        if self.prior_person_id is not None:
            validate_identifier(self.prior_person_id, IdKind.PERSON)
        if self.action in {ResolutionAction.MERGE_PERSON, ResolutionAction.SPLIT_PERSON} and (
            self.prior_person_id is None
        ):
            raise IdentityResolutionError("a merge or split retains both canonical identifiers")
        if self.prior_person_id == self.retained_person_id:
            raise IdentityResolutionError("an identity correction names two distinct people")
        if not self.observation_ids:
            raise IdentityResolutionError("an identity resolution names its exact observations")
        for observation_id in self.observation_ids:
            validate_identifier(observation_id, IdKind.IDENTITY_OBSERVATION)
        ensure_utc(self.decided_at)
