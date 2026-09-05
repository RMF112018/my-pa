"""Disposable PostgreSQL proof for GoodNotes NOTE_UNIT persistence contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import Executable

from my_pa.domain.goodnotes.models import (
    GoodNotesIdentityStatus,
    GoodNotesIngestionRun,
    GoodNotesIngestionStatus,
    GoodNotesIngestionTrigger,
    GoodNotesLogicalPage,
    GoodNotesMatchMethod,
    GoodNotesNote,
    GoodNotesNotebook,
    GoodNotesNoteChangeState,
    GoodNotesNoteLink,
    GoodNotesNoteLinkKind,
    GoodNotesNoteOccurrence,
    GoodNotesNoteRevision,
    GoodNotesPage,
    GoodNotesPagePosition,
    GoodNotesPageVersion,
    GoodNotesRunNoteChange,
    GoodNotesSourceSnapshot,
    issue_stable_id,
)
from my_pa.infrastructure.persistence.goodnotes import PostgresGoodNotesRepository

pytestmark = pytest.mark.database
ROOT = Path(__file__).resolve().parents[2]
DATABASE = "my_pa_goodnotes_notes_test"
WHEN = datetime(2026, 8, 16, 16, 0, tzinfo=UTC)
LATER = WHEN + timedelta(hours=1)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
B = "prn_bbbbbbbbbbbbbbbbbbbbbbbb"
FINGERPRINT = "c" * 64


def administer(engine: Engine, *statements: Executable) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)


def _notebook(principal_id: str, token: str) -> GoodNotesNotebook:
    return GoodNotesNotebook(
        notebook_id=issue_stable_id("gnnb", principal_id, token),
        principal_id=principal_id,
        source_root_id="icloud-goodnotes",
        identity_status=GoodNotesIdentityStatus.ACTIVE,
        created_at=WHEN,
        last_observed_at=WHEN,
        label=token,
    )


def _run(principal_id: str, token: str) -> GoodNotesIngestionRun:
    request_id = f"req-{principal_id[-4:]}-{token}"
    return GoodNotesIngestionRun(
        run_id=issue_stable_id("gnrun", principal_id, token),
        principal_id=principal_id,
        source_root_id="icloud-goodnotes",
        trigger_type=GoodNotesIngestionTrigger.MANUAL,
        request_id=request_id,
        idempotency_key=request_id,
        request_fingerprint=FINGERPRINT,
        started_at=WHEN,
        status=GoodNotesIngestionStatus.RUNNING,
    )


def _logical(principal_id: str, notebook_id: str, token: str) -> GoodNotesLogicalPage:
    return GoodNotesLogicalPage(
        logical_page_id=issue_stable_id("gnlp", principal_id, token),
        principal_id=principal_id,
        notebook_id=notebook_id,
        created_at=WHEN,
        last_seen_at=WHEN,
        identity_status=GoodNotesIdentityStatus.ACTIVE,
    )


def _note(principal_id: str, notebook_id: str, token: str) -> GoodNotesNote:
    return GoodNotesNote(
        note_id=issue_stable_id("gnnt", principal_id, token),
        principal_id=principal_id,
        notebook_id=notebook_id,
        identity_status=GoodNotesIdentityStatus.ACTIVE,
        created_at=WHEN,
        last_seen_at=WHEN,
    )


def _occurrence(
    principal_id: str,
    note_id: str,
    logical_page_id: str,
    token: str,
    *,
    x_min: float,
    y_min: float = 0.2,
) -> GoodNotesNoteOccurrence:
    return GoodNotesNoteOccurrence(
        occurrence_id=issue_stable_id("gnocc", principal_id, token),
        principal_id=principal_id,
        note_id=note_id,
        logical_page_id=logical_page_id,
        x_min=x_min,
        y_min=y_min,
        width=0.2,
        height=0.1,
        identity_status=GoodNotesIdentityStatus.ACTIVE,
        created_at=WHEN,
        last_seen_at=WHEN,
    )


def _parents(
    repository: PostgresGoodNotesRepository, principal_id: str, token: str
) -> tuple[GoodNotesNotebook, GoodNotesLogicalPage, GoodNotesIngestionRun]:
    notebook = repository.store_notebook(_notebook(principal_id, token))
    logical = repository.store_logical_page(_logical(principal_id, notebook.notebook_id, token))
    run = repository.create_run(_run(principal_id, token))
    return notebook, logical, run


def test_cross_principal_isolation_for_the_same_note_id(engine: Engine) -> None:
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        notebook_a, _, _ = _parents(repository, A, "shared-note")
        notebook_b, _, _ = _parents(repository, B, "shared-note")
        note_id = issue_stable_id("gnnt", "shared", "note")
        stored_a = repository.store_note(
            GoodNotesNote(
                note_id=note_id,
                principal_id=A,
                notebook_id=notebook_a.notebook_id,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
            )
        )
        stored_b = repository.store_note(
            GoodNotesNote(
                note_id=note_id,
                principal_id=B,
                notebook_id=notebook_b.notebook_id,
                identity_status=GoodNotesIdentityStatus.RETIRED,
                created_at=WHEN,
                last_seen_at=LATER,
            )
        )
        assert stored_a.note_id == stored_b.note_id
        fetched_a = repository.note(A, note_id)
        fetched_b = repository.note(B, note_id)
        assert fetched_a is not None and fetched_b is not None
        assert fetched_a.identity_status is GoodNotesIdentityStatus.ACTIVE
        assert fetched_b.identity_status is GoodNotesIdentityStatus.RETIRED
        assert fetched_a.notebook_id != fetched_b.notebook_id


def test_occurrence_identity_does_not_use_transcription(engine: Engine) -> None:
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        notebook, logical, _ = _parents(repository, A, "two-boxes")
        note = repository.store_note(_note(A, notebook.notebook_id, "same-words"))
        left = repository.store_occurrence(
            _occurrence(A, note.note_id, logical.logical_page_id, "left", x_min=0.1)
        )
        right = repository.store_occurrence(
            _occurrence(A, note.note_id, logical.logical_page_id, "right", x_min=0.5)
        )
        assert left.occurrence_id != right.occurrence_id
        assert left.geometry_key != right.geometry_key
        assert repository.occurrence(A, left.occurrence_id) is not None
        assert repository.occurrence(B, left.occurrence_id) is None


def test_revision_same_id_different_transcription_fails_closed(engine: Engine) -> None:
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        notebook, logical, _ = _parents(repository, A, "revision-collision")
        note = repository.store_note(_note(A, notebook.notebook_id, "revision-collision"))
        occurrence = repository.store_occurrence(
            _occurrence(A, note.note_id, logical.logical_page_id, "revision-collision", x_min=0.1)
        )
        first = GoodNotesNoteRevision(
            revision_id=issue_stable_id("gnrev", A, "same"),
            principal_id=A,
            note_id=note.note_id,
            schema_version="note-unit.v1",
            analyzer_name="synthetic",
            analyzer_version="1",
            transcription="follow up Tuesday",
            created_at=WHEN,
            occurrence_id=occurrence.occurrence_id,
        )
        stored = repository.store_revision(first)
        assert stored.transcription == "follow up Tuesday"
        replayed = repository.store_revision(first)
        assert replayed.revision_id == first.revision_id
        with pytest.raises(ValueError, match="collided with other content"):
            repository.store_revision(
                GoodNotesNoteRevision(
                    revision_id=first.revision_id,
                    principal_id=A,
                    note_id=note.note_id,
                    schema_version="note-unit.v1",
                    analyzer_name="synthetic",
                    analyzer_version="1",
                    transcription="follow up Thursday",
                    created_at=WHEN,
                    occurrence_id=occurrence.occurrence_id,
                )
            )


def test_run_cannot_emit_two_states_for_one_occurrence(engine: Engine) -> None:
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        notebook, logical, run = _parents(repository, A, "run-change")
        note = repository.store_note(_note(A, notebook.notebook_id, "run-change"))
        occurrence = repository.store_occurrence(
            _occurrence(A, note.note_id, logical.logical_page_id, "run-change", x_min=0.1)
        )
        first = repository.store_run_note_change(
            GoodNotesRunNoteChange(
                change_id=issue_stable_id("gnchg", A, "first"),
                principal_id=A,
                run_id=run.run_id,
                note_id=note.note_id,
                occurrence_id=occurrence.occurrence_id,
                change_state=GoodNotesNoteChangeState.NEW,
                created_at=WHEN,
            )
        )
        assert first.change_state is GoodNotesNoteChangeState.NEW
        replayed = repository.store_run_note_change(first)
        assert replayed.change_id == first.change_id
        with pytest.raises(ValueError, match="collided with other content"):
            repository.store_run_note_change(
                GoodNotesRunNoteChange(
                    change_id=first.change_id,
                    principal_id=A,
                    run_id=run.run_id,
                    note_id=note.note_id,
                    occurrence_id=occurrence.occurrence_id,
                    change_state=GoodNotesNoteChangeState.REVISED,
                    created_at=WHEN,
                )
            )
        with pytest.raises(IntegrityError), connection.begin_nested():
            repository.store_run_note_change(
                GoodNotesRunNoteChange(
                    change_id=issue_stable_id("gnchg", A, "second"),
                    principal_id=A,
                    run_id=run.run_id,
                    note_id=note.note_id,
                    occurrence_id=occurrence.occurrence_id,
                    change_state=GoodNotesNoteChangeState.REVISED,
                    created_at=WHEN,
                )
            )


def test_structural_note_link_persists_without_entity_resolution(engine: Engine) -> None:
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        notebook, _, _ = _parents(repository, A, "link")
        source = repository.store_note(_note(A, notebook.notebook_id, "link-source"))
        target = repository.store_note(_note(A, notebook.notebook_id, "link-target"))
        stored = repository.store_note_link(
            GoodNotesNoteLink(
                link_id=issue_stable_id("gnlink", A, "pair"),
                principal_id=A,
                note_id=source.note_id,
                link_kind=GoodNotesNoteLinkKind.NOTE_TO_NOTE,
                created_at=WHEN,
                target_note_id=target.note_id,
            )
        )
        assert stored.target_key == f"note:{target.note_id}"
        assert repository.note_link(B, stored.link_id) is None


@pytest.fixture
def engine(db_engine: Engine) -> Engine:
    return db_engine


def _move_target(
    repository: PostgresGoodNotesRepository, notebook_id: str, token: str
) -> tuple[
    GoodNotesLogicalPage, GoodNotesPageVersion, GoodNotesSourceSnapshot, GoodNotesIngestionRun
]:
    logical = repository.store_logical_page(_logical(A, notebook_id, token))
    run = repository.create_run(_run(A, token))
    snapshot = repository.store_snapshot(
        GoodNotesSourceSnapshot(
            snapshot_id=issue_stable_id("gnsnap", A, token),
            principal_id=A,
            notebook_id=notebook_id,
            source_object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
            observed_path="synthetic.pdf",
            raw_sha256=FINGERPRINT,
            size_bytes=1,
            page_count=1,
            observed_at=WHEN,
            settled_at=WHEN,
            run_id=run.run_id,
        )
    )
    page = GoodNotesPage(
        page_id=issue_stable_id("gnpg", A, token),
        principal_id=A,
        source_id="src_aaaaaaaaaaaaaaaaaaaaaaaa",
        source_object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
        page_number=1,
    )
    version = repository.store_page_version_render(
        page=page,
        version=GoodNotesPageVersion(
            page_version_id=issue_stable_id("gnver", A, token),
            page_id=page.page_id,
            source_version_id="ver_aaaaaaaaaaaaaaaaaaaaaaaa",
            content_sha256=FINGERPRINT,
            observed_at=WHEN,
            logical_page_id=logical.logical_page_id,
        ),
    )
    repository.store_page_position(
        GoodNotesPagePosition(
            principal_id=A,
            snapshot_id=snapshot.snapshot_id,
            page_number=1,
            logical_page_id=logical.logical_page_id,
            page_version_id=version.page_version_id,
            match_method=GoodNotesMatchMethod.UNRESOLVED,
            created_at=WHEN,
        )
    )
    return logical, version, snapshot, run


def test_occurrence_move_preserves_identity_and_prior_revision(engine: Engine) -> None:
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        notebook, logical, _ = _parents(repository, A, "move-origin")
        note = repository.store_note(_note(A, notebook.notebook_id, "move-note"))
        prior = repository.store_occurrence(
            _occurrence(A, note.note_id, logical.logical_page_id, "move", x_min=0.1)
        )
        revision = repository.store_revision(
            GoodNotesNoteRevision(
                revision_id=issue_stable_id("gnrev", A, "move-prior"),
                principal_id=A,
                note_id=note.note_id,
                occurrence_id=prior.occurrence_id,
                schema_version="note-unit.v1",
                analyzer_name="synthetic",
                analyzer_version="1",
                transcription="synthetic",
                created_at=WHEN,
            )
        )
        target, version, snapshot, run = _move_target(repository, notebook.notebook_id, "target")
        moved = replace(
            prior,
            logical_page_id=target.logical_page_id,
            page_version_id=version.page_version_id,
            snapshot_id=snapshot.snapshot_id,
            run_id=run.run_id,
            last_seen_at=LATER,
        )
        assert repository.store_occurrence(moved) == moved
        assert repository.store_occurrence(moved) == moved
        assert repository.revision(A, revision.revision_id) == revision
        assert repository.note(A, note.note_id) == note
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        assert repository.occurrence(A, prior.occurrence_id) == moved
        assert repository.occurrence(B, prior.occurrence_id) is None


@pytest.mark.parametrize(
    "invalid", ["notebook", "principal", "version", "snapshot", "run", "missing"]
)
def test_occurrence_move_refuses_foreign_or_inconsistent_location(
    engine: Engine, invalid: str
) -> None:
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        notebook, logical, original_run = _parents(repository, A, "refuse-origin")
        note = repository.store_note(_note(A, notebook.notebook_id, "refuse-note"))
        prior = repository.store_occurrence(
            _occurrence(A, note.note_id, logical.logical_page_id, "refuse", x_min=0.1)
        )
        target, version, snapshot, run = _move_target(repository, notebook.notebook_id, "target")
        moved = replace(
            prior,
            logical_page_id=target.logical_page_id,
            page_version_id=version.page_version_id,
            snapshot_id=snapshot.snapshot_id,
            run_id=run.run_id,
            last_seen_at=LATER,
        )
        if invalid == "notebook":
            other, other_page, _ = _parents(repository, A, "foreign")
            assert other.notebook_id != notebook.notebook_id
            moved = replace(moved, logical_page_id=other_page.logical_page_id)
        elif invalid == "principal":
            moved = replace(moved, principal_id=B)
        elif invalid == "version":
            moved = replace(moved, page_version_id=issue_stable_id("gnver", "missing"))
        elif invalid == "snapshot":
            moved = replace(moved, snapshot_id=issue_stable_id("gnsnap", "missing"))
        elif invalid == "run":
            moved = replace(moved, run_id=original_run.run_id)
        else:
            moved = replace(moved, page_version_id=None)
        with pytest.raises(ValueError):
            repository.store_occurrence(moved)
        assert repository.occurrence(A, prior.occurrence_id) == prior
        assert repository.occurrence(B, prior.occurrence_id) is None


@pytest.mark.parametrize(
    "status", [GoodNotesIdentityStatus.ACTIVE, GoodNotesIdentityStatus.RETIRED]
)
def test_occupied_move_target_refuses_without_mutation(
    engine: Engine, status: GoodNotesIdentityStatus
) -> None:
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        notebook, logical, _ = _parents(repository, A, "occupied-origin")
        note = repository.store_note(_note(A, notebook.notebook_id, "occupied-note"))
        prior = repository.store_occurrence(
            _occurrence(A, note.note_id, logical.logical_page_id, "occupied", x_min=0.1)
        )
        target, version, snapshot, run = _move_target(repository, notebook.notebook_id, "target")
        occupant = repository.store_occurrence(
            replace(
                _occurrence(A, note.note_id, target.logical_page_id, "occupant", x_min=0.1),
                identity_status=status,
            )
        )
    with pytest.raises(ValueError, match="already occupied"), engine.begin() as connection:
        PostgresGoodNotesRepository(connection).store_occurrence(
            replace(
                prior,
                logical_page_id=target.logical_page_id,
                page_version_id=version.page_version_id,
                snapshot_id=snapshot.snapshot_id,
                run_id=run.run_id,
                last_seen_at=LATER,
            )
        )
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        assert repository.occurrence(A, prior.occurrence_id) == prior
        assert repository.occurrence(A, occupant.occurrence_id) == occupant


def test_concurrent_moves_cannot_claim_the_same_target(engine: Engine) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        notebook, logical, _ = _parents(repository, A, "racing-origin")
        note = repository.store_note(_note(A, notebook.notebook_id, "racing-note"))
        left = repository.store_occurrence(
            _occurrence(A, note.note_id, logical.logical_page_id, "racing-left", x_min=0.1)
        )
        right = repository.store_occurrence(
            _occurrence(A, note.note_id, logical.logical_page_id, "racing-right", x_min=0.5)
        )
        target, version, snapshot, run = _move_target(repository, notebook.notebook_id, "target")
        moved_left = replace(
            left,
            logical_page_id=target.logical_page_id,
            page_version_id=version.page_version_id,
            snapshot_id=snapshot.snapshot_id,
            run_id=run.run_id,
            last_seen_at=LATER,
        )
        moved_right = replace(
            right,
            logical_page_id=target.logical_page_id,
            x_min=0.1,
            page_version_id=version.page_version_id,
            snapshot_id=snapshot.snapshot_id,
            run_id=run.run_id,
            last_seen_at=LATER,
        )
    with engine.connect() as winner:
        transaction = winner.begin()
        PostgresGoodNotesRepository(winner).store_occurrence(moved_left)
        with engine.connect() as contender:
            competing = contender.begin()
            contender.execute(text("SET LOCAL lock_timeout = '250ms'"))
            with pytest.raises(DBAPIError, match="lock timeout"):
                PostgresGoodNotesRepository(contender).store_occurrence(moved_right)
            competing.rollback()
        transaction.commit()
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        with pytest.raises(ValueError, match="already occupied"):
            repository.store_occurrence(moved_right)
        assert repository.occurrence(A, left.occurrence_id) == moved_left
        assert repository.occurrence(A, right.occurrence_id) == right
