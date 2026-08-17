"""Disposable PostgreSQL proof for GoodNotes occurrence reconciliation."""

from __future__ import annotations

import hashlib
import io
import os
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.sql import Executable

from my_pa.application.commands import SubmitGoodNotesProposal
from my_pa.application.goodnotes_occurrences import (
    GoodNotesOccurrenceReconciler,
    OccurrenceReconcileBusyError,
    _context_anchor,
)
from my_pa.application.goodnotes_semantics import fingerprint_proposal
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.common.identifiers import IdKind
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
    GoodNotesNoteOccurrence,
    GoodNotesNoteRevision,
    GoodNotesPage,
    GoodNotesPagePosition,
    GoodNotesPageVersion,
    GoodNotesRunNoteChange,
    GoodNotesSourceSnapshot,
    issue_stable_id,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.goodnotes import PostgresGoodNotesRepository
from my_pa.infrastructure.persistence.goodnotes_semantics import SqlGoodNotesSemanticRepository

pytestmark = pytest.mark.database
ROOT = Path(__file__).resolve().parents[2]
DATABASE = "my_pa_goodnotes_occurrence_reconcile_test"
WHEN = datetime(2026, 8, 16, 21, 0, tzinfo=UTC)
LATER = WHEN + timedelta(hours=1)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
B = "prn_bbbbbbbbbbbbbbbbbbbbbbbb"
DIGEST = hashlib.sha256(b"synthetic-goodnotes-occurrence-page").hexdigest()
FINGERPRINT = "c" * 64
CROP = "d" * 64
SHARED_RUN = issue_stable_id("gnrun", "shared-occurrence-run")


def administer(engine: Engine, *statements: Executable) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)')
    variable = f"{ENV_PREFIX}DATABASE_URL"
    previous = os.environ.get(variable)
    try:
        administer(maintenance, drop, text(f'CREATE DATABASE "{DATABASE}"'))
        url = configured.set(database=DATABASE).render_as_string(hide_password=False)
        os.environ[variable] = url
        command.upgrade(Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO()), "head")
        built = create_database_engine(url)
        yield built
        built.dispose()
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        administer(maintenance, drop)
        maintenance.dispose()


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


def _run(principal_id: str, token: str, *, run_id: str | None = None) -> GoodNotesIngestionRun:
    request_id = f"req-{principal_id[-4:]}-{token}"
    return GoodNotesIngestionRun(
        run_id=run_id or issue_stable_id("gnrun", principal_id, token),
        principal_id=principal_id,
        source_root_id="icloud-goodnotes",
        trigger_type=GoodNotesIngestionTrigger.MANUAL,
        request_id=request_id,
        idempotency_key=request_id,
        request_fingerprint=FINGERPRINT,
        started_at=WHEN,
        status=GoodNotesIngestionStatus.RUNNING,
    )


def _plant(
    repository: PostgresGoodNotesRepository,
    principal_id: str,
    token: str,
    *,
    run_id: str | None = None,
) -> tuple[str, str, str, str]:
    notebook = repository.store_notebook(_notebook(principal_id, token))
    logical = repository.store_logical_page(
        GoodNotesLogicalPage(
            logical_page_id=issue_stable_id("gnlp", principal_id, token),
            principal_id=principal_id,
            notebook_id=notebook.notebook_id,
            created_at=WHEN,
            last_seen_at=WHEN,
            identity_status=GoodNotesIdentityStatus.ACTIVE,
        )
    )
    run = repository.create_run(_run(principal_id, token, run_id=run_id))
    object_suffix = hashlib.sha256(f"{principal_id}:{token}:object".encode()).hexdigest()[:24]
    source_object_id = f"obj_{object_suffix}"
    snapshot = repository.store_snapshot(
        GoodNotesSourceSnapshot(
            snapshot_id=issue_stable_id("gnsnap", principal_id, token),
            principal_id=principal_id,
            notebook_id=notebook.notebook_id,
            source_object_id=source_object_id,
            observed_path=f"Inbox/{token}.pdf",
            raw_sha256=hashlib.sha256(f"{principal_id}:{token}".encode()).hexdigest(),
            size_bytes=32,
            page_count=1,
            observed_at=WHEN,
            settled_at=WHEN,
            run_id=run.run_id,
        )
    )
    page = GoodNotesPage(
        page_id=issue_stable_id("gnpg", principal_id, token),
        principal_id=principal_id,
        source_id="src_aaaaaaaaaaaaaaaaaaaaaaaa",
        source_object_id=source_object_id,
        page_number=1,
    )
    version = repository.store_page_version_render(
        page=page,
        version=GoodNotesPageVersion(
            page_version_id=issue_stable_id("gnver", principal_id, token),
            page_id=page.page_id,
            source_version_id="ver_aaaaaaaaaaaaaaaaaaaaaaaa",
            content_sha256=DIGEST,
            observed_at=WHEN,
            logical_page_id=logical.logical_page_id,
            renderer_name="synthetic",
            renderer_version="1",
            render_profile_version="v1",
        ),
    )
    repository.store_page_position(
        GoodNotesPagePosition(
            principal_id=principal_id,
            snapshot_id=snapshot.snapshot_id,
            page_number=1,
            logical_page_id=logical.logical_page_id,
            created_at=WHEN,
            match_method=GoodNotesMatchMethod.ORDINAL_WEAK,
            page_version_id=version.page_version_id,
        )
    )
    return run.run_id, version.page_version_id, notebook.notebook_id, logical.logical_page_id


def _segment(
    *,
    x_min: float,
    transcription: str,
    crop_sha256: str | None = None,
    kind: str = "NOTE_UNIT",
) -> dict[str, object]:
    values: dict[str, object] = {
        "kind": kind,
        "geometry": {"x_min": x_min, "y_min": 0.2, "width": 0.2, "height": 0.1},
        "transcription": transcription,
        "primary_class": "MEETING",
    }
    if crop_sha256 is not None:
        values["crop_sha256"] = crop_sha256
    return values


def _propose(
    semantics: SqlGoodNotesSemanticRepository,
    *,
    principal_id: str,
    run_id: str,
    page_version_id: str,
    key: str,
    segments: tuple[dict[str, object], ...],
) -> None:
    command = SubmitGoodNotesProposal(
        run_id=run_id,
        page_version_id=page_version_id,
        content_sha256=DIGEST,
        schema_version="note-unit.v1",
        analyzer_name="synthetic",
        analyzer_version="1",
        idempotency_key=key,
        segments=segments,
    )
    fingerprint, payload_digest, body = fingerprint_proposal(command)
    semantics.submit_proposal(
        principal_id=principal_id,
        run_id=run_id,
        page_version_id=page_version_id,
        content_sha256=DIGEST,
        schema_version=command.schema_version,
        analyzer_name=command.analyzer_name,
        analyzer_version=command.analyzer_version,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        payload_sha256=payload_digest,
        payload=body,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        request_id=key,
        audit_id=issue_identifier(IdKind.AUDIT),
        created_at=WHEN,
    )


def _counts(connection: object, principal_id: str) -> tuple[int, int]:
    notes = int(
        connection.execute(  # type: ignore[union-attr]
            text("SELECT count(*) FROM knowledge.goodnotes_notes WHERE principal_id = :principal"),
            {"principal": principal_id},
        ).scalar_one()
    )
    changes = int(
        connection.execute(  # type: ignore[union-attr]
            text(
                "SELECT count(*) FROM knowledge.goodnotes_run_note_changes "
                "WHERE principal_id = :principal"
            ),
            {"principal": principal_id},
        ).scalar_one()
    )
    return notes, changes


def test_two_principals_same_run_id_string_do_not_leak(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        run_a, page_a, _, _ = _plant(lineage, A, "iso-a", run_id=SHARED_RUN)
        run_b, page_b, _, _ = _plant(lineage, B, "iso-b", run_id=SHARED_RUN)
        assert run_a == run_b == SHARED_RUN
        _propose(
            semantics,
            principal_id=A,
            run_id=run_a,
            page_version_id=page_a,
            key="iso-a",
            segments=(_segment(x_min=0.1, transcription="alpha note"),),
        )
        _propose(
            semantics,
            principal_id=B,
            run_id=run_b,
            page_version_id=page_b,
            key="iso-b",
            segments=(_segment(x_min=0.1, transcription="beta note"),),
        )
        reconciler = GoodNotesOccurrenceReconciler()
        result_a = reconciler.reconcile(A, run_a, repository=lineage, clock=lambda: LATER)
        result_b = reconciler.reconcile(B, run_b, repository=lineage, clock=lambda: LATER)
        assert result_a.changes[0].change_state is GoodNotesNoteChangeState.NEW
        assert result_b.changes[0].change_state is GoodNotesNoteChangeState.NEW
        assert lineage.run_note_changes(B, run_a)[0].note_id != result_a.changes[0].note_id
        assert lineage.note(B, result_a.changes[0].note_id) is None
        assert lineage.note(A, result_b.changes[0].note_id) is None
        assert lineage.occurrence(B, result_a.changes[0].occurrence_id) is None
        with pytest.raises(ValueError, match="no stored GoodNotes ingestion run"):
            reconciler.reconcile(
                B, issue_stable_id("gnrun", "missing-run"), repository=lineage, clock=lambda: LATER
            )


def test_crash_before_commit_writes_nothing(engine: Engine) -> None:
    class Boom(PostgresGoodNotesRepository):
        def store_run_note_change(self, change: GoodNotesRunNoteChange) -> GoodNotesRunNoteChange:
            raise RuntimeError("crash-before-commit")

    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        run_id, page_id, _, _ = _plant(lineage, A, "crash")
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="crash",
            segments=(_segment(x_min=0.1, transcription="do not persist"),),
        )

    before_notes, before_changes = 0, 0
    with engine.begin() as connection:
        before_notes, before_changes = _counts(connection, A)

    with pytest.raises(RuntimeError, match="crash-before-commit"), engine.begin() as connection:
        GoodNotesOccurrenceReconciler().reconcile(
            A, run_id, repository=Boom(connection), clock=lambda: LATER
        )

    with engine.begin() as connection:
        notes, changes = _counts(connection, A)
        assert notes == before_notes
        assert changes == before_changes
        repository = PostgresGoodNotesRepository(connection)
        assert repository.run_note_changes(A, run_id) == ()


def test_success_then_duplicate_request_replays_the_same_change_ids(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        run_id, page_id, _, _ = _plant(lineage, A, "replay")
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="replay",
            segments=(_segment(x_min=0.1, transcription="same note"),),
        )
        reconciler = GoodNotesOccurrenceReconciler()
        first = reconciler.reconcile(A, run_id, repository=lineage, clock=lambda: LATER)
        assert [item.change_state for item in first.changes] == [GoodNotesNoteChangeState.NEW]
        notes_after_first, changes_after_first = _counts(connection, A)

    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        second = GoodNotesOccurrenceReconciler().reconcile(
            A, run_id, repository=lineage, clock=lambda: LATER
        )
        assert second.replayed is True
        assert [item.change_id for item in second.changes] == [
            item.change_id for item in first.changes
        ]
        assert [item.change_state for item in second.changes] == [GoodNotesNoteChangeState.NEW]
        notes_after_second, changes_after_second = _counts(connection, A)
        assert notes_after_second == notes_after_first
        assert changes_after_second == changes_after_first


def test_overlapping_reconciles_busy_or_serialize_without_duplicate_new(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        run_id, page_id, _, _ = _plant(lineage, A, "overlap")
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="overlap",
            segments=(_segment(x_min=0.1, transcription="one winner"),),
        )

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        with engine.connect() as connection:
            trans = connection.begin()
            try:
                barrier.wait(timeout=10)
                try:
                    GoodNotesOccurrenceReconciler().reconcile(
                        A,
                        run_id,
                        repository=PostgresGoodNotesRepository(connection),
                        clock=lambda: LATER,
                    )
                    with lock:
                        outcomes.append("ok")
                    trans.commit()
                except OccurrenceReconcileBusyError:
                    with lock:
                        outcomes.append("busy")
                    trans.rollback()
            except Exception:
                trans.rollback()
                raise

    first = threading.Thread(target=worker)
    second = threading.Thread(target=worker)
    first.start()
    second.start()
    first.join()
    second.join()
    assert "ok" in outcomes
    assert outcomes.count("busy") == 1 or outcomes.count("ok") == 2
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        changes = repository.run_note_changes(A, run_id)
        assert len(changes) == 1
        assert changes[0].change_state is GoodNotesNoteChangeState.NEW
        notes, change_count = _counts(connection, A)
        assert change_count >= 1
        assert notes >= 1


def test_ambiguous_does_not_insert_a_silent_new_pick(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        run_id, page_id, notebook_id, logical_id = _plant(lineage, A, "ambiguous")
        note = lineage.store_note(
            GoodNotesNote(
                note_id=issue_stable_id("gnnt", A, "ambiguous"),
                principal_id=A,
                notebook_id=notebook_id,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
            )
        )
        first = lineage.store_occurrence(
            GoodNotesNoteOccurrence(
                occurrence_id=issue_stable_id("gnocc", A, "ambiguous-one"),
                principal_id=A,
                note_id=note.note_id,
                logical_page_id=logical_id,
                x_min=0.10,
                y_min=0.2,
                width=0.2,
                height=0.1,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
                crop_sha256=CROP,
            )
        )
        second = lineage.store_occurrence(
            GoodNotesNoteOccurrence(
                occurrence_id=issue_stable_id("gnocc", A, "ambiguous-two"),
                principal_id=A,
                note_id=note.note_id,
                logical_page_id=logical_id,
                x_min=0.50,
                y_min=0.2,
                width=0.2,
                height=0.1,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
                crop_sha256=CROP,
            )
        )
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="ambiguous",
            segments=(
                _segment(x_min=0.12, transcription="one", crop_sha256=CROP),
                _segment(x_min=0.52, transcription="two", crop_sha256=CROP),
            ),
        )
        notes_before, _ = _counts(connection, A)
        result = GoodNotesOccurrenceReconciler().reconcile(
            A, run_id, repository=lineage, clock=lambda: LATER
        )
        states = {item.change_state for item in result.changes}
        assert GoodNotesNoteChangeState.NEW not in states
        assert states == {GoodNotesNoteChangeState.AMBIGUOUS}
        assert {item.occurrence_id for item in result.changes} == {
            first.occurrence_id,
            second.occurrence_id,
        }
        notes_after, _ = _counts(connection, A)
        assert notes_after == notes_before
        assert lineage.occurrence(A, first.occurrence_id) is not None
        stored = lineage.occurrence(A, first.occurrence_id)
        assert stored is not None
        assert stored.identity_status is GoodNotesIdentityStatus.AMBIGUOUS


def test_missing_geometry_fails_closed_without_partial_writes(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        run_id, page_id, _, _ = _plant(lineage, A, "bad-geometry")
        semantics.submit_proposal(
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            content_sha256=DIGEST,
            schema_version="note-unit.v1",
            analyzer_name="synthetic",
            analyzer_version="1",
            idempotency_key="bad-geometry",
            request_fingerprint="e" * 64,
            payload_sha256="f" * 64,
            payload={"segments": [{"kind": "NOTE_UNIT", "transcription": "no box"}]},
            correlation_id=issue_identifier(IdKind.CORRELATION),
            request_id="bad-geometry",
            audit_id=issue_identifier(IdKind.AUDIT),
            created_at=WHEN,
        )
        notes_before, changes_before = _counts(connection, A)
        with pytest.raises(ValueError, match="missing required geometry"):
            GoodNotesOccurrenceReconciler().reconcile(
                A, run_id, repository=lineage, clock=lambda: LATER
            )
        notes_after, changes_after = _counts(connection, A)
        assert notes_after == notes_before
        assert changes_after == changes_before


def test_unique_visual_match_with_new_transcription_is_revised(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        run_id, page_id, notebook_id, logical_id = _plant(lineage, A, "revised")
        note = lineage.store_note(
            GoodNotesNote(
                note_id=issue_stable_id("gnnt", A, "revised"),
                principal_id=A,
                notebook_id=notebook_id,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
            )
        )
        occurrence = lineage.store_occurrence(
            GoodNotesNoteOccurrence(
                occurrence_id=issue_stable_id("gnocc", A, "revised"),
                principal_id=A,
                note_id=note.note_id,
                logical_page_id=logical_id,
                x_min=0.1,
                y_min=0.2,
                width=0.2,
                height=0.1,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
            )
        )
        original = lineage.store_revision(
            GoodNotesNoteRevision(
                revision_id=issue_stable_id("gnrev", A, "revised-first"),
                principal_id=A,
                note_id=note.note_id,
                schema_version="note-unit.v1",
                analyzer_name="synthetic",
                analyzer_version="1",
                transcription="follow up Tuesday",
                created_at=WHEN,
                occurrence_id=occurrence.occurrence_id,
            )
        )
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="revised",
            segments=(_segment(x_min=0.1, transcription="follow up Thursday"),),
        )
        result = GoodNotesOccurrenceReconciler().reconcile(
            A, run_id, repository=lineage, clock=lambda: LATER
        )
        assert [item.change_state for item in result.changes] == [GoodNotesNoteChangeState.REVISED]
        assert result.changes[0].occurrence_id == occurrence.occurrence_id
        latest = lineage.latest_revision_for_occurrence(A, occurrence.occurrence_id)
        assert latest is not None
        assert latest.transcription == "follow up Thursday"
        assert latest.supersedes_revision_id == original.revision_id
        assert lineage.revision(A, original.revision_id) is not None
        assert lineage.revision(A, original.revision_id).transcription == "follow up Tuesday"


def test_new_occurrence_does_not_reuse_note_by_page_wide_context_hash(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        run_id, page_id, notebook_id, logical_id = _plant(lineage, A, "append")
        heading = _segment(x_min=0.4, transcription="synthetic heading", kind="SOURCE_CONTEXT")
        existing_unit = _segment(x_min=0.1, transcription="synthetic note", crop_sha256=CROP)
        appended = _segment(x_min=0.6, transcription="synthetic note", crop_sha256="e" * 64)
        note = lineage.store_note(
            GoodNotesNote(
                note_id=issue_stable_id("gnnt", A, "append"),
                principal_id=A,
                notebook_id=notebook_id,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
            )
        )
        existing = lineage.store_occurrence(
            GoodNotesNoteOccurrence(
                occurrence_id=issue_stable_id("gnocc", A, "append"),
                principal_id=A,
                note_id=note.note_id,
                logical_page_id=logical_id,
                x_min=0.1,
                y_min=0.2,
                width=0.2,
                height=0.1,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
                crop_sha256=CROP,
                context_anchor_sha256=_context_anchor((heading, existing_unit, appended)),
            )
        )
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="append",
            segments=(heading, existing_unit, appended),
        )
        notes_before, _ = _counts(connection, A)
        result = GoodNotesOccurrenceReconciler().reconcile(
            A, run_id, repository=lineage, clock=lambda: LATER
        )
        notes_after, _ = _counts(connection, A)
        assert notes_after == notes_before + 1
        notebook_notes = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM knowledge.goodnotes_notes "
                    "WHERE principal_id = :principal AND notebook_id = :notebook"
                ),
                {"principal": A, "notebook": notebook_id},
            ).scalar_one()
        )
        assert notebook_notes == 2
        new_changes = [
            item for item in result.changes if item.change_state is GoodNotesNoteChangeState.NEW
        ]
        assert len(new_changes) == 1
        assert new_changes[0].note_id != note.note_id
        assert new_changes[0].occurrence_id != existing.occurrence_id
        stored = lineage.occurrence(A, new_changes[0].occurrence_id)
        assert stored is not None
        assert stored.note_id != note.note_id
        assert stored.note_id == new_changes[0].note_id
        paired = [item for item in result.changes if item.occurrence_id == existing.occurrence_id]
        assert len(paired) == 1
        assert paired[0].change_state in {
            GoodNotesNoteChangeState.UNCHANGED,
            GoodNotesNoteChangeState.REVISED,
        }
        assert paired[0].note_id == note.note_id
