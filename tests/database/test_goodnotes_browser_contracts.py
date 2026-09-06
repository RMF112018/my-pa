"""Disposable PostgreSQL proof for GoodNotes browser list/read/search/correct."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.sql import Executable

from my_pa.application.commands import (
    CorrectGoodNotes,
    ListGoodNotesNotebooks,
    ListGoodNotesPages,
    ListGoodNotesRuns,
    SearchGoodNotes,
)
from my_pa.application.errors import NotFoundError
from my_pa.application.goodnotes_browse import (
    correct,
    list_notebooks,
    list_pages,
    list_runs,
    search,
)
from my_pa.domain.goodnotes.models import (
    GoodNotesIdentityStatus,
    GoodNotesIngestionRun,
    GoodNotesIngestionStatus,
    GoodNotesIngestionTrigger,
    GoodNotesLogicalPage,
    GoodNotesMatchMethod,
    GoodNotesNote,
    GoodNotesNotebook,
    GoodNotesNoteClass,
    GoodNotesNoteOccurrence,
    GoodNotesNoteRevision,
    GoodNotesPage,
    GoodNotesPagePosition,
    GoodNotesPageVersion,
    GoodNotesSourceSnapshot,
    issue_stable_id,
)
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.infrastructure.persistence.goodnotes_durable_note import PostgresDurableNoteStore

pytestmark = pytest.mark.database
ROOT = Path(__file__).resolve().parents[2]
DATABASE = "my_pa_goodnotes_browser_contracts_test"
WHEN = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
B = "prn_bbbbbbbbbbbbbbbbbbbbbbbb"
C = "prn_cccccccccccccccccccccccc"
FINGERPRINT = "c" * 64


def _oid(prefix: str, principal_id: str, token: str) -> str:
    return f"{prefix}_{hashlib.sha256(f'{principal_id}:{token}'.encode()).hexdigest()[:24]}"


class _Auth:
    def __init__(self, principal_id: str) -> None:
        self.principal = Principal(
            principal_id=principal_id, kind=PrincipalKind.OPERATOR, authenticated=True
        )


class _Uow:
    def __init__(self, store: PostgresDurableNoteStore) -> None:
        self.goodnotes_durable_notes = store


def administer(engine: Engine, *statements: Executable) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)


def _notebook(principal_id: str, token: str, *, observed: datetime) -> GoodNotesNotebook:
    return GoodNotesNotebook(
        notebook_id=issue_stable_id("gnnb", principal_id, token),
        principal_id=principal_id,
        source_root_id="icloud-goodnotes",
        identity_status=GoodNotesIdentityStatus.ACTIVE,
        created_at=WHEN,
        last_observed_at=observed,
        label=token,
    )


def _run(principal_id: str, token: str, *, started: datetime) -> GoodNotesIngestionRun:
    request_id = f"req-{principal_id[-4:]}-{token}"
    return GoodNotesIngestionRun(
        run_id=issue_stable_id("gnrun", principal_id, token),
        principal_id=principal_id,
        source_root_id="icloud-goodnotes",
        trigger_type=GoodNotesIngestionTrigger.MANUAL,
        request_id=request_id,
        idempotency_key=request_id,
        request_fingerprint=FINGERPRINT,
        started_at=started,
        status=GoodNotesIngestionStatus.SUCCEEDED,
        ended_at=started + timedelta(minutes=1),
    )


def _plant_page(
    repository: PostgresDurableNoteStore,
    principal_id: str,
    token: str,
    *,
    observed: datetime,
    notebook: GoodNotesNotebook | None = None,
    logical: GoodNotesLogicalPage | None = None,
    page_number: int = 1,
) -> tuple[GoodNotesNotebook, GoodNotesLogicalPage, GoodNotesIngestionRun, GoodNotesPageVersion]:
    if notebook is None:
        notebook = repository.store_notebook(_notebook(principal_id, token, observed=observed))
    if logical is None:
        logical = repository.store_logical_page(
            GoodNotesLogicalPage(
                logical_page_id=issue_stable_id("gnlp", principal_id, token),
                principal_id=principal_id,
                notebook_id=notebook.notebook_id,
                created_at=WHEN,
                last_seen_at=observed,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
            )
        )
    run = repository.create_run(_run(principal_id, token, started=observed))
    snapshot = repository.store_snapshot(
        GoodNotesSourceSnapshot(
            snapshot_id=issue_stable_id("gnsnap", principal_id, token),
            principal_id=principal_id,
            notebook_id=notebook.notebook_id,
            source_object_id=_oid("obj", principal_id, token),
            observed_path="synthetic.pdf",
            raw_sha256=hashlib.sha256(token.encode()).hexdigest(),
            size_bytes=32,
            page_count=1,
            observed_at=observed,
            settled_at=observed,
            run_id=run.run_id,
        )
    )
    page = GoodNotesPage(
        page_id=issue_stable_id("gnpg", principal_id, token),
        principal_id=principal_id,
        source_id=_oid("src", principal_id, token),
        source_object_id=_oid("obj", principal_id, token),
        page_number=page_number,
    )
    version = repository.store_page_version_render(
        page=page,
        version=GoodNotesPageVersion(
            page_version_id=issue_stable_id("gnver", principal_id, token),
            page_id=page.page_id,
            source_version_id=_oid("ver", principal_id, token),
            content_sha256=hashlib.sha256(f"{principal_id}:{token}".encode()).hexdigest(),
            observed_at=observed,
            logical_page_id=logical.logical_page_id,
        ),
    )
    repository.store_page_position(
        GoodNotesPagePosition(
            principal_id=principal_id,
            snapshot_id=snapshot.snapshot_id,
            page_number=page_number,
            logical_page_id=logical.logical_page_id,
            created_at=observed,
            match_method=GoodNotesMatchMethod.ORDINAL_WEAK,
            page_version_id=version.page_version_id,
        )
    )
    return notebook, logical, run, version


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
    page_version_id: str,
    run_id: str,
) -> GoodNotesNoteOccurrence:
    return GoodNotesNoteOccurrence(
        occurrence_id=issue_stable_id("gnocc", principal_id, token),
        principal_id=principal_id,
        note_id=note_id,
        logical_page_id=logical_page_id,
        x_min=0.1,
        y_min=0.2,
        width=0.2,
        height=0.1,
        identity_status=GoodNotesIdentityStatus.ACTIVE,
        created_at=WHEN,
        last_seen_at=WHEN,
        page_version_id=page_version_id,
        run_id=run_id,
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


def test_browser_lists_are_principal_bound_ordered_and_paginated(engine: Engine) -> None:
    with engine.begin() as connection:
        store = PostgresDurableNoteStore(connection)
        first = store.store_notebook(_notebook(A, "alpha-book", observed=WHEN))
        second = store.store_notebook(_notebook(A, "bravo-book", observed=WHEN + HOUR))
        third = store.store_notebook(_notebook(A, "charlie-book", observed=WHEN + HOUR * 2))
        store.store_notebook(_notebook(B, "alpha-book", observed=WHEN + HOUR * 3))
        uow = _Uow(store)
        empty = list_notebooks(uow, _Auth(C), ListGoodNotesNotebooks())
        assert empty == {"notebooks": []}
        page = list_notebooks(uow, _Auth(A), ListGoodNotesNotebooks(page_size=1))
        assert [row["notebook_id"] for row in page["notebooks"]] == [third.notebook_id]
        assert page["notebooks"][0]["title"] == "charlie-book"
        assert page["notebooks"][0]["liveness"] == "unknown"
        assert "next_cursor" in page
        next_page = list_notebooks(
            uow, _Auth(A), ListGoodNotesNotebooks(page_size=1, cursor=page["next_cursor"])
        )
        assert [row["notebook_id"] for row in next_page["notebooks"]] == [second.notebook_id]
        theirs = list_notebooks(uow, _Auth(B), ListGoodNotesNotebooks())
        assert [row["title"] for row in theirs["notebooks"]] == ["alpha-book"]
        assert list_pages(uow, _Auth(B), ListGoodNotesPages(notebook_id=first.notebook_id)) == {
            "pages": []
        }
        hits = search(uow, _Auth(A), SearchGoodNotes(query="alpha-book"))
        assert {hit["notebook_id"] for hit in hits["hits"]} == {first.notebook_id}
        assert search(uow, _Auth(B), SearchGoodNotes(query=first.notebook_id))["hits"] == []


def test_pages_mark_latest_and_runs_stay_principal_bound(engine: Engine) -> None:
    with engine.begin() as connection:
        store = PostgresDurableNoteStore(connection)
        notebook, logical, older_run, older = _plant_page(store, A, "page-old", observed=WHEN)
        _, _, newer_run, newer = _plant_page(
            store,
            A,
            "page-new",
            observed=WHEN + HOUR,
            notebook=notebook,
            logical=logical,
            page_number=1,
        )
        _plant_page(store, B, "page-other", observed=WHEN + HOUR * 2)
        uow = _Uow(store)
        pages = list_pages(uow, _Auth(A), ListGoodNotesPages(notebook_id=notebook.notebook_id))
        by_id = {row["page_version_id"]: row for row in pages["pages"]}
        assert by_id[newer.page_version_id]["is_latest"] is True
        assert by_id[older.page_version_id]["is_latest"] is False
        assert by_id[newer.page_version_id]["run_id"] == newer_run.run_id
        runs = list_runs(uow, _Auth(A), ListGoodNotesRuns(notebook_id=notebook.notebook_id))
        assert [row["run_id"] for row in runs["runs"]] == [newer_run.run_id, older_run.run_id]
        assert all(row["state"] == GoodNotesIngestionStatus.SUCCEEDED.value for row in runs["runs"])
        other = list_runs(uow, _Auth(B), ListGoodNotesRuns())
        assert newer_run.run_id not in {row["run_id"] for row in other["runs"]}
        filtered = list_runs(
            uow,
            _Auth(A),
            ListGoodNotesRuns(page_version_id=newer.page_version_id),
        )
        assert [row["run_id"] for row in filtered["runs"]] == [newer_run.run_id]
        assert filtered["runs"][0]["page_version_id"] == newer.page_version_id


def test_interpretation_projects_proposal_and_occurrence_without_bodies(engine: Engine) -> None:
    with engine.begin() as connection:
        store = PostgresDurableNoteStore(connection)
        notebook, logical, run, version = _plant_page(store, A, "interp", observed=WHEN)
        store.store_semantic_proposal(
            A,
            run.run_id,
            version.page_version_id,
            schema_version="note-unit.v1",
            analyzer_name="synthetic",
            analyzer_version="1",
            payload={
                "segments": (
                    {
                        "kind": "NOTE_UNIT",
                        "geometry": {"x_min": 0.1, "y_min": 0.1, "width": 0.2, "height": 0.2},
                        "transcription": "must not appear",
                        "primary_class": "MEETING",
                    },
                ),
                "candidate_tags": [],
                "ranked_candidates": [],
                "confidence": 0.9,
            },
        )
        note = store.store_note(_note(A, notebook.notebook_id, "interp"))
        occurrence = store.store_occurrence(
            _occurrence(
                A,
                note.note_id,
                logical.logical_page_id,
                "interp",
                page_version_id=version.page_version_id,
                run_id=run.run_id,
            )
        )
        revision = store.store_revision(
            _revision(A, note.note_id, occurrence.occurrence_id, "interp")
        )
        items = store.browse_interpretation(A, run.run_id, version.page_version_id)
        assert store.browse_interpretation(B, run.run_id, version.page_version_id) == []
        dumped = repr(items)
        assert "must not appear" not in dumped
        assert "synthetic note" not in dumped
        assert any("proposal_id" in item and item["disposition"] is None for item in items)
        assert any(
            item.get("occurrence_id") == occurrence.occurrence_id
            and item.get("revision_id") == revision.revision_id
            for item in items
        )


def test_correct_appends_a_revision_invisible_to_the_other_principal(engine: Engine) -> None:
    with engine.begin() as connection:
        store = PostgresDurableNoteStore(connection)
        notebook, logical, run, version = _plant_page(store, A, "correct", observed=WHEN)
        note = store.store_note(_note(A, notebook.notebook_id, "correct"))
        occurrence = store.store_occurrence(
            _occurrence(
                A,
                note.note_id,
                logical.logical_page_id,
                "correct",
                page_version_id=version.page_version_id,
                run_id=run.run_id,
            )
        )
        original = store.store_revision(
            _revision(A, note.note_id, occurrence.occurrence_id, "correct")
        )
        uow = _Uow(store)
        result = correct(
            uow,
            _Auth(A),
            CorrectGoodNotes(
                occurrence_id=occurrence.occurrence_id, transcription="operator correction"
            ),
        )
        assert result["disposition"] == "canonical_revision_appended"
        assert result["prior_revision_id"] == original.revision_id
        assert result["replayed"] is False
        stored_original = store.revision(A, original.revision_id)
        assert stored_original is not None
        assert stored_original.transcription == "synthetic note"
        latest = store.latest_revision_for_occurrence(A, occurrence.occurrence_id)
        assert latest is not None
        assert latest.revision_id == result["revision_id"]
        assert latest.transcription == "operator correction"
        assert store.revision(B, result["revision_id"]) is None
        with pytest.raises(NotFoundError):
            correct(
                uow,
                _Auth(B),
                CorrectGoodNotes(
                    occurrence_id=occurrence.occurrence_id, transcription="operator correction"
                ),
            )


@pytest.fixture
def engine(db_engine: Engine) -> Engine:
    return db_engine
