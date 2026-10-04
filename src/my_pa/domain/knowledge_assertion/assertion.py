"""Knowledge Assertion value objects (KLP-WP-01).

A candidate assertion is a subject, a registered predicate, exactly one typed
value branch, an optional closed qualifier and an optional effective interval.
`KnowledgeValue` is the single typed branch (AC-005): a text predicate carries
`value_text` and never `value_datetime`, a datetime predicate the reverse, and
any other shape -- both, neither, or a branch that disagrees with the declared
type -- is refused here exactly as CHECK `knowledge_assertion_value_follows_type`
refuses it in the database.

Pure domain: no persistence, no identifiers are issued here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.knowledge_assertion.digest import (
    InvalidKnowledgeValueError,
    assertion_fingerprint,
    fingerprint_object,
    normalize_datetime,
    normalize_text,
    normalized_value_sha256,
)
from my_pa.domain.knowledge_assertion.predicate import KnowledgePredicate
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeDateKind,
    KnowledgeQualifierRule,
    KnowledgeSubjectKind,
    KnowledgeValueType,
)

__all__ = [
    "SUBJECT_ID_KINDS",
    "InvalidKnowledgeAssertionError",
    "KnowledgeAssertionCandidate",
    "KnowledgeValue",
    "validate_qualifier",
    "validate_subject",
]

#: subject_id prefix per subject kind (plan section 4, `knowledge_subject_kind`).
SUBJECT_ID_KINDS: Final[Mapping[KnowledgeSubjectKind, IdKind]] = {
    KnowledgeSubjectKind.PRINCIPAL: IdKind.PRINCIPAL,
    KnowledgeSubjectKind.ENTITY: IdKind.ENTITY,
    KnowledgeSubjectKind.PROJECT: IdKind.PROJECT,
    KnowledgeSubjectKind.MANAGED_DOCUMENT: IdKind.MANAGED_DOCUMENT,
    KnowledgeSubjectKind.EVIDENCE_REF: IdKind.KNOWLEDGE_EVIDENCE_REF,
}


class InvalidKnowledgeAssertionError(ValueError):
    """Raised when a candidate assertion has an illegal shape. Names fields, never values."""


@dataclass(frozen=True, slots=True)
class KnowledgeValue:
    """Exactly one typed value branch, already normalized.

    Construct with `KnowledgeValue.text(...)` / `KnowledgeValue.instant(...)`,
    which normalize; the raw constructor validates the shape and refuses any
    value that is not already in normalized form.
    """

    value_type: KnowledgeValueType
    value_text: str | None = None
    value_datetime: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.value_type, KnowledgeValueType):
            raise InvalidKnowledgeAssertionError("value_type must be a closed token")
        if self.value_type is KnowledgeValueType.TEXT:
            if self.value_text is None or self.value_datetime is not None:
                raise InvalidKnowledgeAssertionError("a text value carries value_text only")
            if normalize_text(self.value_text) != self.value_text:
                raise InvalidKnowledgeAssertionError("value_text is not normalized")
        else:
            if self.value_datetime is None or self.value_text is not None:
                raise InvalidKnowledgeAssertionError("a datetime value carries value_datetime only")
            normalize_datetime(self.value_datetime)

    @classmethod
    def text(cls, raw: object) -> KnowledgeValue:
        return cls(KnowledgeValueType.TEXT, value_text=normalize_text(raw))

    @classmethod
    def instant(cls, raw: object) -> KnowledgeValue:
        # The stored branch stays a real datetime; the normalized string is
        # derived on demand. `__post_init__` refuses a naive one.
        if not isinstance(raw, datetime):
            raise InvalidKnowledgeValueError("a datetime value must be a datetime")
        return cls(KnowledgeValueType.DATETIME, value_datetime=raw)

    @property
    def normalized(self) -> str:
        """The normalized value string the digest and fingerprint use."""
        if self.value_text is not None:
            return self.value_text
        return normalize_datetime(self.value_datetime)

    @property
    def sha256(self) -> str:
        """`normalized_value_sha256`."""
        return normalized_value_sha256(self.normalized)


def validate_subject(subject_kind: KnowledgeSubjectKind, subject_id: str) -> str:
    """Refuse a subject id whose prefix does not match its kind."""
    if not isinstance(subject_kind, KnowledgeSubjectKind):
        raise InvalidKnowledgeAssertionError("subject_kind must be a closed token")
    try:
        return validate_identifier(subject_id, SUBJECT_ID_KINDS[subject_kind])
    except InvalidIdentifierError as exc:
        raise InvalidKnowledgeAssertionError("subject_id does not match subject_kind") from exc


def validate_qualifier(
    rule: KnowledgeQualifierRule, qualifier: Mapping[str, object] | None
) -> dict[str, str] | None:
    """Return the canonical qualifier, or refuse it.

    `none` admits only null; `date_kind` admits exactly `{"date_kind": <closed
    KnowledgeDateKind>}` (CHECK `knowledge_assertion_qualifier_follows_rule`).
    """
    if rule is KnowledgeQualifierRule.NONE:
        if qualifier is not None:
            raise InvalidKnowledgeAssertionError("qualifier must be null for qualifier_rule none")
        return None
    if not isinstance(qualifier, Mapping) or set(qualifier) != {"date_kind"}:
        raise InvalidKnowledgeAssertionError("qualifier must be exactly {date_kind}")
    raw = qualifier["date_kind"]
    if not isinstance(raw, str):
        raise InvalidKnowledgeAssertionError("qualifier.date_kind is not a closed token")
    try:
        date_kind = KnowledgeDateKind(raw)
    except ValueError as exc:
        raise InvalidKnowledgeAssertionError("qualifier.date_kind is not a closed token") from exc
    return {"date_kind": date_kind.value}


@dataclass(frozen=True, slots=True)
class KnowledgeAssertionCandidate:
    """The factual payload shared by an assertion and a proposal of the same fact."""

    subject_kind: KnowledgeSubjectKind
    subject_id: str
    predicate: KnowledgePredicate
    value: KnowledgeValue
    qualifier: Mapping[str, object] | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None

    def __post_init__(self) -> None:
        validate_subject(self.subject_kind, self.subject_id)
        if self.subject_kind not in self.predicate.allowed_subject_kinds:
            raise InvalidKnowledgeAssertionError("subject_kind is not allowed by the predicate")
        if not isinstance(self.value, KnowledgeValue):
            raise InvalidKnowledgeAssertionError("value must be a KnowledgeValue")
        if self.value.value_type is not self.predicate.value_type:
            raise InvalidKnowledgeAssertionError("value_type does not match the predicate")
        object.__setattr__(
            self, "qualifier", validate_qualifier(self.predicate.qualifier_rule, self.qualifier)
        )
        try:
            start = None if self.effective_from is None else normalize_datetime(self.effective_from)
            end = None if self.effective_to is None else normalize_datetime(self.effective_to)
        except InvalidKnowledgeValueError as exc:
            raise InvalidKnowledgeAssertionError(
                "effective bounds must be aware datetimes"
            ) from exc
        if start is not None and end is not None and not end > start:
            raise InvalidKnowledgeAssertionError("effective_to must be after effective_from")

    def fingerprint_object(self) -> dict[str, object]:
        return fingerprint_object(
            subject_kind=self.subject_kind.value,
            subject_id=self.subject_id,
            predicate_code=self.predicate.predicate_code,
            value_type=self.value.value_type,
            normalized_value=self.value.normalized,
            qualifier=self.qualifier,
            temporal_semantics=self.predicate.temporal_semantics,
            effective_from=self.effective_from,
            effective_to=self.effective_to,
        )

    def fingerprint(self) -> str:
        """`assertion_fingerprint` (fingerprint object v1)."""
        return assertion_fingerprint(self.fingerprint_object())
