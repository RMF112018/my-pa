"""Domain contracts for NOTE_UNIT identity, occurrences, revisions, and run changes."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta

import pytest

from my_pa.domain.goodnotes.models import (
    GoodNotesIdentityStatus,
    GoodNotesNote,
    GoodNotesNoteChangeState,
    GoodNotesNoteClass,
    GoodNotesNoteLink,
    GoodNotesNoteLinkKind,
    GoodNotesNoteOccurrence,
    GoodNotesNoteRevision,
    GoodNotesRunNoteChange,
    issue_stable_id,
    occurrence_geometry_key,
)

WHEN = datetime(2026, 8, 16, 16, 0, tzinfo=UTC)
LATER = WHEN + timedelta(hours=1)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"


def test_issue_stable_id_accepts_note_unit_prefixes() -> None:
    note = issue_stable_id("gnnt", "synthetic", "note")
    occurrence = issue_stable_id("gnocc", "synthetic", "occurrence")
    revision = issue_stable_id("gnrev", "synthetic", "revision")
    link = issue_stable_id("gnlink", "synthetic", "link")
    change = issue_stable_id("gnchg", "synthetic", "change")
    assert note.startswith("gnnt_") and len(note) == 29
    assert occurrence.startswith("gnocc_") and len(occurrence) == 30
    assert revision.startswith("gnrev_") and len(revision) == 30
    assert link.startswith("gnlink_") and len(link) == 31
    assert change.startswith("gnchg_") and len(change) == 30
    with pytest.raises(ValueError, match="unknown GoodNotes identity prefix"):
        issue_stable_id("gnregx", "synthetic")


def test_note_identity_is_independent_of_page_and_path() -> None:
    note = GoodNotesNote(
        note_id=issue_stable_id("gnnt", "alpha"),
        principal_id=A,
        notebook_id=issue_stable_id("gnnb", "alpha"),
        identity_status=GoodNotesIdentityStatus.ACTIVE,
        created_at=WHEN,
        last_seen_at=LATER,
    )
    names = {item.name for item in fields(GoodNotesNote)}
    assert "page_number" not in names
    assert "path" not in names
    assert note.primary_class is None
    with pytest.raises(ValueError, match="invalid gnnt identifier"):
        GoodNotesNote(
            note_id=issue_stable_id("gnpg", "not-a-note"),
            principal_id=A,
            notebook_id=note.notebook_id,
            identity_status=GoodNotesIdentityStatus.ACTIVE,
            created_at=WHEN,
            last_seen_at=WHEN,
        )


def test_occurrence_identity_is_geometry_not_transcription() -> None:
    first = GoodNotesNoteOccurrence(
        occurrence_id=issue_stable_id("gnocc", "left"),
        principal_id=A,
        note_id=issue_stable_id("gnnt", "same-words"),
        logical_page_id=issue_stable_id("gnlp", "cover"),
        x_min=0.1,
        y_min=0.2,
        width=0.3,
        height=0.15,
        identity_status=GoodNotesIdentityStatus.ACTIVE,
        created_at=WHEN,
        last_seen_at=WHEN,
    )
    second = GoodNotesNoteOccurrence(
        occurrence_id=issue_stable_id("gnocc", "right"),
        principal_id=A,
        note_id=issue_stable_id("gnnt", "same-words"),
        logical_page_id=first.logical_page_id,
        x_min=0.55,
        y_min=0.2,
        width=0.3,
        height=0.15,
        identity_status=GoodNotesIdentityStatus.ACTIVE,
        created_at=WHEN,
        last_seen_at=WHEN,
        crop_sha256="a" * 64,
    )
    assert "transcription" not in {item.name for item in fields(GoodNotesNoteOccurrence)}
    assert first.geometry_key != second.geometry_key
    assert first.geometry_key == occurrence_geometry_key(0.1, 0.2, 0.3, 0.15, None)
    assert second.geometry_key.endswith(":" + "a" * 64)
    with pytest.raises(ValueError, match="normalized to the page"):
        GoodNotesNoteOccurrence(
            occurrence_id=issue_stable_id("gnocc", "overflow"),
            principal_id=A,
            note_id=first.note_id,
            logical_page_id=first.logical_page_id,
            x_min=0.8,
            y_min=0.1,
            width=0.3,
            height=0.1,
            identity_status=GoodNotesIdentityStatus.ACTIVE,
            created_at=WHEN,
            last_seen_at=WHEN,
        )


def test_revision_is_append_only_interpretation() -> None:
    original = GoodNotesNoteRevision(
        revision_id=issue_stable_id("gnrev", "first"),
        principal_id=A,
        note_id=issue_stable_id("gnnt", "alpha"),
        schema_version="note-unit.v1",
        analyzer_name="synthetic",
        analyzer_version="1",
        transcription="follow up Tuesday",
        created_at=WHEN,
        primary_class=GoodNotesNoteClass.MEETING,
    )
    correction = GoodNotesNoteRevision(
        revision_id=issue_stable_id("gnrev", "second"),
        principal_id=A,
        note_id=original.note_id,
        schema_version="note-unit.v1",
        analyzer_name="synthetic",
        analyzer_version="1",
        transcription="follow up Thursday",
        created_at=LATER,
        supersedes_revision_id=original.revision_id,
    )
    assert original.transcription != correction.transcription
    assert correction.supersedes_revision_id == original.revision_id
    with pytest.raises(ValueError, match="cannot supersede itself"):
        GoodNotesNoteRevision(
            revision_id=original.revision_id,
            principal_id=A,
            note_id=original.note_id,
            schema_version="note-unit.v1",
            analyzer_name="synthetic",
            analyzer_version="1",
            transcription="same",
            created_at=WHEN,
            supersedes_revision_id=original.revision_id,
        )
    with pytest.raises(ValueError, match="bounded non-empty string"):
        GoodNotesNoteRevision(
            revision_id=issue_stable_id("gnrev", "nul"),
            principal_id=A,
            note_id=original.note_id,
            schema_version="note-unit.v1",
            analyzer_name="synthetic",
            analyzer_version="1",
            transcription="bad\x00text",
            created_at=WHEN,
        )


def test_note_link_target_must_match_kind() -> None:
    note_id = issue_stable_id("gnnt", "source")
    target = issue_stable_id("gnnt", "target")
    link = GoodNotesNoteLink(
        link_id=issue_stable_id("gnlink", "pair"),
        principal_id=A,
        note_id=note_id,
        link_kind=GoodNotesNoteLinkKind.NOTE_TO_NOTE,
        created_at=WHEN,
        target_note_id=target,
    )
    assert link.target_key == f"note:{target}"
    with pytest.raises(ValueError, match="must match its kind"):
        GoodNotesNoteLink(
            link_id=issue_stable_id("gnlink", "mismatch"),
            principal_id=A,
            note_id=note_id,
            link_kind=GoodNotesNoteLinkKind.NOTE_TO_NOTE,
            created_at=WHEN,
            target_logical_page_id=issue_stable_id("gnlp", "page"),
        )


def test_run_change_states_are_the_canonical_closed_set() -> None:
    assert {member.value for member in GoodNotesNoteChangeState} == {
        "NEW",
        "UNCHANGED",
        "REVISED",
        "REMOVED_OR_NO_LONGER_PRESENT",
        "AMBIGUOUS",
    }
    change = GoodNotesRunNoteChange(
        change_id=issue_stable_id("gnchg", "new"),
        principal_id=A,
        run_id=issue_stable_id("gnrun", "run"),
        note_id=issue_stable_id("gnnt", "note"),
        occurrence_id=issue_stable_id("gnocc", "occ"),
        change_state=GoodNotesNoteChangeState.AMBIGUOUS,
        created_at=WHEN,
    )
    assert change.change_state is GoodNotesNoteChangeState.AMBIGUOUS
