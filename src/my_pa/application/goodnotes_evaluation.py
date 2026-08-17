"""Dormant GoodNotes evaluation instrumentation.

Two independent scores. A model-quality improvement may never trade away
database integrity. Helpers score a labeled synthetic fixture; they do not
call a model, grade the implementing worker, train, or run an optimizer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from my_pa.domain.goodnotes.models import GoodNotesIdentityStatus, GoodNotesNoteOccurrence

DATABASE_INTEGRITY_METRIC = "DATABASE_INTEGRITY_METRIC"


class NewNoteIntegrityLossKind(StrEnum):
    FALSE_NEW_DUPLICATE = "false-new-duplicate"
    MISSED_GENUINE_NEW = "missed-genuine-new"
    WRONG_BOUNDARY = "wrong-boundary"
    MATERIALLY_WRONG_TRANSCRIPTION = "materially-wrong-transcription"
    WRONG_PRIMARY_CLASS = "wrong-primary-class"
    WRONG_HIGH_CONFIDENCE_ASSOCIATION = "wrong-high-confidence-association"
    FABRICATED_UNREADABLE_CONTENT = "fabricated-unreadable-content"


NEW_NOTE_INTEGRITY_LOSS_WEIGHTS: Mapping[NewNoteIntegrityLossKind, int] = {
    NewNoteIntegrityLossKind.FALSE_NEW_DUPLICATE: 5,
    NewNoteIntegrityLossKind.MISSED_GENUINE_NEW: 4,
    NewNoteIntegrityLossKind.WRONG_BOUNDARY: 2,
    NewNoteIntegrityLossKind.MATERIALLY_WRONG_TRANSCRIPTION: 2,
    NewNoteIntegrityLossKind.WRONG_PRIMARY_CLASS: 1,
    NewNoteIntegrityLossKind.WRONG_HIGH_CONFIDENCE_ASSOCIATION: 2,
    NewNoteIntegrityLossKind.FABRICATED_UNREADABLE_CONTENT: 5,
}


@dataclass(frozen=True, slots=True)
class LabeledNewNoteCase:
    """Operator-labeled synthetic ground truth. Not a model or worker grade."""

    case_id: str
    genuine_new: bool
    boundary: str
    primary_class: str | None
    high_confidence_association: str | None
    unreadable: bool
    transcription: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ObservedNewNoteOutcome:
    """Recorded system outcome for one labeled case. Not a worker grade."""

    case_id: str
    classified_as_new: bool
    boundary: str
    primary_class: str | None
    high_confidence_association: str | None
    transcription: str = field(repr=False)


def duplicate_active_occurrence_count(
    occurrences: Sequence[GoodNotesNoteOccurrence],
) -> int:
    """Extra ACTIVE rows sharing Principal + logical page + geometry_key.

    The hard floor is 0. RETIRED and AMBIGUOUS rows are not this metric.
    """
    grouped: dict[tuple[str, str, str], int] = {}
    for item in occurrences:
        if item.identity_status is not GoodNotesIdentityStatus.ACTIVE:
            continue
        key = (item.principal_id, item.logical_page_id, item.geometry_key)
        grouped[key] = grouped.get(key, 0) + 1
    return sum(count - 1 for count in grouped.values() if count > 1)


def new_note_integrity_losses(
    label: LabeledNewNoteCase,
    outcome: ObservedNewNoteOutcome,
) -> tuple[NewNoteIntegrityLossKind, ...]:
    """Compare one labeled case to its observed outcome. No model is consulted."""
    if label.case_id != outcome.case_id:
        raise ValueError("a labeled case and outcome must share a case identity")
    losses: list[NewNoteIntegrityLossKind] = []
    if not label.genuine_new and outcome.classified_as_new:
        losses.append(NewNoteIntegrityLossKind.FALSE_NEW_DUPLICATE)
    if label.genuine_new and not outcome.classified_as_new:
        losses.append(NewNoteIntegrityLossKind.MISSED_GENUINE_NEW)
    if label.boundary != outcome.boundary:
        losses.append(NewNoteIntegrityLossKind.WRONG_BOUNDARY)
    if label.unreadable:
        if outcome.transcription:
            losses.append(NewNoteIntegrityLossKind.FABRICATED_UNREADABLE_CONTENT)
    elif label.transcription != outcome.transcription:
        losses.append(NewNoteIntegrityLossKind.MATERIALLY_WRONG_TRANSCRIPTION)
    if label.primary_class != outcome.primary_class:
        losses.append(NewNoteIntegrityLossKind.WRONG_PRIMARY_CLASS)
    if label.high_confidence_association != outcome.high_confidence_association:
        losses.append(NewNoteIntegrityLossKind.WRONG_HIGH_CONFIDENCE_ASSOCIATION)
    return tuple(losses)


def score_new_note_integrity_loss(
    labels: Sequence[LabeledNewNoteCase],
    outcomes: Sequence[ObservedNewNoteOutcome],
) -> int:
    """Weighted loss over an operator-labeled synthetic corpus."""
    by_id = {item.case_id: item for item in outcomes}
    if len(by_id) != len(outcomes):
        raise ValueError("observed outcomes repeat a case identity")
    label_ids = {item.case_id for item in labels}
    if label_ids != set(by_id):
        raise ValueError("labeled cases and observed outcomes must cover the same corpus")
    total = 0
    for label in labels:
        for kind in new_note_integrity_losses(label, by_id[label.case_id]):
            total += NEW_NOTE_INTEGRITY_LOSS_WEIGHTS[kind]
    return total
