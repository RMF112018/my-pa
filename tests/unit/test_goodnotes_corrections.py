"""Operator corrections append a semantic revision and keep prior evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from my_pa.application.goodnotes_corrections import (
    OPERATOR_CORRECTION_ANALYZER,
    GoodNotesCorrectionService,
)
from my_pa.domain.goodnotes.models import (
    GoodNotesIdentityStatus,
    GoodNotesNoteClass,
    GoodNotesNoteLink,
    GoodNotesNoteLinkKind,
    GoodNotesNoteOccurrence,
    GoodNotesNoteRevision,
    issue_stable_id,
)

WHEN = datetime(2026, 8, 16, 23, 0, tzinfo=UTC)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
B = "prn_bbbbbbbbbbbbbbbbbbbbbbbb"
NOTE = issue_stable_id("gnnt", "synthetic", "note")
OCCURRENCE = issue_stable_id("gnocc", "synthetic", "occurrence")
PAGE = issue_stable_id("gnlp", "synthetic", "page")
ORIGINAL = issue_stable_id("gnrev", "synthetic", "original")


@dataclass
class _FakeCorrectionRepository:
    principal_id: str
    stored_occurrence: GoodNotesNoteOccurrence | None
    revisions: list[GoodNotesNoteRevision] = field(default_factory=list)
    links: list[GoodNotesNoteLink] = field(default_factory=list)

    def occurrence(self, principal_id: str, occurrence_id: str) -> GoodNotesNoteOccurrence | None:
        if principal_id != self.principal_id:
            return None
        if self.stored_occurrence is None:
            return None
        if self.stored_occurrence.occurrence_id != occurrence_id:
            return None
        return self.stored_occurrence

    def latest_revision_for_occurrence(
        self, principal_id: str, occurrence_id: str
    ) -> GoodNotesNoteRevision | None:
        matches = [
            item
            for item in self.revisions
            if item.principal_id == principal_id and item.occurrence_id == occurrence_id
        ]
        if not matches:
            return None
        return max(matches, key=lambda item: (item.created_at, item.revision_id))

    def revision(self, principal_id: str, revision_id: str) -> GoodNotesNoteRevision | None:
        for item in self.revisions:
            if item.principal_id == principal_id and item.revision_id == revision_id:
                return item
        return None

    def store_revision(self, revision: GoodNotesNoteRevision) -> GoodNotesNoteRevision:
        self.revisions.append(revision)
        return revision

    def store_note_link(self, link: GoodNotesNoteLink) -> GoodNotesNoteLink:
        self.links.append(link)
        return link


def _occurrence() -> GoodNotesNoteOccurrence:
    return GoodNotesNoteOccurrence(
        occurrence_id=OCCURRENCE,
        principal_id=A,
        note_id=NOTE,
        logical_page_id=PAGE,
        x_min=0.1,
        y_min=0.2,
        width=0.2,
        height=0.1,
        identity_status=GoodNotesIdentityStatus.ACTIVE,
        created_at=WHEN,
        last_seen_at=WHEN,
        crop_sha256="a" * 64,
    )


def _original() -> GoodNotesNoteRevision:
    return GoodNotesNoteRevision(
        revision_id=ORIGINAL,
        principal_id=A,
        note_id=NOTE,
        schema_version="note-unit.v1",
        analyzer_name="synthetic",
        analyzer_version="1",
        transcription="synthetic note",
        created_at=WHEN,
        occurrence_id=OCCURRENCE,
        primary_class=GoodNotesNoteClass.MEETING,
    )


def test_correction_appends_a_revision_and_keeps_the_prior() -> None:
    original = _original()
    repo = _FakeCorrectionRepository(
        principal_id=A,
        stored_occurrence=_occurrence(),
        revisions=[original],
    )
    result = GoodNotesCorrectionService().apply(
        A,
        OCCURRENCE,
        transcription="synthetic correction",
        repository=repo,
        clock=lambda: WHEN,
    )
    assert result.replayed is False
    assert result.prior_revision.revision_id == original.revision_id
    assert result.prior_revision.transcription == "synthetic note"
    assert result.revision.supersedes_revision_id == original.revision_id
    assert result.revision.transcription == "synthetic correction"
    assert result.revision.analyzer_name == OPERATOR_CORRECTION_ANALYZER
    assert "synthetic correction" not in repr(result.revision)
    assert original in repo.revisions
    assert repo.revisions[0].transcription == "synthetic note"
    assert len(repo.revisions) == 2
    geometry = repo.stored_occurrence
    assert geometry is not None
    assert geometry.x_min == 0.1
    assert geometry.crop_sha256 == "a" * 64


def test_other_principal_fails_closed_without_writing() -> None:
    repo = _FakeCorrectionRepository(
        principal_id=A,
        stored_occurrence=_occurrence(),
        revisions=[_original()],
    )
    with pytest.raises(ValueError, match="no stored GoodNotes note occurrence"):
        GoodNotesCorrectionService().apply(
            B,
            OCCURRENCE,
            transcription="synthetic correction",
            repository=repo,
            clock=lambda: WHEN,
        )
    assert len(repo.revisions) == 1
    assert repo.revisions[0].revision_id == ORIGINAL


def test_missing_occurrence_and_transcription_fail_closed() -> None:
    repo = _FakeCorrectionRepository(principal_id=A, stored_occurrence=None, revisions=[])
    with pytest.raises(ValueError, match="no stored GoodNotes note occurrence"):
        GoodNotesCorrectionService().apply(
            A,
            OCCURRENCE,
            transcription="synthetic correction",
            repository=repo,
            clock=lambda: WHEN,
        )
    present = _FakeCorrectionRepository(
        principal_id=A,
        stored_occurrence=_occurrence(),
        revisions=[_original()],
    )
    with pytest.raises(ValueError, match="missing required transcription"):
        GoodNotesCorrectionService().apply(
            A,
            OCCURRENCE,
            transcription="",
            repository=present,
            clock=lambda: WHEN,
        )
    assert len(present.revisions) == 1


def test_optional_link_is_appended_without_replacing_the_revision_chain() -> None:
    original = _original()
    repo = _FakeCorrectionRepository(
        principal_id=A,
        stored_occurrence=_occurrence(),
        revisions=[original],
    )
    target = issue_stable_id("gnnt", "synthetic", "target")
    result = GoodNotesCorrectionService().apply(
        A,
        OCCURRENCE,
        transcription="synthetic correction",
        repository=repo,
        link_kind=GoodNotesNoteLinkKind.NOTE_TO_NOTE,
        target_note_id=target,
        clock=lambda: WHEN,
    )
    assert result.link is not None
    assert result.link.link_kind is GoodNotesNoteLinkKind.NOTE_TO_NOTE
    assert result.link.target_note_id == target
    assert result.revision.supersedes_revision_id == original.revision_id
    assert original in repo.revisions


def test_identical_correction_replays_without_a_second_row() -> None:
    original = _original()
    repo = _FakeCorrectionRepository(
        principal_id=A,
        stored_occurrence=_occurrence(),
        revisions=[original],
    )
    service = GoodNotesCorrectionService()
    first = service.apply(
        A,
        OCCURRENCE,
        transcription="synthetic correction",
        repository=repo,
        clock=lambda: datetime(2026, 8, 16, 23, 30, tzinfo=UTC),
    )
    second = service.apply(
        A,
        OCCURRENCE,
        transcription="synthetic correction",
        repository=repo,
        clock=lambda: datetime(2026, 8, 16, 23, 45, tzinfo=UTC),
    )
    assert first.replayed is False
    assert second.replayed is True
    assert second.revision.revision_id == first.revision.revision_id
    assert [item.revision_id for item in repo.revisions].count(original.revision_id) == 1
    assert [item.revision_id for item in repo.revisions].count(first.revision.revision_id) == 1
