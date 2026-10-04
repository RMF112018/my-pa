"""The closed predicate registry contract (KLP-WP-01).

A Knowledge Assertion is never an entity-attribute-value row. Every assertion
names a registered `predicate_code` whose head version fixes, once and for all,
its value type, cardinality, temporal semantics, qualifier rule, allowed
subjects, canonical owner, normalization and fingerprint semantics. The value
itself is one typed branch (text or datetime), never a caller-chosen attribute
name or a free-form JSON blob. That is the anti-EAV contract, and this module
states it in Python so the WP-02 CHECKs, the WP-02 structure trigger and the
services all mirror one rule:

* **Structural immutability within a code.** A later version of a code may
  change only the non-structural policy fields; any structural change needs a
  new `predicate_code` (`STRUCTURAL_FIELDS`, `require_structural_successor`).
* **A retired head closes the code permanently.**
* **Row-shape rules** identical to the predicate-table CHECKs (plan section
  11.3): single_current is unqualified state and conflicts by review; the
  normalization rule follows the value type; a date_kind qualifier is only for
  datetime values; a consequential or domain-owned predicate never direct-admits.

Pure data and validation: the registry rows themselves are seeded only by the
WP-02 revision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from my_pa.domain.common.classification import Classification
from my_pa.domain.knowledge_assertion.vocabulary import (
    KNOWLEDGE_CLASSIFICATION_FLOORS,
    KnowledgeAutonomousAdmissionPolicy,
    KnowledgeCanonicalOwner,
    KnowledgeCardinality,
    KnowledgeConflictRule,
    KnowledgeConsequentialClass,
    KnowledgeEvidenceAuthority,
    KnowledgeNormalizationRule,
    KnowledgePredicateAdmissionState,
    KnowledgeQualifierRule,
    KnowledgeReviewRequirement,
    KnowledgeSubjectKind,
    KnowledgeTemporalSemantics,
    KnowledgeValueType,
)
from my_pa.domain.relationship.entity import EntityType

__all__ = [
    "PREDICATE_CODE_PATTERN",
    "STRUCTURAL_FIELDS",
    "InvalidPredicateError",
    "KnowledgePredicate",
    "require_structural_successor",
]

#: `knowledge_predicate_code_is_bounded`: `<namespace>.<name>`, lower snake case.
PREDICATE_CODE_PATTERN: Final = re.compile(r"\A[a-z][a-z_]{0,30}[.][a-z][a-z_]{0,30}\Z")

#: The fields the WP-02 structure trigger compares against the prior head. Any
#: difference is refused: structure is immutable within a predicate_code, which
#: is also why the fingerprint can exclude predicate_version (plan section 6.5).
STRUCTURAL_FIELDS: Final[tuple[str, ...]] = (
    "value_type",
    "cardinality",
    "temporal_semantics",
    "qualifier_rule",
    "allowed_subject_kinds",
    "allowed_entity_types",
    "canonical_owner",
    "normalization_rule",
    "fingerprint_version",
)

_SINGLE_CURRENT_TEMPORAL: Final = frozenset(
    {KnowledgeTemporalSemantics.ATEMPORAL, KnowledgeTemporalSemantics.OBSERVED_STATE}
)
_RULE_FOR_TYPE: Final = {
    KnowledgeValueType.TEXT: KnowledgeNormalizationRule.TEXT_NFC_TRIM_COLLAPSE_WHITESPACE,
    KnowledgeValueType.DATETIME: KnowledgeNormalizationRule.DATETIME_UTC_MICROSECOND,
}


class InvalidPredicateError(ValueError):
    """Raised when a predicate row or version successor violates the registry contract."""


@dataclass(frozen=True, slots=True)
class KnowledgePredicate:
    """One registered predicate version (the 18 non-timestamp columns)."""

    predicate_code: str
    predicate_version: int
    admission_state: KnowledgePredicateAdmissionState
    value_type: KnowledgeValueType
    cardinality: KnowledgeCardinality
    temporal_semantics: KnowledgeTemporalSemantics
    qualifier_rule: KnowledgeQualifierRule
    allowed_subject_kinds: frozenset[KnowledgeSubjectKind]
    allowed_entity_types: frozenset[EntityType]
    canonical_owner: KnowledgeCanonicalOwner
    autonomous_admission_policy: KnowledgeAutonomousAdmissionPolicy
    review_requirement: KnowledgeReviewRequirement
    consequential_class: KnowledgeConsequentialClass
    normalization_rule: KnowledgeNormalizationRule
    classification_floor: Classification
    conflict_rule: KnowledgeConflictRule
    minimum_evidence_authority: KnowledgeEvidenceAuthority
    fingerprint_version: int = 1

    def __post_init__(self) -> None:
        code: object = self.predicate_code
        if not isinstance(code, str) or not PREDICATE_CODE_PATTERN.fullmatch(code):
            raise InvalidPredicateError("predicate_code is not a bounded <namespace>.<name> code")
        version: object = self.predicate_version
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise InvalidPredicateError("predicate_version must be a positive integer")
        self._require_closed_tokens()
        if not 1 <= len(self.allowed_subject_kinds) <= len(KnowledgeSubjectKind):
            raise InvalidPredicateError("allowed_subject_kinds must name 1..5 subject kinds")
        names_entity = KnowledgeSubjectKind.ENTITY in self.allowed_subject_kinds
        if bool(self.allowed_entity_types) != names_entity:
            raise InvalidPredicateError(
                "allowed_entity_types must be non-empty exactly for entity subjects"
            )
        if self.fingerprint_version != 1:
            raise InvalidPredicateError("fingerprint_version is frozen at 1")
        if self.classification_floor not in KNOWLEDGE_CLASSIFICATION_FLOORS:
            raise InvalidPredicateError(
                "classification_floor must be private_local or restricted_local"
            )
        single = self.cardinality is KnowledgeCardinality.SINGLE_CURRENT
        if single and (
            self.temporal_semantics not in _SINGLE_CURRENT_TEMPORAL
            or self.qualifier_rule is not KnowledgeQualifierRule.NONE
        ):
            raise InvalidPredicateError(
                "single_current must be unqualified atemporal/observed state"
            )
        if single != (self.conflict_rule is KnowledgeConflictRule.REVIEW_ON_DIFFERENCE):
            raise InvalidPredicateError(
                "single_current exactly when conflict_rule is review_on_difference"
            )
        if _RULE_FOR_TYPE[self.value_type] is not self.normalization_rule:
            raise InvalidPredicateError("normalization_rule does not follow value_type")
        if (
            self.qualifier_rule is KnowledgeQualifierRule.DATE_KIND
            and self.value_type is not KnowledgeValueType.DATETIME
        ):
            raise InvalidPredicateError("a date_kind qualifier is only for datetime values")
        never = KnowledgeAutonomousAdmissionPolicy.NEVER
        if self.consequential_class is not KnowledgeConsequentialClass.NONE and (
            self.autonomous_admission_policy is not never
        ):
            raise InvalidPredicateError("a consequential predicate never direct-admits")
        if self.canonical_owner is not KnowledgeCanonicalOwner.KNOWLEDGE_ASSERTION and (
            self.autonomous_admission_policy is not never
        ):
            raise InvalidPredicateError("a domain-owned predicate never direct-admits")

    def _require_closed_tokens(self) -> None:
        typed: tuple[tuple[object, type], ...] = (
            (self.admission_state, KnowledgePredicateAdmissionState),
            (self.value_type, KnowledgeValueType),
            (self.cardinality, KnowledgeCardinality),
            (self.temporal_semantics, KnowledgeTemporalSemantics),
            (self.qualifier_rule, KnowledgeQualifierRule),
            (self.canonical_owner, KnowledgeCanonicalOwner),
            (self.autonomous_admission_policy, KnowledgeAutonomousAdmissionPolicy),
            (self.review_requirement, KnowledgeReviewRequirement),
            (self.consequential_class, KnowledgeConsequentialClass),
            (self.normalization_rule, KnowledgeNormalizationRule),
            (self.classification_floor, Classification),
            (self.conflict_rule, KnowledgeConflictRule),
            (self.minimum_evidence_authority, KnowledgeEvidenceAuthority),
        )
        for value, enum_type in typed:
            if not isinstance(value, enum_type):
                raise InvalidPredicateError(f"{enum_type.__name__} must be a closed token")
        subjects: object = self.allowed_subject_kinds
        if not isinstance(subjects, frozenset) or not all(
            isinstance(kind, KnowledgeSubjectKind) for kind in subjects
        ):
            raise InvalidPredicateError(
                "allowed_subject_kinds must be a frozenset of subject kinds"
            )
        entity_types: object = self.allowed_entity_types
        if not isinstance(entity_types, frozenset) or not all(
            isinstance(kind, EntityType) for kind in entity_types
        ):
            raise InvalidPredicateError("allowed_entity_types must be a frozenset of entity types")

    @property
    def is_open_for_intake(self) -> bool:
        """A retired head closes intake for its code permanently."""
        return self.admission_state is KnowledgePredicateAdmissionState.ACTIVE

    def structure(self) -> tuple[object, ...]:
        """The structural tuple the WP-02 trigger compares."""
        return tuple(getattr(self, name) for name in STRUCTURAL_FIELDS)


def require_structural_successor(head: KnowledgePredicate, successor: KnowledgePredicate) -> None:
    """Refuse `successor` unless it is a legal next version of `head`.

    Mirrors trigger `knowledge_predicate_version_preserves_structure`: same code,
    version exactly head + 1, head not retired, and every structural field equal.
    """
    if successor.predicate_code != head.predicate_code:
        raise InvalidPredicateError("a successor version must keep its predicate_code")
    if not head.is_open_for_intake:
        raise InvalidPredicateError("a retired predicate_code is closed; use a new code")
    if successor.predicate_version != head.predicate_version + 1:
        raise InvalidPredicateError("a successor version must be exactly head + 1")
    changed = [
        name for name in STRUCTURAL_FIELDS if getattr(head, name) != getattr(successor, name)
    ]
    if changed:
        raise InvalidPredicateError(
            "predicate structure is immutable within a predicate_code: " + ", ".join(changed)
        )
