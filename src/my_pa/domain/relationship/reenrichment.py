"""Durable, exact-version-bound Relationship Intelligence re-enrichment.

Re-enrichment is not identity-correction authority. A governed merge applies
its reversible identity effects in the transaction that records the operation.
This module records downstream work and refuses to apply a binding whose exact
subjects, inputs, producer, or policy have moved since registration.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, Protocol

from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "DEFAULT_MAX_REENRICHMENT_ATTEMPTS",
    "MAX_REENRICHMENT_SUBJECTS",
    "BindingCurrency",
    "BindingVersion",
    "CurrentReenrichmentBindings",
    "ReenrichmentBinding",
    "ReenrichmentLimitation",
    "ReenrichmentState",
    "ReenrichmentSubject",
    "ReenrichmentSubjectKind",
    "ReenrichmentTrigger",
    "ReenrichmentWork",
    "StaleBindingReason",
    "assess_currency",
]

MAX_REENRICHMENT_SUBJECTS: Final = 100
DEFAULT_MAX_REENRICHMENT_ATTEMPTS: Final = 3
_MAX_VERSION_CHARACTERS: Final = 200
_OPAQUE_CAUSE: Final = re.compile(r"\A[A-Za-z][A-Za-z0-9]{1,15}_[A-Za-z0-9]{8,64}\Z")
_SAFE_VERSION_KEY: Final = re.compile(r"\A[a-z][a-z0-9_.-]{0,63}\Z")


class ReenrichmentTrigger(StrEnum):
    """The exact nine triggers in RI v0.2 section 27.4."""

    CORRECTED_IDENTITY = "corrected_identity"
    NEW_ALIAS = "new_alias"
    PROJECT_MAPPING_CHANGE = "project_mapping_change"
    ROLE_OR_ORGANIZATION_CHANGE = "role_or_organization_change"
    SOURCE_VERSION_CHANGE = "source_version_change"
    MODEL_OR_RULE_VERSION_CHANGE = "model_or_rule_version_change"
    ACCEPTED_QUICK_CAPTURE_CORRECTION = "accepted_quick_capture_correction"
    CONTRADICTION_RESOLUTION = "contradiction_resolution"
    POLICY_CHANGE = "policy_change"


class ReenrichmentSubjectKind(StrEnum):
    """Content-free record families a work item may bind."""

    PRINCIPAL = "principal"
    ENTITY = "entity"
    ALIAS = "alias"
    ASSIGNMENT = "assignment"
    RELATIONSHIP = "relationship"
    SOURCE_OBJECT = "source_object"
    SOURCE_VERSION = "source_version"
    CAPTURE = "capture"
    CAPTURE_VERSION = "capture_version"
    PROPOSAL = "proposal"
    REVIEW_DECISION = "review_decision"
    IDENTITY_OPERATION = "identity_operation"


_SUBJECT_ID_KINDS: Final[Mapping[ReenrichmentSubjectKind, IdKind]] = {
    ReenrichmentSubjectKind.PRINCIPAL: IdKind.PRINCIPAL,
    ReenrichmentSubjectKind.ENTITY: IdKind.ENTITY,
    ReenrichmentSubjectKind.ALIAS: IdKind.ENTITY_ALIAS,
    ReenrichmentSubjectKind.ASSIGNMENT: IdKind.ASSIGNMENT,
    ReenrichmentSubjectKind.RELATIONSHIP: IdKind.ENTITY_RELATIONSHIP,
    ReenrichmentSubjectKind.SOURCE_OBJECT: IdKind.SOURCE_OBJECT,
    ReenrichmentSubjectKind.SOURCE_VERSION: IdKind.VERSION,
    ReenrichmentSubjectKind.CAPTURE: IdKind.CAPTURE,
    ReenrichmentSubjectKind.CAPTURE_VERSION: IdKind.CAPTURE_VERSION,
    ReenrichmentSubjectKind.REVIEW_DECISION: IdKind.REVIEW_DECISION,
    ReenrichmentSubjectKind.IDENTITY_OPERATION: IdKind.ENTITY_IDENTITY_OPERATION,
}


def _validate_version(value: str) -> None:
    if not value or len(value) > _MAX_VERSION_CHARACTERS:
        raise ValueError("a re-enrichment version is present and bounded")
    if any(character.isspace() for character in value):
        raise ValueError("a re-enrichment version contains no whitespace")


def _validate_subject_identifier(kind: ReenrichmentSubjectKind, value: str) -> None:
    if kind is ReenrichmentSubjectKind.PROPOSAL:
        try:
            validate_identifier(value, IdKind.PROPOSAL)
        except InvalidIdentifierError:
            validate_identifier(value, IdKind.ENTITY_PROPOSAL)
        return
    validate_identifier(value, _SUBJECT_ID_KINDS[kind])


@dataclass(frozen=True, slots=True, order=True)
class ReenrichmentSubject:
    """One exact record and the version the trigger observed."""

    kind: ReenrichmentSubjectKind
    subject_id: str
    version: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ReenrichmentSubjectKind):
            raise ValueError("a re-enrichment subject has a closed kind")
        _validate_subject_identifier(self.kind, self.subject_id)
        _validate_version(self.version)


@dataclass(frozen=True, slots=True, order=True)
class BindingVersion:
    """One named input or producer version, never source content."""

    key: str
    version: str

    def __post_init__(self) -> None:
        if not _SAFE_VERSION_KEY.fullmatch(self.key):
            raise ValueError("a re-enrichment version key is a bounded safe token")
        _validate_version(self.version)


def _unique_subjects(
    values: Sequence[ReenrichmentSubject],
) -> tuple[ReenrichmentSubject, ...]:
    ordered = tuple(
        sorted(values, key=lambda item: (item.kind.value, item.subject_id, item.version))
    )
    if len(set(ordered)) != len(ordered):
        raise ValueError("a re-enrichment binding names each item once")
    return ordered


def _unique_versions(values: Sequence[BindingVersion]) -> tuple[BindingVersion, ...]:
    ordered = tuple(sorted(values, key=lambda item: (item.key, item.version)))
    if len(set(ordered)) != len(ordered):
        raise ValueError("a re-enrichment binding names each item once")
    return ordered


@dataclass(frozen=True, slots=True)
class ReenrichmentBinding:
    """Immutable dedupe and currency identity for one bounded work item."""

    principal_id: str
    trigger: ReenrichmentTrigger
    cause_record_id: str
    subjects: tuple[ReenrichmentSubject, ...]
    input_versions: tuple[BindingVersion, ...]
    producer_versions: tuple[BindingVersion, ...]
    policy_version: str

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.trigger, ReenrichmentTrigger):
            raise ValueError("a re-enrichment binding has a closed trigger")
        if not _OPAQUE_CAUSE.fullmatch(self.cause_record_id):
            raise ValueError("a re-enrichment cause is an opaque record identifier")
        if not self.subjects or len(self.subjects) > MAX_REENRICHMENT_SUBJECTS:
            raise ValueError("a re-enrichment binding has a bounded non-empty subject set")
        object.__setattr__(self, "subjects", _unique_subjects(self.subjects))
        object.__setattr__(self, "input_versions", _unique_versions(self.input_versions))
        object.__setattr__(self, "producer_versions", _unique_versions(self.producer_versions))
        _validate_version(self.policy_version)
        for subject in self.subjects:
            if (
                subject.kind is ReenrichmentSubjectKind.PRINCIPAL
                and subject.subject_id != self.principal_id
            ):
                raise ValueError("a Principal subject is the binding's own Principal")

    @property
    def binding_sha256(self) -> str:
        """Canonical dedupe identity; changed versions create new work."""
        payload = {
            "cause_record_id": self.cause_record_id,
            "input_versions": [
                {"key": item.key, "version": item.version} for item in self.input_versions
            ],
            "policy_version": self.policy_version,
            "principal_id": self.principal_id,
            "producer_versions": [
                {"key": item.key, "version": item.version} for item in self.producer_versions
            ],
            "subjects": [
                {"kind": item.kind.value, "subject_id": item.subject_id, "version": item.version}
                for item in self.subjects
            ],
            "trigger": self.trigger.value,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class ReenrichmentState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    STALE = "stale"
    FAILED = "failed"


class StaleBindingReason(StrEnum):
    SUBJECT_VERSION_CHANGED = "subject_version_changed"
    INPUT_VERSION_CHANGED = "input_version_changed"
    PRODUCER_VERSION_CHANGED = "producer_version_changed"
    POLICY_VERSION_CHANGED = "policy_version_changed"


class ReenrichmentLimitation(StrEnum):
    """Content-free limitations safe for an operational status surface."""

    NO_AUTONOMOUS_IDENTITY_MUTATION = "no_autonomous_identity_mutation"
    STABLE_EXTRACTION_REUSED = "stable_extraction_reused"
    BOUNDED_SUBJECT_SET = "bounded_subject_set"


@dataclass(frozen=True, slots=True)
class ReenrichmentWork:
    work_id: str
    binding: ReenrichmentBinding
    state: ReenrichmentState
    attempt_count: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    completed_at: datetime | None = None
    stale_reasons: tuple[StaleBindingReason, ...] = ()
    last_error_code: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"erwk_[A-Za-z0-9]{8,64}", self.work_id):
            raise ValueError("a re-enrichment work identifier is opaque")
        if not isinstance(self.state, ReenrichmentState):
            raise ValueError("re-enrichment work has a closed state")
        if not 1 <= self.max_attempts <= 10 or not 0 <= self.attempt_count <= self.max_attempts:
            raise ValueError("re-enrichment attempts stay within a bounded budget")
        for moment in (self.created_at, self.updated_at, self.lease_expires_at, self.completed_at):
            if moment is not None:
                ensure_utc(moment)
        leased = self.lease_owner is not None and self.lease_expires_at is not None
        if leased is not (self.state is ReenrichmentState.RUNNING):
            raise ValueError("only running re-enrichment work holds a complete lease")
        if (self.state is ReenrichmentState.STALE) is not bool(self.stale_reasons):
            raise ValueError("only stale work names why its binding moved")
        terminal = self.state in {
            ReenrichmentState.SUCCEEDED,
            ReenrichmentState.STALE,
            ReenrichmentState.FAILED,
        }
        if terminal is not (self.completed_at is not None):
            raise ValueError("only terminal re-enrichment work records completion")

    @property
    def limitations(self) -> tuple[ReenrichmentLimitation, ...]:
        return tuple(ReenrichmentLimitation)


class CurrentReenrichmentBindings(Protocol):
    """Read-only current-version view used immediately before application."""

    def subject_version(
        self, principal_id: str, kind: ReenrichmentSubjectKind, subject_id: str
    ) -> str | None: ...

    def input_version(self, principal_id: str, key: str) -> str | None: ...

    def producer_version(self, principal_id: str, key: str) -> str | None: ...

    def policy_version(self, principal_id: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class BindingCurrency:
    reasons: tuple[StaleBindingReason, ...] = ()

    @property
    def is_current(self) -> bool:
        return not self.reasons


def assess_currency(
    binding: ReenrichmentBinding, current: CurrentReenrichmentBindings
) -> BindingCurrency:
    """Re-read every exact binding; absence is drift and therefore stale."""
    reasons: set[StaleBindingReason] = set()
    if any(
        current.subject_version(binding.principal_id, item.kind, item.subject_id) != item.version
        for item in binding.subjects
    ):
        reasons.add(StaleBindingReason.SUBJECT_VERSION_CHANGED)
    if any(
        current.input_version(binding.principal_id, item.key) != item.version
        for item in binding.input_versions
    ):
        reasons.add(StaleBindingReason.INPUT_VERSION_CHANGED)
    if any(
        current.producer_version(binding.principal_id, item.key) != item.version
        for item in binding.producer_versions
    ):
        reasons.add(StaleBindingReason.PRODUCER_VERSION_CHANGED)
    if current.policy_version(binding.principal_id) != binding.policy_version:
        reasons.add(StaleBindingReason.POLICY_VERSION_CHANGED)
    return BindingCurrency(tuple(sorted(reasons, key=lambda reason: reason.value)))
