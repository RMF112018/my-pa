"""NEW-only summary membership, entity resolution, and suppressed empty delivery."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import pytest

from my_pa.application.goodnotes_delivery import (
    GoodNotesDeliveryAttemptLedger,
    GoodNotesNewOnlyDelivery,
    NewOnlySummaryNote,
    build_new_only_summary,
    new_note_is_uncertain,
    resolve_entity_candidate,
)
from my_pa.contracts.ports import GoodNotesSemanticProposalMaterial
from my_pa.domain.goodnotes.models import (
    GoodNotesDeliveryAttempt,
    GoodNotesDeliveryAttemptState,
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
    GoodNotesNoteRevision,
    GoodNotesRunNoteChange,
    issue_stable_id,
)

WHEN = datetime(2026, 8, 16, 22, 0, tzinfo=UTC)
LATER = WHEN + timedelta(hours=1)
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
    attempt = issue_stable_id("gndla", "synthetic", "attempt")
    assert receipt.startswith("gndlv_") and len(receipt) == 30
    assert association.startswith("gnent_") and len(association) == 30
    assert attempt.startswith("gndla_") and len(attempt) == 30
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
    meeting_id = "mtg_aaaaaaaaaaaaaaaa"
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
        GoodNotesEntityDirectoryRecord(
            entity_id=meeting_id,
            kind=GoodNotesEntityKind.MEETING,
            normalized_name="staff meeting",
        ),
    )
    associated = resolve_entity_candidate("Alpha Project", directory)
    by_id = resolve_entity_candidate(project_id, directory)
    meeting = resolve_entity_candidate("Staff Meeting", directory)
    meeting_id_hit = resolve_entity_candidate(meeting_id, directory)
    ambiguous = resolve_entity_candidate("shared name", directory)
    missing = resolve_entity_candidate("no such project", directory)
    close = resolve_entity_candidate("Alpha Project!", directory)
    empty_meeting = resolve_entity_candidate("Staff Meeting", ())
    assert associated == (
        GoodNotesEntityResolution.ASSOCIATED,
        GoodNotesEntityKind.PROJECT,
        project_id,
    )
    assert by_id == associated
    assert meeting == (
        GoodNotesEntityResolution.ASSOCIATED,
        GoodNotesEntityKind.MEETING,
        meeting_id,
    )
    assert meeting_id_hit == meeting
    assert ambiguous == (GoodNotesEntityResolution.UNRESOLVED, None, None)
    assert missing == (GoodNotesEntityResolution.UNRESOLVED, None, None)
    assert close == (GoodNotesEntityResolution.UNRESOLVED, None, None)
    assert empty_meeting == (GoodNotesEntityResolution.UNRESOLVED, None, None)
    assert {member.value for member in GoodNotesEntityKind} == {
        "PROJECT",
        "PERSON",
        "NOTE",
        "MEETING",
        "AGENDA",
    }


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
    revisions: dict[str, GoodNotesNoteRevision]
    proposals: tuple[tuple[str, str, str, str, dict[str, object]], ...] = ()
    directory: tuple[GoodNotesEntityDirectoryRecord, ...] = ()
    receipts: list[GoodNotesDeliveryReceipt] = field(default_factory=list)
    associations: list[GoodNotesEntityAssociation] = field(default_factory=list)
    attempts: list[GoodNotesDeliveryAttempt] = field(default_factory=list)

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

    def revision(self, principal_id: str, revision_id: str) -> GoodNotesNoteRevision | None:
        if principal_id != self.principal_id:
            return None
        return self.revisions.get(revision_id)

    def latest_revision_for_occurrence(
        self, principal_id: str, occurrence_id: str
    ) -> GoodNotesNoteRevision | None:
        if principal_id != self.principal_id:
            return None
        matches = tuple(
            item
            for item in self.revisions.values()
            if item.principal_id == principal_id and item.occurrence_id == occurrence_id
        )
        if not matches:
            return None
        return max(matches, key=lambda item: (item.created_at, item.revision_id))

    def semantic_proposals_for_run(
        self, principal_id: str, run_id: str
    ) -> tuple[tuple[str, str, str, str, dict[str, object]], ...]:
        if principal_id != self.principal_id:
            return ()
        return self.proposals

    def accepted_semantic_material(
        self, principal_id: str, run_id: str, *, require_promoted: bool = False
    ) -> tuple[GoodNotesSemanticProposalMaterial, ...] | None:
        if self.run(principal_id, run_id) is None:
            return None
        return tuple(
            GoodNotesSemanticProposalMaterial(
                proposal_id=issue_stable_id("gnrun", principal_id, run_id, row[0]),
                run_id=run_id,
                page_version_id=row[0],
                content_sha256="a" * 64,
                schema_version=row[1],
                analyzer_name=row[2],
                analyzer_version=row[3],
                payload=row[4],
            )
            for row in self.proposals
        )

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

    def delivery_receipts_for_run(
        self, principal_id: str, run_id: str
    ) -> tuple[GoodNotesDeliveryReceipt, ...]:
        if principal_id != self.principal_id:
            return ()
        return tuple(item for item in self.receipts if item.run_id == run_id)

    def store_delivery_attempt(self, attempt: GoodNotesDeliveryAttempt) -> GoodNotesDeliveryAttempt:
        for existing in self.attempts:
            if existing.attempt_id == attempt.attempt_id:
                return existing
            if (
                existing.idempotency_token == attempt.idempotency_token
                and existing.state is attempt.state
            ):
                return existing
        self.attempts.append(attempt)
        return attempt

    def delivery_attempt(
        self, principal_id: str, attempt_id: str
    ) -> GoodNotesDeliveryAttempt | None:
        if principal_id != self.principal_id:
            return None
        for item in self.attempts:
            if item.attempt_id == attempt_id:
                return item
        return None

    def delivery_attempts_for_token(
        self, principal_id: str, idempotency_token: str
    ) -> tuple[GoodNotesDeliveryAttempt, ...]:
        if principal_id != self.principal_id:
            return ()
        return tuple(item for item in self.attempts if item.idempotency_token == idempotency_token)


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


def _change(
    token: str,
    state: GoodNotesNoteChangeState,
    *,
    revision_id: str | None = None,
) -> GoodNotesRunNoteChange:
    return GoodNotesRunNoteChange(
        change_id=issue_stable_id("gnchg", token),
        principal_id=A,
        run_id=RUN,
        note_id=issue_stable_id("gnnt", token),
        occurrence_id=issue_stable_id("gnocc", token),
        change_state=state,
        created_at=WHEN,
        revision_id=revision_id,
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
    page = issue_stable_id("gnver", "page")
    revision = GoodNotesNoteRevision(
        revision_id=issue_stable_id("gnrev", "new"),
        principal_id=A,
        note_id=issue_stable_id("gnnt", "new"),
        schema_version="note-unit.v1",
        analyzer_name="synthetic",
        analyzer_version="1",
        transcription="synthetic note",
        created_at=WHEN,
        occurrence_id=issue_stable_id("gnocc", "new"),
        primary_class=GoodNotesNoteClass.MEETING,
    )
    new_change = _change("new", GoodNotesNoteChangeState.NEW, revision_id=revision.revision_id)
    revised = _change("revised", GoodNotesNoteChangeState.REVISED)
    unchanged = _change("unchanged", GoodNotesNoteChangeState.UNCHANGED)
    ambiguous = _change("ambiguous", GoodNotesNoteChangeState.AMBIGUOUS)
    repo = _FakeDeliveryRepository(
        principal_id=A,
        stored_run=_run(),
        changes=(new_change, revised, unchanged, ambiguous),
        occurrences={new_change.occurrence_id: _occurrence("new", page)},
        revisions={revision.revision_id: revision},
        proposals=(
            (
                page,
                "note-unit.v2",
                "synthetic",
                "1",
                {
                    "segments": [
                        {
                            "kind": "NOTE_UNIT",
                            "geometry": {
                                "x_min": 0.1,
                                "y_min": 0.2,
                                "width": 0.2,
                                "height": 0.1,
                            },
                            "transcription": "synthetic note",
                            "ranked_candidates": [{"rank": 1, "candidate": "missing project"}],
                            "confidence": {"uncertainty": "faint ink"},
                        }
                    ],
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


def test_v1_page_level_candidates_do_not_attach_to_two_note_units() -> None:
    page = issue_stable_id("gnver", "mixed-v1")
    left_revision = GoodNotesNoteRevision(
        revision_id=issue_stable_id("gnrev", "left"),
        principal_id=A,
        note_id=issue_stable_id("gnnt", "left"),
        schema_version="note-unit.v1",
        analyzer_name="synthetic",
        analyzer_version="1",
        transcription="synthetic left",
        created_at=WHEN,
        occurrence_id=issue_stable_id("gnocc", "left"),
        primary_class=GoodNotesNoteClass.MEETING,
    )
    right_revision = GoodNotesNoteRevision(
        revision_id=issue_stable_id("gnrev", "right"),
        principal_id=A,
        note_id=issue_stable_id("gnnt", "right"),
        schema_version="note-unit.v1",
        analyzer_name="synthetic",
        analyzer_version="1",
        transcription="synthetic right",
        created_at=WHEN,
        occurrence_id=issue_stable_id("gnocc", "right"),
        primary_class=GoodNotesNoteClass.MEETING,
    )
    left = _change("left", GoodNotesNoteChangeState.NEW, revision_id=left_revision.revision_id)
    right = _change("right", GoodNotesNoteChangeState.NEW, revision_id=right_revision.revision_id)
    revisions = {
        left_revision.revision_id: left_revision,
        right_revision.revision_id: right_revision,
    }
    repo = _FakeDeliveryRepository(
        principal_id=A,
        stored_run=_run(),
        changes=(left, right),
        occurrences={
            left.occurrence_id: _occurrence("left", page),
            right.occurrence_id: replace(_occurrence("right", page), x_min=0.6),
        },
        revisions=revisions,
        proposals=(
            (
                page,
                "note-unit.v1",
                "synthetic",
                "1",
                {
                    "segments": [
                        {
                            "kind": "NOTE_UNIT",
                            "geometry": {
                                "x_min": 0.1,
                                "y_min": 0.2,
                                "width": 0.2,
                                "height": 0.1,
                            },
                            "transcription": "synthetic left",
                        },
                        {
                            "kind": "NOTE_UNIT",
                            "geometry": {
                                "x_min": 0.6,
                                "y_min": 0.2,
                                "width": 0.2,
                                "height": 0.1,
                            },
                            "transcription": "synthetic right",
                        },
                    ],
                    "ranked_candidates": [{"rank": 1, "candidate": "Alpha Project"}],
                },
            ),
        ),
        directory=(
            GoodNotesEntityDirectoryRecord(
                entity_id="prj_aaaaaaaaaaaaaaaa",
                kind=GoodNotesEntityKind.PROJECT,
                normalized_name="alpha project",
            ),
        ),
    )
    result = GoodNotesNewOnlyDelivery().deliver(
        A, RUN, DESTINATION, repository=repo, clock=lambda: WHEN
    )
    assert result.associations == ()


def test_v2_mixed_page_candidates_stay_on_the_note_unit_that_named_them() -> None:
    page = issue_stable_id("gnver", "mixed-v2")
    left_revision = GoodNotesNoteRevision(
        revision_id=issue_stable_id("gnrev", "left-v2"),
        principal_id=A,
        note_id=issue_stable_id("gnnt", "left-v2"),
        schema_version="note-unit.v2",
        analyzer_name="synthetic",
        analyzer_version="1",
        transcription="synthetic left",
        created_at=WHEN,
        occurrence_id=issue_stable_id("gnocc", "left-v2"),
        primary_class=GoodNotesNoteClass.MEETING,
    )
    right_revision = GoodNotesNoteRevision(
        revision_id=issue_stable_id("gnrev", "right-v2"),
        principal_id=A,
        note_id=issue_stable_id("gnnt", "right-v2"),
        schema_version="note-unit.v2",
        analyzer_name="synthetic",
        analyzer_version="1",
        transcription="synthetic right",
        created_at=WHEN,
        occurrence_id=issue_stable_id("gnocc", "right-v2"),
        primary_class=GoodNotesNoteClass.MEETING,
    )
    left = _change("left-v2", GoodNotesNoteChangeState.NEW, revision_id=left_revision.revision_id)
    right = _change(
        "right-v2", GoodNotesNoteChangeState.NEW, revision_id=right_revision.revision_id
    )
    revisions = {
        left_revision.revision_id: left_revision,
        right_revision.revision_id: right_revision,
    }
    repo = _FakeDeliveryRepository(
        principal_id=A,
        stored_run=_run(),
        changes=(left, right),
        occurrences={
            left.occurrence_id: _occurrence("left-v2", page),
            right.occurrence_id: replace(_occurrence("right-v2", page), x_min=0.6),
        },
        revisions=revisions,
        proposals=(
            (
                page,
                "note-unit.v2",
                "synthetic",
                "1",
                {
                    "segments": [
                        {
                            "kind": "NOTE_UNIT",
                            "geometry": {
                                "x_min": 0.1,
                                "y_min": 0.2,
                                "width": 0.2,
                                "height": 0.1,
                            },
                            "transcription": "synthetic left",
                            "ranked_candidates": [{"rank": 1, "candidate": "Alpha Project"}],
                        },
                        {
                            "kind": "NOTE_UNIT",
                            "geometry": {
                                "x_min": 0.6,
                                "y_min": 0.2,
                                "width": 0.2,
                                "height": 0.1,
                            },
                            "transcription": "synthetic right",
                            "ranked_candidates": [{"rank": 1, "candidate": "Beta Project"}],
                        },
                    ],
                },
            ),
        ),
        directory=(
            GoodNotesEntityDirectoryRecord(
                entity_id="prj_aaaaaaaaaaaaaaaa",
                kind=GoodNotesEntityKind.PROJECT,
                normalized_name="alpha project",
            ),
            GoodNotesEntityDirectoryRecord(
                entity_id="prj_bbbbbbbbbbbbbbbb",
                kind=GoodNotesEntityKind.PROJECT,
                normalized_name="beta project",
            ),
        ),
    )
    result = GoodNotesNewOnlyDelivery().deliver(
        A, RUN, DESTINATION, repository=repo, clock=lambda: WHEN
    )
    by_note = {item.note_id: item for item in result.associations}
    assert set(by_note) == {left.note_id, right.note_id}
    assert by_note[left.note_id].candidate == "Alpha Project"
    assert by_note[left.note_id].resolved_id == "prj_aaaaaaaaaaaaaaaa"
    assert by_note[right.note_id].candidate == "Beta Project"
    assert by_note[right.note_id].resolved_id == "prj_bbbbbbbbbbbbbbbb"


def _meeting_revision(token: str, transcription: str) -> GoodNotesNoteRevision:
    return GoodNotesNoteRevision(
        revision_id=issue_stable_id("gnrev", token),
        principal_id=A,
        note_id=issue_stable_id("gnnt", token),
        schema_version="note-unit.v1",
        analyzer_name="synthetic",
        analyzer_version="1",
        transcription=transcription,
        created_at=WHEN,
        occurrence_id=issue_stable_id("gnocc", token),
        primary_class=GoodNotesNoteClass.MEETING,
    )


def test_historical_run_uses_the_bound_revision_not_a_later_correction() -> None:
    page = issue_stable_id("gnver", "bound")
    bound = _meeting_revision("bound", "synthetic original")
    later = replace(
        bound,
        revision_id=issue_stable_id("gnrev", "later"),
        transcription="synthetic corrected",
        created_at=LATER,
        supersedes_revision_id=bound.revision_id,
    )
    change = _change("bound", GoodNotesNoteChangeState.NEW, revision_id=bound.revision_id)
    repo = _FakeDeliveryRepository(
        principal_id=A,
        stored_run=_run(),
        changes=(change,),
        occurrences={change.occurrence_id: _occurrence("bound", page)},
        revisions={bound.revision_id: bound},
    )
    first = GoodNotesNewOnlyDelivery().deliver(
        A, RUN, DESTINATION, repository=repo, clock=lambda: WHEN
    )
    assert first.receipt.body is not None
    assert "synthetic original" in first.receipt.body
    assert "synthetic corrected" not in first.receipt.body
    repo.revisions[later.revision_id] = later
    second = GoodNotesNewOnlyDelivery().deliver(
        A, RUN, DESTINATION, repository=repo, clock=lambda: LATER
    )
    assert second.receipt.replayed is True
    assert second.receipt.summary_hash == first.receipt.summary_hash
    assert second.receipt.body == first.receipt.body
    repo.occurrences[change.occurrence_id] = replace(
        repo.occurrences[change.occurrence_id],
        identity_status=GoodNotesIdentityStatus.RETIRED,
    )
    third = GoodNotesNewOnlyDelivery().deliver(
        A, RUN, DESTINATION, repository=repo, clock=lambda: LATER
    )
    assert third.receipt.replayed is True
    assert third.receipt.receipt_id == first.receipt.receipt_id
    assert third.receipt.summary_hash == first.receipt.summary_hash
    assert third.receipt.body == first.receipt.body
    assert len(repo.receipts) == 1


def test_first_delivery_rejects_a_superseded_revision_without_writing() -> None:
    page = issue_stable_id("gnver", "superseded")
    bound = _meeting_revision("superseded", "synthetic original")
    later = replace(
        bound,
        revision_id=issue_stable_id("gnrev", "superseded-later"),
        transcription="synthetic corrected",
        created_at=LATER,
        supersedes_revision_id=bound.revision_id,
    )
    change = _change("superseded", GoodNotesNoteChangeState.NEW, revision_id=bound.revision_id)
    repo = _FakeDeliveryRepository(
        principal_id=A,
        stored_run=_run(),
        changes=(change,),
        occurrences={change.occurrence_id: _occurrence("superseded", page)},
        revisions={bound.revision_id: bound, later.revision_id: later},
    )
    with pytest.raises(ValueError, match="revision is superseded"):
        GoodNotesNewOnlyDelivery().deliver(
            A, RUN, DESTINATION, repository=repo, clock=lambda: LATER
        )
    assert repo.receipts == []
    assert repo.associations == []


@pytest.mark.parametrize(
    "identity_status",
    (GoodNotesIdentityStatus.AMBIGUOUS, GoodNotesIdentityStatus.RETIRED),
)
def test_delivery_rejects_non_active_occurrence_without_writing(
    identity_status: GoodNotesIdentityStatus,
) -> None:
    page = issue_stable_id("gnver", "inactive")
    revision = _meeting_revision("inactive", "synthetic note")
    change = _change("inactive", GoodNotesNoteChangeState.NEW, revision_id=revision.revision_id)
    occurrence = replace(_occurrence("inactive", page), identity_status=identity_status)
    repo = _FakeDeliveryRepository(
        principal_id=A,
        stored_run=_run(),
        changes=(change,),
        occurrences={change.occurrence_id: occurrence},
        revisions={revision.revision_id: revision},
    )
    with pytest.raises(ValueError, match="occurrence is not active"):
        GoodNotesNewOnlyDelivery().deliver(A, RUN, DESTINATION, repository=repo, clock=lambda: WHEN)
    assert repo.receipts == []
    assert repo.associations == []


def test_delivery_rejects_mismatched_or_missing_trace_without_writing() -> None:
    page = issue_stable_id("gnver", "trace")
    revision = _meeting_revision("trace", "synthetic note")
    change = _change("trace", GoodNotesNoteChangeState.NEW, revision_id=revision.revision_id)
    occurrence = _occurrence("trace", page)
    mismatched = replace(revision, note_id=issue_stable_id("gnnt", "other-note"))
    repo = _FakeDeliveryRepository(
        principal_id=A,
        stored_run=_run(),
        changes=(change,),
        occurrences={change.occurrence_id: occurrence},
        revisions={mismatched.revision_id: mismatched},
    )
    with pytest.raises(ValueError, match="evidence trace does not match"):
        GoodNotesNewOnlyDelivery().deliver(A, RUN, DESTINATION, repository=repo, clock=lambda: WHEN)
    repo.revisions[revision.revision_id] = revision
    repo.occurrences[change.occurrence_id] = replace(occurrence, page_version_id=None)
    with pytest.raises(ValueError, match="no page-version trace"):
        GoodNotesNewOnlyDelivery().deliver(A, RUN, DESTINATION, repository=repo, clock=lambda: WHEN)
    assert repo.receipts == []
    assert repo.associations == []


def test_null_revision_id_does_not_reconstruct_from_latest() -> None:
    page = issue_stable_id("gnver", "legacy")
    latest = _meeting_revision("legacy", "synthetic latest")
    change = _change("legacy", GoodNotesNoteChangeState.NEW)
    repo = _FakeDeliveryRepository(
        principal_id=A,
        stored_run=_run(),
        changes=(change,),
        occurrences={change.occurrence_id: _occurrence("legacy", page)},
        revisions={latest.revision_id: latest},
    )
    with pytest.raises(ValueError, match="no stored GoodNotes note revision"):
        GoodNotesNewOnlyDelivery().deliver(A, RUN, DESTINATION, repository=repo, clock=lambda: WHEN)


def test_missing_named_revision_fails_closed() -> None:
    page = issue_stable_id("gnver", "missing-rev")
    named = issue_stable_id("gnrev", "missing-rev")
    other = _meeting_revision("other", "synthetic other")
    change = _change("missing-rev", GoodNotesNoteChangeState.NEW, revision_id=named)
    repo = _FakeDeliveryRepository(
        principal_id=A,
        stored_run=_run(),
        changes=(change,),
        occurrences={change.occurrence_id: _occurrence("missing-rev", page)},
        revisions={other.revision_id: other},
    )
    with pytest.raises(ValueError, match="no stored GoodNotes note revision"):
        GoodNotesNewOnlyDelivery().deliver(A, RUN, DESTINATION, repository=repo, clock=lambda: WHEN)


def test_attempt_ledger_records_crash_windows_without_duplicate_receipts() -> None:
    page = issue_stable_id("gnver", "crash")
    bound = _meeting_revision("crash", "synthetic note")
    change = _change("crash", GoodNotesNoteChangeState.NEW, revision_id=bound.revision_id)
    repo = _FakeDeliveryRepository(
        principal_id=A,
        stored_run=_run(),
        changes=(change,),
        occurrences={change.occurrence_id: _occurrence("crash", page)},
        revisions={bound.revision_id: bound},
    )
    ledger = GoodNotesDeliveryAttemptLedger()
    window = "crash-window"
    prepared = ledger.record(
        A, RUN, DESTINATION, window, GoodNotesDeliveryAttemptState.PREPARED, repository=repo
    )
    sent = ledger.record(
        A, RUN, DESTINATION, window, GoodNotesDeliveryAttemptState.SENT, repository=repo
    )
    assert {item.state for item in repo.attempts} == {
        GoodNotesDeliveryAttemptState.PREPARED,
        GoodNotesDeliveryAttemptState.SENT,
    }
    assert repo.receipts == []
    result = GoodNotesNewOnlyDelivery().deliver(
        A, RUN, DESTINATION, repository=repo, clock=lambda: WHEN
    )
    acknowledged = ledger.record(
        A,
        RUN,
        DESTINATION,
        window,
        GoodNotesDeliveryAttemptState.ACKNOWLEDGED,
        repository=repo,
        summary_hash=result.receipt.summary_hash,
        receipt_id=result.receipt.receipt_id,
    )
    replayed_prepared = ledger.record(
        A, RUN, DESTINATION, window, GoodNotesDeliveryAttemptState.PREPARED, repository=repo
    )
    replay = GoodNotesNewOnlyDelivery().deliver(
        A, RUN, DESTINATION, repository=repo, clock=lambda: LATER
    )
    replayed_ack = ledger.record(
        A,
        RUN,
        DESTINATION,
        window,
        GoodNotesDeliveryAttemptState.ACKNOWLEDGED,
        repository=repo,
        summary_hash=result.receipt.summary_hash,
        receipt_id=result.receipt.receipt_id,
    )
    assert replay.receipt.replayed is True
    assert replay.receipt.receipt_id == result.receipt.receipt_id
    assert len(repo.receipts) == 1
    assert replayed_prepared.attempt_id == prepared.attempt_id
    assert replayed_ack.attempt_id == acknowledged.attempt_id
    assert sent.state is GoodNotesDeliveryAttemptState.SENT
    states = [item.state for item in repo.delivery_attempts_for_token(A, window)]
    assert states == [
        GoodNotesDeliveryAttemptState.PREPARED,
        GoodNotesDeliveryAttemptState.SENT,
        GoodNotesDeliveryAttemptState.ACKNOWLEDGED,
    ]


def test_failed_attempt_does_not_invent_a_receipt() -> None:
    page = issue_stable_id("gnver", "failed")
    bound = _meeting_revision("failed", "synthetic note")
    change = _change("failed", GoodNotesNoteChangeState.NEW, revision_id=bound.revision_id)
    repo = _FakeDeliveryRepository(
        principal_id=A,
        stored_run=_run(),
        changes=(change,),
        occurrences={change.occurrence_id: _occurrence("failed", page)},
        revisions={bound.revision_id: bound},
    )
    ledger = GoodNotesDeliveryAttemptLedger()
    window = "failed-window"
    ledger.record(
        A, RUN, DESTINATION, window, GoodNotesDeliveryAttemptState.PREPARED, repository=repo
    )
    failed = ledger.record(
        A, RUN, DESTINATION, window, GoodNotesDeliveryAttemptState.FAILED, repository=repo
    )
    assert failed.state is GoodNotesDeliveryAttemptState.FAILED
    assert repo.receipts == []
    result = GoodNotesNewOnlyDelivery().deliver(
        A, RUN, DESTINATION, repository=repo, clock=lambda: WHEN
    )
    assert result.receipt.replayed is False
    assert len(repo.receipts) == 1
