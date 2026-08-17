"""Disposable PostgreSQL proof for GoodNotes operator corrections and integrity."""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.sql import Executable

from my_pa.application.goodnotes_corrections import (
    OPERATOR_CORRECTION_ANALYZER,
    GoodNotesCorrectionService,
)
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.goodnotes.models import (
    GoodNotesIdentityStatus,
    GoodNotesIngestionRun,
    GoodNotesIngestionStatus,
    GoodNotesIngestionTrigger,
    GoodNotesLogicalPage,
    GoodNotesNote,
    GoodNotesNotebook,
    GoodNotesNoteClass,
    GoodNotesNoteLinkKind,
    GoodNotesNoteOccurrence,
    GoodNotesNoteRevision,
    issue_stable_id,
)
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.goodnotes import PostgresGoodNotesRepository

pytestmark = pytest.mark.database
ROOT = Path(__file__).resolve().parents[2]
DATABASE = "my_pa_goodnotes_corrections_test"
WHEN = datetime(2026, 8, 16, 23, 0, tzinfo=UTC)
LATER = WHEN + timedelta(hours=1)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
B = "prn_bbbbbbbbbbbbbbbbbbbbbbbb"
FINGERPRINT = "c" * 64


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


def _parents(
    repository: PostgresGoodNotesRepository, principal_id: str, token: str
) -> tuple[GoodNotesNotebook, GoodNotesLogicalPage, GoodNotesIngestionRun]:
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
    run = repository.create_run(_run(principal_id, token))
    return notebook, logical, run


def _note(principal_id: str, notebook_id: str, token: str) -> GoodNotesNote:
    return GoodNotesNote(
        note_id=issue_stable_id("gnnt", principal_id, token),
        principal_id=principal_id,
        notebook_id=notebook_id,
        identity_status=GoodNotesIdentityStatus.ACTIVE,
        created_at=WHEN,
        last_seen_at=WHEN,
        primary_class=GoodNotesNoteClass.MEETING,
    )


def _occurrence(
    principal_id: str,
    note_id: str,
    logical_page_id: str,
    token: str,
    *,
    x_min: float,
) -> GoodNotesNoteOccurrence:
    return GoodNotesNoteOccurrence(
        occurrence_id=issue_stable_id("gnocc", principal_id, token),
        principal_id=principal_id,
        note_id=note_id,
        logical_page_id=logical_page_id,
        x_min=x_min,
        y_min=0.2,
        width=0.2,
        height=0.1,
        identity_status=GoodNotesIdentityStatus.ACTIVE,
        created_at=WHEN,
        last_seen_at=WHEN,
        crop_sha256="a" * 64,
    )


def _revision(
    principal_id: str, note_id: str, occurrence_id: str, token: str
) -> GoodNotesNoteRevision:
    return GoodNotesNoteRevision(
        revision_id=issue_stable_id("gnrev", principal_id, token),
        principal_id=principal_id,
        note_id=note_id,
        schema_version="note-unit.v1",
        analyzer_name="synthetic",
        analyzer_version="1",
        transcription="synthetic note",
        created_at=WHEN,
        occurrence_id=occurrence_id,
        primary_class=GoodNotesNoteClass.MEETING,
    )


def test_correction_on_principal_a_is_invisible_to_b(engine: Engine) -> None:
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        notebook_a, logical_a, _ = _parents(repository, A, "shared-correction")
        notebook_b, logical_b, _ = _parents(repository, B, "shared-correction")
        occurrence_id = issue_stable_id("gnocc", "shared", "correction")
        note_a = repository.store_note(_note(A, notebook_a.notebook_id, "shared-correction"))
        note_b = repository.store_note(_note(B, notebook_b.notebook_id, "shared-correction"))
        occurrence_a = repository.store_occurrence(
            GoodNotesNoteOccurrence(
                occurrence_id=occurrence_id,
                principal_id=A,
                note_id=note_a.note_id,
                logical_page_id=logical_a.logical_page_id,
                x_min=0.1,
                y_min=0.2,
                width=0.2,
                height=0.1,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
            )
        )
        occurrence_b = repository.store_occurrence(
            GoodNotesNoteOccurrence(
                occurrence_id=occurrence_id,
                principal_id=B,
                note_id=note_b.note_id,
                logical_page_id=logical_b.logical_page_id,
                x_min=0.1,
                y_min=0.2,
                width=0.2,
                height=0.1,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
            )
        )
        original_a = repository.store_revision(
            _revision(A, note_a.note_id, occurrence_a.occurrence_id, "shared-a")
        )
        original_b = repository.store_revision(
            _revision(B, note_b.note_id, occurrence_b.occurrence_id, "shared-b")
        )
        result = GoodNotesCorrectionService().apply(
            A,
            occurrence_id,
            transcription="synthetic correction",
            repository=repository,
            clock=lambda: LATER,
        )
        assert result.revision.analyzer_name == OPERATOR_CORRECTION_ANALYZER
        assert repository.revision(B, result.revision.revision_id) is None
        latest_b = repository.latest_revision_for_occurrence(B, occurrence_id)
        assert latest_b is not None
        assert latest_b.revision_id == original_b.revision_id
        assert latest_b.transcription == "synthetic note"
        with pytest.raises(ValueError, match="no stored GoodNotes note occurrence"):
            GoodNotesCorrectionService().apply(
                B,
                issue_stable_id("gnocc", "missing"),
                transcription="synthetic correction",
                repository=repository,
                clock=lambda: LATER,
            )
        assert repository.revision(A, original_a.revision_id) is not None
        assert repository.revision(A, original_a.revision_id).transcription == "synthetic note"


def test_prior_revision_row_still_present_after_correction(engine: Engine) -> None:
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        notebook, logical, _ = _parents(repository, A, "keep-prior")
        note = repository.store_note(_note(A, notebook.notebook_id, "keep-prior"))
        occurrence = repository.store_occurrence(
            _occurrence(A, note.note_id, logical.logical_page_id, "keep-prior", x_min=0.1)
        )
        original = repository.store_revision(
            _revision(A, note.note_id, occurrence.occurrence_id, "keep-prior")
        )
        geometry_before = occurrence.geometry_key
        crop_before = occurrence.crop_sha256
        target = repository.store_note(_note(A, notebook.notebook_id, "keep-prior-target"))
        result = GoodNotesCorrectionService().apply(
            A,
            occurrence.occurrence_id,
            transcription="synthetic correction",
            repository=repository,
            link_kind=GoodNotesNoteLinkKind.NOTE_TO_NOTE,
            target_note_id=target.note_id,
            clock=lambda: LATER,
        )
        stored_original = repository.revision(A, original.revision_id)
        assert stored_original is not None
        assert stored_original.transcription == "synthetic note"
        assert stored_original.analyzer_name == "synthetic"
        latest = repository.latest_revision_for_occurrence(A, occurrence.occurrence_id)
        assert latest is not None
        assert latest.revision_id == result.revision.revision_id
        assert latest.supersedes_revision_id == original.revision_id
        assert latest.transcription == "synthetic correction"
        unchanged = repository.occurrence(A, occurrence.occurrence_id)
        assert unchanged is not None
        assert unchanged.geometry_key == geometry_before
        assert unchanged.crop_sha256 == crop_before
        assert result.link is not None
        assert repository.note_link(A, result.link.link_id) is not None
        assert repository.note_link(B, result.link.link_id) is None


def test_integrity_metric_is_zero_on_the_unique_geometry_path(engine: Engine) -> None:
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        notebook, logical, _ = _parents(repository, A, "unique-geometry")
        note = repository.store_note(_note(A, notebook.notebook_id, "unique-geometry"))
        left = repository.store_occurrence(
            _occurrence(A, note.note_id, logical.logical_page_id, "left", x_min=0.1)
        )
        right = repository.store_occurrence(
            _occurrence(A, note.note_id, logical.logical_page_id, "right", x_min=0.5)
        )
        assert left.geometry_key != right.geometry_key
        assert repository.duplicate_active_occurrence_count(A) == 0
        assert repository.duplicate_active_occurrence_count(B) == 0
        repository.store_revision(_revision(A, note.note_id, left.occurrence_id, "left"))
        GoodNotesCorrectionService().apply(
            A,
            left.occurrence_id,
            transcription="synthetic correction",
            repository=repository,
            clock=lambda: LATER,
        )
        assert repository.duplicate_active_occurrence_count(A) == 0
        stored = repository.occurrence(A, left.occurrence_id)
        assert stored is not None
        assert stored.geometry_key == left.geometry_key
