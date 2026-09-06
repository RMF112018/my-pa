"""The immutable snapshot one applied Constraint mutation leaves behind.

PC-CM-IMP-WP02. `ConstraintRevision` is the domain half of
`knowledge.project_constraint_revisions` and its party rows: everything the
Constraint *was* at one version, including the ordered BIC and Responsible
collections, which are stored as separate rows and reconstructed by
`(revision_id, role) ORDER BY ordinal`.

A revision is written, never revised: the stored table refuses UPDATE and
DELETE with a trigger, and this class carries no mutator. It also repeats none
of the aggregate's completeness rules — a revision records what was, and a
legacy workbook import that the aggregate itself could not be built from must
still be snapshot-able once WP13 hydrates one. What it does enforce is identity
shape, a positive `version`, that it names the history receipt that produced it,
and that every party reference is a real `PartyRef`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintRecordQuality,
    ProjectConstraint,
)
from my_pa.domain.project_controls.party import PartyRef

__all__ = [
    "ConstraintRevision",
    "ConstraintRevisionError",
]


class ConstraintRevisionError(ValueError):
    """A revision snapshot violated a structural invariant. `code` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ConstraintRevision:
    """One immutable snapshot of a Constraint at one `version`.

    The scalar fields carry the same names and types as the aggregate's, so a
    reader comparing a revision against the current row never has to translate
    between two vocabularies.
    """

    revision_id: str
    principal_id: str
    constraint_id: str
    history_id: str
    version: int
    lifecycle_state: ConstraintLifecycleState
    origin: ConstraintOrigin
    record_quality: ConstraintRecordQuality
    recorded_at: datetime
    project_id: str | None = None
    category_id: str | None = None
    constraint_code: str | None = None
    description: str | None = None
    date_identified: date | None = None
    due_date: date | None = None
    reference: str | None = None
    current_update: str | None = None
    completion_date: date | None = None
    closure_commentary: str | None = None
    voided_date: date | None = None
    void_reason: str | None = None
    published_at: datetime | None = None
    bic: tuple[PartyRef, ...] = ()
    responsible: tuple[PartyRef, ...] = ()

    def __post_init__(self) -> None:
        validate_identifier(self.revision_id, IdKind.PROJECT_CONSTRAINT_REVISION)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.constraint_id, IdKind.PROJECT_CONSTRAINT)
        validate_identifier(self.history_id, IdKind.PROJECT_CONSTRAINT_HISTORY)
        if self.project_id is not None:
            validate_identifier(self.project_id, IdKind.PROJECT)
        if self.category_id is not None:
            validate_identifier(self.category_id, IdKind.CONSTRAINT_CATEGORY)
        if self.version < 1:
            raise ConstraintRevisionError(
                "constraint_revision_version_not_positive",
                "a revision version is a positive integer",
            )
        if not isinstance(self.lifecycle_state, ConstraintLifecycleState):
            raise ConstraintRevisionError(
                "constraint_revision_lifecycle_state_unknown",
                "a revision names one known lifecycle state",
            )
        if not isinstance(self.origin, ConstraintOrigin):
            raise ConstraintRevisionError(
                "constraint_revision_origin_unknown", "a revision names one known origin"
            )
        if not isinstance(self.record_quality, ConstraintRecordQuality):
            raise ConstraintRevisionError(
                "constraint_revision_record_quality_unknown",
                "a revision names one known record quality",
            )
        for party in (*self.bic, *self.responsible):
            if not isinstance(party, PartyRef):
                raise ConstraintRevisionError(
                    "constraint_revision_party_malformed",
                    "a revision snapshots party references, not raw values",
                )
        object.__setattr__(self, "recorded_at", ensure_utc(self.recorded_at))
        if self.published_at is not None:
            object.__setattr__(self, "published_at", ensure_utc(self.published_at))

    @classmethod
    def from_constraint(
        cls,
        constraint: ProjectConstraint,
        *,
        revision_id: str,
        history_id: str,
        recorded_at: datetime,
    ) -> ConstraintRevision:
        """Snapshot `constraint` exactly as it stands, under the receipt that applied it.

        Every scalar and both party collections are copied field for field, in
        order: this is the only place the mapping between the aggregate and its
        revision is written down, so a field added to one without the other is a
        single-file change rather than a silent gap.
        """
        return cls(
            revision_id=revision_id,
            principal_id=constraint.principal_id,
            constraint_id=constraint.constraint_id,
            history_id=history_id,
            version=constraint.version,
            lifecycle_state=constraint.lifecycle_state,
            origin=constraint.origin,
            record_quality=constraint.record_quality,
            recorded_at=recorded_at,
            project_id=constraint.project_id,
            category_id=constraint.category_id,
            constraint_code=constraint.constraint_code,
            description=constraint.description,
            date_identified=constraint.date_identified,
            due_date=constraint.due_date,
            reference=constraint.reference,
            current_update=constraint.current_update,
            completion_date=constraint.completion_date,
            closure_commentary=constraint.closure_commentary,
            voided_date=constraint.voided_date,
            void_reason=constraint.void_reason,
            published_at=constraint.published_at,
            bic=tuple(constraint.bic),
            responsible=tuple(constraint.responsible),
        )
