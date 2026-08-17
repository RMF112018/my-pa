"""NEW-only summary membership, entity resolution, and suppressed empty delivery."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import pytest

from my_pa.application.goodnotes_delivery import (
    GoodNotesNewOnlyDelivery,
    NewOnlySummaryNote,
    build_new_only_summary,
    new_note_is_uncertain,
    resolve_entity_candidate,
)
from my_pa.domain.goodnotes.models import (
    GoodNotesDeliveryReceipt,
    GoodNotesEntityAssociation,
    GoodNotesEntityDirectoryRecord,
    GoodNotesEntityKind,
    GoodNotesEntityResolution,
    GoodNotesIdentityStatus,
    GoodNotesIngestionRun,
    GoodNotesIngestionStatus,
    GoodNotesIngestionTrigger,
    GoodNotesNoteChangeState,
    GoodNotesNoteClass,
    GoodNotesNoteOccurrence,
    GoodNotesRunNoteChange,
    issue_stable_id,
)

WHEN = datetime(2026, 8, 16, 22, 0, tzinfo=UTC)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
RUN = issue_stable_id("gnrun", "summary")
DESTINATION = "operator-local"


def _note(
    token: str,
    *,
    note_class: GoodNotesNoteClass | None,
    transcription: str,
    uncertain: bool = False,
) -> NewOnlySummaryNote:
    return NewOnlySummaryNote(
        note_id=issue_stable_id("gnnt", token),
        occurrence_id=issue_stable_id("gnocc", token),
        primary_class=note_class,
        uncertain=uncertain,
        transcription=transcription,
    )


def test_issue_stable_id_accepts_delivery_prefixes() -> None:
    receipt = issue_stable_id("gndlv", "synthetic", "receipt")
    association = issue_stable_id("gnent", "synthetic", "association")
    assert receipt.startswith("gndlv_") and len(receipt) == 30
    assert association.startswith("gnent_") and len(association) == 30
    with pytest.raises(ValueError, match="unknown GoodNotes identity prefix"):
        issue_stable_id("gnrecx", "synthetic")


def test_mixed_states_include_only_new_notes() -> None:
    body = build_new_only_summary(
        (
            _note(
                "new-meeting", note_class=GoodNotesNoteClass.MEETING, transcription="synthetic note"
            ),
            _note(
                "new-project",
                note_class=GoodNotesNoteClass.PROJECT,
                transcription="synthetic heading",
            ),
        )
    )
    assert body is not None
    assert "NEW MEETING NOTES" in body
    assert "synthetic note" in body
    assert "NEW PROJECT NOTES" in body
    assert "synthetic heading" in body
    assert "REVISED" not in body
    assert "UNCHANGED" not in body
    assert "AMBIGUOUS" not in body
    assert "REMOVED" not in body


def test_all_new_notes_appear_in_the_correct_class_section() -> None:
    body = build_new_only_summary(
        (
            _note("meet", note_class=GoodNotesNoteClass.MEETING, transcription="synthetic meeting"),
            _note("proj", note_class=GoodNotesNoteClass.PROJECT, transcription="synthetic project"),
            _note(
                "rel",
                note_class=GoodNotesNoteClass.RELATIONSHIP,
                transcription="synthetic relationship",
            ),
            _note("gen", note_class=GoodNotesNoteClass.GENERAL, transcription="synthetic general"),
        )
    )
    assert body is not None
    meeting, project, relationship, general = body.split("\n\n")
    assert meeting.startswith("NEW MEETING NOTES")
    assert "synthetic meeting" in meeting
    assert project.startswith("NEW PROJECT NOTES")
    assert "synthetic project" in project
    assert relationship.startswith("NEW RELATIONSHIP NOTES")
    assert "synthetic relationship" in relationship
    assert general.startswith("NEW GENERAL NOTES")
    assert "synthetic general" in general


def test_empty_new_set_suppresses_user_facing_body() -> None:
    assert build_new_only_summary(()) is None


def test_low_confidence_is_only_for_uncertain_new_notes() -> None:
    body = build_new_only_summary(
        (
            _note(
                "sure",
                note_class=GoodNotesNoteClass.MEETING,
                transcription="synthetic note",
            ),
            _note(
                "unsure",
                note_class=GoodNotesNoteClass.MEETING,
                transcription="synthetic heading",
                uncertain=True,
            ),
            _note(
                "missing-class",
                note_class=None,
                transcription="synthetic review",
                uncertain=True,
            ),
        )
    )
    assert body is not None
    assert "LOW-CONFIDENCE / REVIEW NEEDED" in body
    review = body.split("LOW-CONFIDENCE / REVIEW NEEDED", 1)[1]
    assert "synthetic heading" in review
    assert "synthetic review" in review
    assert review.count("synthetic note") == 0
    assert "synthetic note" in body.split("LOW-CONFIDENCE / REVIEW NEEDED", 1)[0]


def test_identical_transcriptions_in_different_geometry_both_appear() -> None:
    body = build_new_only_summary(
        (
            _note("left", note_class=GoodNotesNoteClass.MEETING, transcription="synthetic note"),
            _note("right", note_class=GoodNotesNoteClass.MEETING, transcription="synthetic note"),
        )
    )
    assert body is not None
    assert body.count("synthetic note") == 2


def test_unique_exact_candidate_associates_and_ambiguous_name_does_not() -> None:
    project_id = "prj_aaaaaaaaaaaaaaaa"
    directory = (
        GoodNotesEntityDirectoryRecord(
            entity_id=project_id,
            kind=GoodNotesEntityKind.PROJECT,
            normalized_name="alpha project",
        ),
        GoodNotesEntityDirectoryRecord(
            entity_id="prj_bbbbbbbbbbbbbbbb",
            kind=GoodNotesEntityKind.PROJECT,
            normalized_name="shared name",
        ),
        GoodNotesEntityDirectoryRecord(
            entity_id="prj_cccccccccccccccc",
            kind=GoodNotesEntityKind.PROJECT,
            normalized_name="shared name",
        ),
    )
    associated = resolve_entity_candidate("Alpha Project", directory)
    by_id = resolve_entity_candidate(project_id, directory)
    ambiguous = resolve_entity_candidate("shared name", directory)
    missing = resolve_entity_candidate("no such project", directory)
    close = resolve_entity_candidate("Alpha Project!", directory)
    assert associated == (
        GoodNotesEntityResolution.ASSOCIATED,
        GoodNotesEntityKind.PROJECT,
        project_id,
    )
    assert by_id == associated
    assert ambiguous == (GoodNotesEntityResolution.UNRESOLVED, None, None)
    assert missing == (GoodNotesEntityResolution.UNRESOLVED, None, None)
    assert close == (GoodNotesEntityResolution.UNRESOLVED, None, None)


def test_uncertainty_uses_missing_class_and_proposal_confidence() -> None:
    assert new_note_is_uncertain(primary_class=None, confidence=None)
    assert not new_note_is_uncertain(
        primary_class=GoodNotesNoteClass.MEETING, confidence={"linking": 0.9}
    )
    assert new_note_is_uncertain(
        primary_class=GoodNotesNoteClass.MEETING, confidence={"uncertainty": "handwriting faint"}
    )
    assert new_note_is_uncertain(
        primary_class=GoodNotesNoteClass.MEETING, confidence={"linking": 0.4}
    )
    assert not new_note_is_uncertain(
        primary_class=GoodNotesNoteClass.MEETING, confidence={"linking": 0.5}
    )


@dataclass
class _FakeDeliveryRepository:
    principal_id: str
    stored_run: GoodNotesIngestionRun | None
    changes: tuple[GoodNotesRunNoteChange, ...]
    occurrences: dict[str, GoodNotesNoteOccurrence]
    revisions: dict[str, object]
    proposals: tuple[tuple[str, str, str, str, dict[str, object]], ...] = ()
    directory: tuple[GoodNotesEntityDirectoryRecord, ...] = ()
    receipts: list[GoodNotesDeliveryReceipt] = field(default_factory=list)
    associations: list[GoodNotesEntityAssociation] = field(default_factory=list)

    def run(self, principal_id: str, run_id: str) -> GoodNotesIngestionRun | None:
        if principal_id != self.principal_id:
            return None
        if self.stored_run is None or self.stored_run.run_id != run_id:
            return None
        return self.stored_run

    def run_note_changes(
        self, principal_id: str, run_id: str
    ) -> tuple[GoodNotesRunNoteChange, ...]:
        if principal_id != self.principal_id:
            return ()
        return tuple(item for item in self.changes if item.run_id == run_id)

    def occurrence(self, principal_id: str, occurrence_id: str) -> GoodNotesNoteOccurrence | None:
        if principal_id != self.principal_id:
            return None
        return self.occurrences.get(occurrence_id)

    def latest_revision_for_occurrence(self, principal_id: str, occurrence_id: str) -> object:
        if principal_id != self.principal_id:
            return None
        return self.revisions.get(occurrence_id)

    def semantic_proposals_for_run(
        self, principal_id: str, run_id: str
    ) -> tuple[tuple[str, str, str, str, dict[str, object]], ...]:
        if principal_id != self.principal_id:
            return ()
        return self.proposals

    def entity_directory(self, principal_id: str) -> tuple[GoodNotesEntityDirectoryRecord, ...]:
        if principal_id != self.principal_id:
            return ()
        return self.directory

    def store_entity_association(
        self, association: GoodNotesEntityAssociation
    ) -> GoodNotesEntityAssociation:
        self.associations.append(association)
        return association

    def entity_associations_for_run(
        self, principal_id: str, run_id: str
    ) -> tuple[GoodNotesEntityAssociation, ...]:
        if principal_id != self.principal_id:
            return ()
        return tuple(item for item in self.associations if item.run_id == run_id)

    def store_delivery_receipt(self, receipt: GoodNotesDeliveryReceipt) -> GoodNotesDeliveryReceipt:
        self.receipts.append(receipt)
        return receipt

    def delivery_receipt_by_key(
        self,
        principal_id: str,
        run_id: str,
        destination: str,
        summary_hash: str,
    ) -> GoodNotesDeliveryReceipt | None:
        if principal_id != self.principal_id:
            return None
        for item in self.receipts:
            if (
                item.run_id == run_id
                and item.destination == destination
                and item.summary_hash == summary_hash
            ):
                return item
        return None


def _run() -> GoodNotesIngestionRun:
    return GoodNotesIngestionRun(
        run_id=RUN,
        principal_id=A,
        source_root_id="icloud-goodnotes",
        trigger_type=GoodNotesIngestionTrigger.MANUAL,
        request_id="req-summary",
        idempotency_key="req-summary",
        request_fingerprint="c" * 64,
        started_at=WHEN,
        status=GoodNotesIngestionStatus.RUNNING,
    )


def _change(token: str, state: GoodNotesNoteChangeState) -> GoodNotesRunNoteChange:
    return GoodNotesRunNoteChange(
        change_id=issue_stable_id("gnchg", token),
        principal_id=A,
        run_id=RUN,
        note_id=issue_stable_id("gnnt", token),
        occurrence_id=issue_stable_id("gnocc", token),
        change_state=state,
        created_at=WHEN,
    )


def _occurrence(token: str, page_version_id: str) -> GoodNotesNoteOccurrence:
    return GoodNotesNoteOccurrence(
        occurrence_id=issue_stable_id("gnocc", token),
        principal_id=A,
        note_id=issue_stable_id("gnnt", token),
        logical_page_id=issue_stable_id("gnlp", token),
        x_min=0.1,
        y_min=0.2,
        width=0.2,
        height=0.1,
        identity_status=GoodNotesIdentityStatus.ACTIVE,
        created_at=WHEN,
        last_seen_at=WHEN,
        page_version_id=page_version_id,
    )


def test_deliver_filters_non_new_changes_and_replays_the_same_receipt() -> None:
    from my_pa.domain.goodnotes.models import GoodNotesNoteRevision

    page = issue_stable_id("gnver", "page")
    new_change = _change("new", GoodNotesNoteChangeState.NEW)
    revised = _change("revised", GoodNotesNoteChangeState.REVISED)
    unchanged = _change("unchanged", GoodNotesNoteChangeState.UNCHANGED)
    ambiguous = _change("ambiguous", GoodNotesNoteChangeState.AMBIGUOUS)
    revision = GoodNotesNoteRevision(
        revision_id=issue_stable_id("gnrev", "new"),
        principal_id=A,
        note_id=new_change.note_id,
        schema_version="note-unit.v1",
        analyzer_name="synthetic",
        analyzer_version="1",
        transcription="synthetic note",
        created_at=WHEN,
        occurrence_id=new_change.occurrence_id,
        primary_class=GoodNotesNoteClass.MEETING,
    )
    repo = _FakeDeliveryRepository(
        principal_id=A,
        stored_run=_run(),
        changes=(new_change, revised, unchanged, ambiguous),
        occurrences={new_change.occurrence_id: _occurrence("new", page)},
        revisions={new_change.occurrence_id: revision},
        proposals=(
            (
                page,
                "note-unit.v1",
                "synthetic",
                "1",
                {
                    "ranked_candidates": [{"rank": 1, "candidate": "missing project"}],
                    "confidence": {"uncertainty": "faint ink"},
                },
            ),
        ),
    )
    service = GoodNotesNewOnlyDelivery()
    first = service.deliver(A, RUN, DESTINATION, repository=repo, clock=lambda: WHEN)
    assert first.receipt.replayed is False
    assert first.receipt.suppressed is False
    assert first.receipt.body is not None
    assert "synthetic note" in first.receipt.body
    assert "NEW MEETING NOTES" in first.receipt.body
    assert "LOW-CONFIDENCE / REVIEW NEEDED" in first.receipt.body
    assert "REVISED" not in first.receipt.body
    assert len(first.associations) == 1
    assert first.associations[0].resolution is GoodNotesEntityResolution.UNRESOLVED
    second = service.deliver(A, RUN, DESTINATION, repository=repo, clock=lambda: WHEN)
    assert second.receipt.replayed is True
    assert second.receipt.receipt_id == first.receipt.receipt_id
    assert len(repo.receipts) == 1


def test_no_new_run_writes_a_suppressed_internal_receipt() -> None:
    repo = _FakeDeliveryRepository(
        principal_id=A,
        stored_run=_run(),
        changes=(_change("revised", GoodNotesNoteChangeState.REVISED),),
        occurrences={},
        revisions={},
    )
    result = GoodNotesNewOnlyDelivery().deliver(
        A, RUN, DESTINATION, repository=repo, clock=lambda: WHEN
    )
    assert result.receipt.suppressed is True
    assert result.receipt.body is None
    assert result.receipt.replayed is False
    assert result.associations == ()


def test_missing_run_fails_closed() -> None:
    repo = _FakeDeliveryRepository(
        principal_id=A,
        stored_run=None,
        changes=(),
        occurrences={},
        revisions={},
    )
    with pytest.raises(ValueError, match="no stored GoodNotes ingestion run"):
        GoodNotesNewOnlyDelivery().deliver(A, RUN, DESTINATION, repository=repo, clock=lambda: WHEN)


def test_principal_mismatch_does_not_see_another_partition() -> None:
    repo = _FakeDeliveryRepository(
        principal_id=A,
        stored_run=_run(),
        changes=(),
        occurrences={},
        revisions={},
    )
    with pytest.raises(ValueError, match="no stored GoodNotes ingestion run"):
        GoodNotesNewOnlyDelivery().deliver(
            "prn_bbbbbbbbbbbbbbbbbbbbbbbb",
            RUN,
            DESTINATION,
            repository=repo,
            clock=lambda: WHEN,
        )


def test_delivery_receipt_hides_transcription_from_repr() -> None:
    receipt = GoodNotesDeliveryReceipt(
        receipt_id=issue_stable_id("gndlv", "repr"),
        principal_id=A,
        run_id=RUN,
        destination=DESTINATION,
        summary_hash="a" * 64,
        suppressed=False,
        created_at=WHEN,
        body="synthetic note",
    )
    assert "synthetic note" not in repr(receipt)
    assert replace(receipt, suppressed=True, body=None).suppressed is True
