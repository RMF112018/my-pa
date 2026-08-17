"""Deterministic NOTE_UNIT occurrence matching. Transcription is not identity."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

from my_pa.application.goodnotes_occurrences import (
    CurrentOccurrence,
    OccurrenceMatchKind,
    OccurrenceMatchMethod,
    match_occurrences,
)
from my_pa.domain.goodnotes.models import (
    GoodNotesIdentityStatus,
    GoodNotesNoteClass,
    GoodNotesNoteOccurrence,
    issue_stable_id,
    occurrence_geometry_key,
)

WHEN = datetime(2026, 8, 16, 21, 0, tzinfo=UTC)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
NOTE = issue_stable_id("gnnt", "synthetic", "note")
COVER = issue_stable_id("gnlp", "synthetic", "cover")
BODY = issue_stable_id("gnlp", "synthetic", "body")
CROP = "a" * 64
OTHER_CROP = "b" * 64
ANCHOR = "c" * 64


def _current(
    logical_page_id: str,
    token: str,
    *,
    x_min: float,
    y_min: float = 0.2,
    width: float = 0.2,
    height: float = 0.1,
    crop_sha256: str | None = None,
    context_anchor_sha256: str | None = None,
    transcription: str = "follow up Tuesday",
) -> CurrentOccurrence:
    return CurrentOccurrence(
        logical_page_id=logical_page_id,
        page_version_id=issue_stable_id("gnver", token),
        snapshot_id=issue_stable_id("gnsnap", token),
        x_min=x_min,
        y_min=y_min,
        width=width,
        height=height,
        crop_sha256=crop_sha256,
        context_anchor_sha256=context_anchor_sha256,
        transcription=transcription,
        primary_class=GoodNotesNoteClass.MEETING,
        schema_version="note-unit.v1",
        analyzer_name="synthetic",
        analyzer_version="1",
        geometry_key=occurrence_geometry_key(x_min, y_min, width, height, crop_sha256),
    )


def _prior(
    logical_page_id: str,
    token: str,
    *,
    x_min: float,
    y_min: float = 0.2,
    width: float = 0.2,
    height: float = 0.1,
    crop_sha256: str | None = None,
    context_anchor_sha256: str | None = None,
) -> GoodNotesNoteOccurrence:
    return GoodNotesNoteOccurrence(
        occurrence_id=issue_stable_id("gnocc", token),
        principal_id=A,
        note_id=NOTE,
        logical_page_id=logical_page_id,
        x_min=x_min,
        y_min=y_min,
        width=width,
        height=height,
        identity_status=GoodNotesIdentityStatus.ACTIVE,
        created_at=WHEN,
        last_seen_at=WHEN,
        crop_sha256=crop_sha256,
        context_anchor_sha256=context_anchor_sha256,
    )


def test_regenerated_same_geometry_reuses_occurrence() -> None:
    prior = _prior(COVER, "cover", x_min=0.1, crop_sha256=CROP)
    matches = match_occurrences(
        current=(_current(COVER, "cover-v2", x_min=0.1, crop_sha256=CROP),),
        prior=(prior,),
    )
    assert len(matches) == 1
    assert matches[0].kind is OccurrenceMatchKind.PAIRED
    assert matches[0].method is OccurrenceMatchMethod.EXACT_GEOMETRY_KEY
    assert matches[0].prior is not None
    assert matches[0].prior.occurrence_id == prior.occurrence_id
    assert sum(1 for item in matches if item.kind is OccurrenceMatchKind.NEW) == 0


def test_append_one_new_keeps_the_existing_occurrence() -> None:
    prior = _prior(COVER, "existing", x_min=0.1)
    matches = match_occurrences(
        current=(
            _current(COVER, "existing", x_min=0.1),
            _current(COVER, "appended", x_min=0.6),
        ),
        prior=(prior,),
    )
    by_kind = {item.kind: item for item in matches}
    assert by_kind[OccurrenceMatchKind.PAIRED].prior is not None
    assert by_kind[OccurrenceMatchKind.PAIRED].prior.occurrence_id == prior.occurrence_id
    assert by_kind[OccurrenceMatchKind.NEW].current is not None
    assert by_kind[OccurrenceMatchKind.NEW].current.x_min == 0.6
    assert sum(item.kind is OccurrenceMatchKind.NEW for item in matches) == 1


def test_reorder_same_geometry_keys_reuses_both() -> None:
    left = _prior(COVER, "left", x_min=0.1)
    right = _prior(COVER, "right", x_min=0.6)
    matches = match_occurrences(
        current=(_current(COVER, "right-now", x_min=0.6), _current(COVER, "left-now", x_min=0.1)),
        prior=(left, right),
    )
    paired = [item for item in matches if item.kind is OccurrenceMatchKind.PAIRED]
    assert len(paired) == 2
    assert {item.prior.occurrence_id for item in paired if item.prior is not None} == {
        left.occurrence_id,
        right.occurrence_id,
    }
    assert all(item.kind is not OccurrenceMatchKind.NEW for item in matches)


def test_shared_crop_is_ambiguous_and_does_not_reuse_identity() -> None:
    prior_one = _prior(COVER, "one", x_min=0.10, crop_sha256=CROP)
    prior_two = _prior(COVER, "two", x_min=0.50, crop_sha256=CROP)
    matches = match_occurrences(
        current=(
            _current(COVER, "new-one", x_min=0.12, crop_sha256=CROP),
            _current(COVER, "new-two", x_min=0.52, crop_sha256=CROP),
        ),
        prior=(prior_one, prior_two),
    )
    assert all(item.kind is OccurrenceMatchKind.AMBIGUOUS for item in matches)
    assert all(item.method is OccurrenceMatchMethod.UNRESOLVED for item in matches)
    prior_ids = {item.prior.occurrence_id for item in matches if item.prior is not None}
    assert prior_ids == {prior_one.occurrence_id, prior_two.occurrence_id}
    assert all(item.kind is not OccurrenceMatchKind.NEW for item in matches)


def test_transcription_only_never_matches() -> None:
    prior = _prior(COVER, "left", x_min=0.1)
    matches = match_occurrences(
        current=(_current(COVER, "right", x_min=0.6, transcription="follow up Tuesday"),),
        prior=(prior,),
    )
    assert all(item.kind is OccurrenceMatchKind.AMBIGUOUS for item in matches)
    assert all(item.kind is not OccurrenceMatchKind.PAIRED for item in matches)


def test_page_number_never_matches_across_logical_pages() -> None:
    prior = _prior(COVER, "cover", x_min=0.1, crop_sha256=CROP)
    matches = match_occurrences(
        current=(_current(BODY, "body", x_min=0.1, crop_sha256=CROP),),
        prior=(prior,),
    )
    kinds = {item.kind for item in matches}
    assert OccurrenceMatchKind.PAIRED not in kinds
    assert OccurrenceMatchKind.NEW in kinds
    assert OccurrenceMatchKind.REMOVED in kinds
    new = next(item for item in matches if item.kind is OccurrenceMatchKind.NEW)
    removed = next(item for item in matches if item.kind is OccurrenceMatchKind.REMOVED)
    assert new.current is not None and new.current.logical_page_id == BODY
    assert removed.prior is not None and removed.prior.occurrence_id == prior.occurrence_id


def test_matcher_source_does_not_read_transcription_or_page_number() -> None:
    source = inspect.getsource(match_occurrences)
    assert "transcription" not in source
    assert "page_number" not in source


def test_unique_crop_matches_when_geometry_moved() -> None:
    prior = _prior(COVER, "moved", x_min=0.1, crop_sha256=CROP)
    matches = match_occurrences(
        current=(_current(COVER, "moved", x_min=0.4, crop_sha256=CROP),),
        prior=(prior,),
    )
    assert len(matches) == 1
    assert matches[0].kind is OccurrenceMatchKind.PAIRED
    assert matches[0].method is OccurrenceMatchMethod.UNIQUE_CROP
    assert matches[0].prior is not None
    assert matches[0].prior.occurrence_id == prior.occurrence_id


def test_unique_context_overlap_matches_when_box_shifts() -> None:
    prior = _prior(
        COVER,
        "anchored",
        x_min=0.10,
        y_min=0.20,
        width=0.20,
        height=0.10,
        context_anchor_sha256=ANCHOR,
    )
    matches = match_occurrences(
        current=(
            _current(
                COVER,
                "anchored",
                x_min=0.12,
                y_min=0.21,
                width=0.20,
                height=0.10,
                context_anchor_sha256=ANCHOR,
            ),
        ),
        prior=(prior,),
    )
    assert len(matches) == 1
    assert matches[0].kind is OccurrenceMatchKind.PAIRED
    assert matches[0].method is OccurrenceMatchMethod.CONTEXT_OVERLAP


def test_different_crop_does_not_match_on_geometry_alone_when_keys_differ() -> None:
    prior = _prior(COVER, "old-crop", x_min=0.1, crop_sha256=CROP)
    matches = match_occurrences(
        current=(_current(COVER, "new-crop", x_min=0.1, crop_sha256=OTHER_CROP),),
        prior=(prior,),
    )
    assert all(item.kind is OccurrenceMatchKind.AMBIGUOUS for item in matches)
