"""Dormant integrity evaluation scores a labeled fixture, not a worker or model."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from my_pa.application.goodnotes_evaluation import (
    DATABASE_INTEGRITY_METRIC,
    NEW_NOTE_INTEGRITY_LOSS_WEIGHTS,
    LabeledNewNoteCase,
    NewNoteIntegrityLossKind,
    ObservedNewNoteOutcome,
    duplicate_active_occurrence_count,
    new_note_integrity_losses,
    score_new_note_integrity_loss,
)
from my_pa.domain.goodnotes.models import (
    GoodNotesIdentityStatus,
    GoodNotesNoteOccurrence,
    issue_stable_id,
)

WHEN = datetime(2026, 8, 16, 23, 0, tzinfo=UTC)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
NOTE = issue_stable_id("gnnt", "synthetic", "note")
PAGE = issue_stable_id("gnlp", "synthetic", "page")


def _occurrence(
    token: str,
    *,
    x_min: float,
    identity_status: GoodNotesIdentityStatus = GoodNotesIdentityStatus.ACTIVE,
    logical_page_id: str = PAGE,
    principal_id: str = A,
) -> GoodNotesNoteOccurrence:
    return GoodNotesNoteOccurrence(
        occurrence_id=issue_stable_id("gnocc", token),
        principal_id=principal_id,
        note_id=NOTE,
        logical_page_id=logical_page_id,
        x_min=x_min,
        y_min=0.2,
        width=0.2,
        height=0.1,
        identity_status=identity_status,
        created_at=WHEN,
        last_seen_at=WHEN,
    )


def _label(**overrides: object) -> LabeledNewNoteCase:
    base = LabeledNewNoteCase(
        case_id="synthetic-case",
        genuine_new=True,
        boundary="0.1000,0.2000,0.2000,0.1000:none",
        transcription="synthetic note",
        primary_class="MEETING",
        high_confidence_association="prj_synthetic",
        unreadable=False,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def _outcome(**overrides: object) -> ObservedNewNoteOutcome:
    base = ObservedNewNoteOutcome(
        case_id="synthetic-case",
        classified_as_new=True,
        boundary="0.1000,0.2000,0.2000,0.1000:none",
        transcription="synthetic note",
        primary_class="MEETING",
        high_confidence_association="prj_synthetic",
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def test_integrity_metric_name_is_stable() -> None:
    assert DATABASE_INTEGRITY_METRIC == "DATABASE_INTEGRITY_METRIC"


def test_database_integrity_metric_is_zero_on_a_clean_fixture() -> None:
    clean = (
        _occurrence("left", x_min=0.1),
        _occurrence("right", x_min=0.5),
        _occurrence(
            "retired-same-box",
            x_min=0.1,
            identity_status=GoodNotesIdentityStatus.RETIRED,
        ),
    )
    assert duplicate_active_occurrence_count(clean) == 0


def test_database_integrity_metric_detects_a_planted_duplicate() -> None:
    planted = (
        _occurrence("first", x_min=0.1),
        _occurrence("duplicate", x_min=0.1),
        _occurrence("other-page", x_min=0.1, logical_page_id=issue_stable_id("gnlp", "other")),
    )
    assert duplicate_active_occurrence_count(planted) == 1
    retired_twin = (
        _occurrence("active", x_min=0.5),
        _occurrence(
            "retired",
            x_min=0.5,
            identity_status=GoodNotesIdentityStatus.RETIRED,
        ),
    )
    assert duplicate_active_occurrence_count(retired_twin) == 0


def test_integrity_loss_weights_are_the_accepted_floor() -> None:
    assert NEW_NOTE_INTEGRITY_LOSS_WEIGHTS == {
        NewNoteIntegrityLossKind.FALSE_NEW_DUPLICATE: 5,
        NewNoteIntegrityLossKind.MISSED_GENUINE_NEW: 4,
        NewNoteIntegrityLossKind.WRONG_BOUNDARY: 2,
        NewNoteIntegrityLossKind.MATERIALLY_WRONG_TRANSCRIPTION: 2,
        NewNoteIntegrityLossKind.WRONG_PRIMARY_CLASS: 1,
        NewNoteIntegrityLossKind.WRONG_HIGH_CONFIDENCE_ASSOCIATION: 2,
        NewNoteIntegrityLossKind.FABRICATED_UNREADABLE_CONTENT: 5,
    }


def test_each_integrity_loss_weight_scores_in_isolation() -> None:
    cases = (
        (
            NewNoteIntegrityLossKind.FALSE_NEW_DUPLICATE,
            5,
            _label(genuine_new=False),
            _outcome(classified_as_new=True),
        ),
        (
            NewNoteIntegrityLossKind.MISSED_GENUINE_NEW,
            4,
            _label(genuine_new=True),
            _outcome(classified_as_new=False),
        ),
        (
            NewNoteIntegrityLossKind.WRONG_BOUNDARY,
            2,
            _label(),
            _outcome(boundary="0.5000,0.2000,0.2000,0.1000:none"),
        ),
        (
            NewNoteIntegrityLossKind.MATERIALLY_WRONG_TRANSCRIPTION,
            2,
            _label(),
            _outcome(transcription="synthetic correction"),
        ),
        (
            NewNoteIntegrityLossKind.WRONG_PRIMARY_CLASS,
            1,
            _label(),
            _outcome(primary_class="PROJECT"),
        ),
        (
            NewNoteIntegrityLossKind.WRONG_HIGH_CONFIDENCE_ASSOCIATION,
            2,
            _label(),
            _outcome(high_confidence_association="prj_other"),
        ),
        (
            NewNoteIntegrityLossKind.FABRICATED_UNREADABLE_CONTENT,
            5,
            _label(unreadable=True, transcription=""),
            _outcome(transcription="synthetic note"),
        ),
    )
    for kind, weight, label, outcome in cases:
        losses = new_note_integrity_losses(label, outcome)
        assert losses == (kind,)
        assert score_new_note_integrity_loss((label,), (outcome,)) == weight


def test_integrity_loss_sums_independent_faults_and_stays_zero_when_aligned() -> None:
    aligned = _label()
    observed = _outcome()
    assert score_new_note_integrity_loss((aligned,), (observed,)) == 0
    stacked = score_new_note_integrity_loss(
        (_label(genuine_new=False, primary_class="GENERAL"),),
        (_outcome(classified_as_new=True, primary_class="MEETING"),),
    )
    assert stacked == 6
    with pytest.raises(ValueError, match="same corpus"):
        score_new_note_integrity_loss((_label(),), (_outcome(case_id="other"),))
    assert "synthetic note" not in repr(_label())
    assert "synthetic note" not in repr(_outcome())
