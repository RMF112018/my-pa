"""Disposable PostgreSQL proof for GoodNotes lineage isolation and replay."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.sql import Executable

from my_pa.application.goodnotes_lineage import (
    GoodNotesLineageService,
    LineageReconcileRequest,
    ObservedNotebookFile,
)
from my_pa.domain.goodnotes.models import (
    GoodNotesIdentityStatus,
    GoodNotesIngestionRun,
    GoodNotesIngestionStatus,
    GoodNotesIngestionTrigger,
    GoodNotesLogicalPage,
    GoodNotesMatchMethod,
    GoodNotesNotebook,
    GoodNotesNotebookPath,
    GoodNotesPage,
    GoodNotesPagePosition,
    GoodNotesPageVersion,
    GoodNotesSourceSnapshot,
    SourcePage,
    issue_stable_id,
)
from my_pa.infrastructure.goodnotes.pdf import split_admitted_pdf
from my_pa.infrastructure.goodnotes.render import (
    MappedPageRenderer,
    RawRepresentationRenderer,
    production_page_renderer,
)
from my_pa.infrastructure.persistence.goodnotes import PostgresGoodNotesRepository
from tests.unit.vector_pdf import Rect, vector_pdf

pytestmark = pytest.mark.database
ROOT = Path(__file__).resolve().parents[2]
DATABASE = "my_pa_goodnotes_lineage_test"
WHEN = datetime(2026, 8, 16, 15, 0, tzinfo=UTC)
LATER = WHEN + timedelta(hours=1)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
B = "prn_bbbbbbbbbbbbbbbbbbbbbbbb"
DIGEST_ONE = "a" * 64
DIGEST_TWO = "b" * 64
FINGERPRINT_ONE = "c" * 64
FINGERPRINT_TWO = "d" * 64


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


def _run(principal_id: str, token: str, fingerprint: str) -> GoodNotesIngestionRun:
    request_id = f"req-{principal_id[-4:]}-{token}"
    return GoodNotesIngestionRun(
        run_id=issue_stable_id("gnrun", principal_id, token),
        principal_id=principal_id,
        source_root_id="icloud-goodnotes",
        trigger_type=GoodNotesIngestionTrigger.MANUAL,
        request_id=request_id,
        idempotency_key=request_id,
        request_fingerprint=fingerprint,
        started_at=WHEN,
        status=GoodNotesIngestionStatus.RUNNING,
    )


def test_cross_principal_isolation_and_path_history(engine: Engine) -> None:
    notebook_a = _notebook(A, "shared-name")
    notebook_b = GoodNotesNotebook(
        notebook_id=notebook_a.notebook_id,
        principal_id=B,
        source_root_id="icloud-goodnotes",
        identity_status=GoodNotesIdentityStatus.ACTIVE,
        created_at=WHEN,
        last_observed_at=WHEN,
        label="other",
    )
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        stored_a = repository.store_notebook(notebook_a)
        stored_b = repository.store_notebook(notebook_b)
        assert stored_a.notebook_id == stored_b.notebook_id
        fetched_a = repository.notebook(A, notebook_a.notebook_id)
        fetched_b = repository.notebook(B, notebook_a.notebook_id)
        assert fetched_a is not None and fetched_b is not None
        assert fetched_a.label == "shared-name"
        assert fetched_b.label == "other"
        first = repository.record_notebook_path(
            GoodNotesNotebookPath(
                principal_id=A,
                notebook_id=notebook_a.notebook_id,
                path="Inbox/alpha.pdf",
                first_seen_at=WHEN,
                last_seen_at=WHEN,
                is_current=True,
            )
        )
        renamed = repository.record_notebook_path(
            GoodNotesNotebookPath(
                principal_id=A,
                notebook_id=notebook_a.notebook_id,
                path="Archive/alpha.pdf",
                first_seen_at=LATER,
                last_seen_at=LATER,
                is_current=True,
            )
        )
        paths = repository.notebook_paths(A, notebook_a.notebook_id)
        assert {item.path for item in paths} == {first.path, renamed.path}
        assert sum(item.is_current for item in paths) == 1
        current = next(item for item in paths if item.is_current)
        assert current.path == "Archive/alpha.pdf"
        assert repository.notebook_paths(B, notebook_a.notebook_id) == ()


def test_exact_snapshot_replay_and_logical_page_positions(engine: Engine) -> None:
    notebook = _notebook(A, "replay")
    run = _run(A, "replay", FINGERPRINT_ONE)
    snapshot = GoodNotesSourceSnapshot(
        snapshot_id=issue_stable_id("gnsnap", A, "first"),
        principal_id=A,
        notebook_id=notebook.notebook_id,
        source_object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
        observed_path="Inbox/alpha.pdf",
        raw_sha256=DIGEST_ONE,
        size_bytes=32,
        page_count=2,
        observed_at=WHEN,
        settled_at=WHEN,
        run_id=run.run_id,
    )
    logical = GoodNotesLogicalPage(
        logical_page_id=issue_stable_id("gnlp", A, "cover"),
        principal_id=A,
        notebook_id=notebook.notebook_id,
        created_at=WHEN,
        last_seen_at=WHEN,
        identity_status=GoodNotesIdentityStatus.ACTIVE,
    )
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        repository.store_notebook(notebook)
        stored_run = repository.create_run(run)
        first = repository.store_snapshot(snapshot)
        replayed = repository.store_snapshot(
            GoodNotesSourceSnapshot(
                snapshot_id=issue_stable_id("gnsnap", A, "second-attempt"),
                principal_id=A,
                notebook_id=notebook.notebook_id,
                source_object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
                observed_path="Archive/alpha.pdf",
                raw_sha256=DIGEST_ONE,
                size_bytes=64,
                page_count=9,
                observed_at=LATER,
                settled_at=LATER,
                run_id=stored_run.run_id,
            )
        )
        assert replayed.snapshot_id == first.snapshot_id
        assert replayed.observed_path == "Inbox/alpha.pdf"
        assert replayed.size_bytes == 32
        later_run = repository.create_run(
            GoodNotesIngestionRun(
                run_id=issue_stable_id("gnrun", A, "later"),
                principal_id=A,
                source_root_id="icloud-goodnotes",
                trigger_type=GoodNotesIngestionTrigger.SCHEDULED,
                request_id="req-later",
                idempotency_key="req-later",
                request_fingerprint=DIGEST_TWO,
                started_at=LATER,
                status=GoodNotesIngestionStatus.RUNNING,
            )
        )
        second = repository.store_snapshot(
            GoodNotesSourceSnapshot(
                snapshot_id=issue_stable_id("gnsnap", A, "changed-bytes"),
                principal_id=A,
                notebook_id=notebook.notebook_id,
                source_object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
                observed_path="Archive/alpha.pdf",
                raw_sha256=DIGEST_TWO,
                size_bytes=40,
                page_count=2,
                observed_at=LATER,
                settled_at=LATER,
                run_id=later_run.run_id,
            )
        )
        assert second.snapshot_id != first.snapshot_id
        repository.store_logical_page(logical)
        first_position = repository.store_page_position(
            GoodNotesPagePosition(
                principal_id=A,
                snapshot_id=first.snapshot_id,
                page_number=2,
                logical_page_id=logical.logical_page_id,
                created_at=WHEN,
                match_method=GoodNotesMatchMethod.ORDINAL_WEAK,
            )
        )
        second_position = repository.store_page_position(
            GoodNotesPagePosition(
                principal_id=A,
                snapshot_id=second.snapshot_id,
                page_number=1,
                logical_page_id=logical.logical_page_id,
                created_at=LATER,
                match_method=GoodNotesMatchMethod.EXACT_NORMALIZED_RENDER,
                match_confidence=1.0,
            )
        )
        assert first_position.logical_page_id == second_position.logical_page_id
        assert first_position.page_number != second_position.page_number
        assert repository.snapshot(B, first.snapshot_id) is None
        assert repository.logical_page(B, logical.logical_page_id) is None


def test_page_version_render_identity_is_append_only(engine: Engine) -> None:
    notebook = _notebook(A, "immutable-render")
    logical = GoodNotesLogicalPage(
        logical_page_id=issue_stable_id("gnlp", A, "immutable-render"),
        principal_id=A,
        notebook_id=notebook.notebook_id,
        created_at=WHEN,
        last_seen_at=WHEN,
        identity_status=GoodNotesIdentityStatus.ACTIVE,
    )
    page = GoodNotesPage(
        page_id=issue_stable_id("gnpg", A, "immutable-render"),
        principal_id=A,
        source_id="src_929292929292929292929292",
        source_object_id="obj_929292929292929292929292",
        page_number=1,
    )
    version = GoodNotesPageVersion(
        page_version_id=issue_stable_id("gnver", A, "immutable-render"),
        page_id=page.page_id,
        source_version_id="ver_929292929292929292929292",
        content_sha256=DIGEST_ONE,
        observed_at=WHEN,
        logical_page_id=logical.logical_page_id,
        exact_render_sha256=DIGEST_ONE,
        normalized_render_sha256=DIGEST_ONE,
        renderer_name="synthetic",
        renderer_version="1",
        render_profile_version="test-v1",
    )
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        repository.store_notebook(notebook)
        repository.store_logical_page(logical)
        stored = repository.store_page_version_render(page=page, version=version)

        with pytest.raises(ValueError, match="page version identity collided"):
            repository.store_page_version_render(
                page=page,
                version=replace(version, exact_render_sha256=DIGEST_TWO),
            )

        unchanged = repository.page_version(A, version.page_version_id)
        assert unchanged == stored


def test_request_id_replay_and_fingerprint_conflict(engine: Engine) -> None:
    first = _run(A, "idempotent", FINGERPRINT_ONE)
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        stored = repository.create_run(first)
        replayed = repository.create_run(
            GoodNotesIngestionRun(
                run_id=issue_stable_id("gnrun", A, "other-id"),
                principal_id=A,
                source_root_id="icloud-goodnotes",
                trigger_type=GoodNotesIngestionTrigger.REPLAY,
                request_id=first.request_id,
                idempotency_key=first.request_id,
                request_fingerprint=FINGERPRINT_ONE,
                started_at=LATER,
                status=GoodNotesIngestionStatus.PENDING,
            )
        )
        assert replayed.run_id == stored.run_id
        assert replayed.status is GoodNotesIngestionStatus.RUNNING
        with pytest.raises(ValueError, match="bound to another ingestion"):
            repository.create_run(
                GoodNotesIngestionRun(
                    run_id=issue_stable_id("gnrun", A, "conflict"),
                    principal_id=A,
                    source_root_id="icloud-goodnotes",
                    trigger_type=GoodNotesIngestionTrigger.MANUAL,
                    request_id=first.request_id,
                    idempotency_key=first.request_id,
                    request_fingerprint=FINGERPRINT_TWO,
                    started_at=LATER,
                    status=GoodNotesIngestionStatus.PENDING,
                )
            )
        other = repository.create_run(_run(B, "idempotent", FINGERPRINT_ONE))
        assert other.run_id != stored.run_id
        finished = repository.update_run(
            GoodNotesIngestionRun(
                run_id=stored.run_id,
                principal_id=A,
                source_root_id=stored.source_root_id,
                trigger_type=stored.trigger_type,
                request_id=stored.request_id,
                idempotency_key=stored.idempotency_key,
                request_fingerprint=stored.request_fingerprint,
                started_at=stored.started_at,
                status=GoodNotesIngestionStatus.SUCCEEDED,
                ended_at=LATER,
                snapshot_count=1,
                page_count=2,
            )
        )
        assert finished.status is GoodNotesIngestionStatus.SUCCEEDED
        assert finished.snapshot_count == 1
        assert repository.run(B, stored.run_id) is None


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _source_page(
    *,
    principal_id: str,
    source_id: str,
    object_id: str,
    version_id: str,
    page_number: int,
    content: bytes,
    observed_at: datetime = WHEN,
) -> SourcePage:
    return SourcePage(
        principal_id=principal_id,
        source_id=source_id,
        source_object_id=object_id,
        source_version_id=version_id,
        page_number=page_number,
        observed_at=observed_at,
        content=content,
    )


def _observation(path: str, payload: bytes, page_count: int) -> ObservedNotebookFile:
    return ObservedNotebookFile(
        relative_path=path,
        size_bytes=len(payload),
        sha256=_sha(payload),
        mtime_ns=1_000_000_000,
        page_count=page_count,
    )


def test_lineage_reconcile_twice_on_identical_bytes_replays_snapshot(engine: Engine) -> None:
    cover = b"synthetic-cover-page"
    body = b"synthetic-body-page"
    notebook_bytes = cover + b"\x1f" + body
    object_id = "obj_cccccccccccccccccccccccc"
    pages = (
        _source_page(
            principal_id=A,
            source_id="src_cccccccccccccccccccccccc",
            object_id=object_id,
            version_id="ver_cccccccccccccccccccccccc",
            page_number=1,
            content=cover,
        ),
        _source_page(
            principal_id=A,
            source_id="src_cccccccccccccccccccccccc",
            object_id=object_id,
            version_id="ver_cccccccccccccccccccccccc",
            page_number=2,
            content=body,
        ),
    )
    notebook_id = issue_stable_id("gnnb", A, "service-replay")
    request = LineageReconcileRequest(
        principal_id=A,
        request_id="lineage-replay-1",
        source_root_id="icloud-goodnotes",
        source_object_id=object_id,
        observation=_observation("Inbox/replay.pdf", notebook_bytes, 2),
        pages=pages,
        notebook_id=notebook_id,
        observed_at=WHEN,
    )
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        service = GoodNotesLineageService()
        first = service.reconcile(
            request, renderer=RawRepresentationRenderer(), repository=repository, clock=lambda: WHEN
        )
        second = service.reconcile(
            LineageReconcileRequest(
                principal_id=A,
                request_id="lineage-replay-2",
                source_root_id="icloud-goodnotes",
                source_object_id=object_id,
                observation=request.observation,
                pages=pages,
                notebook_id=notebook_id,
                observed_at=LATER,
            ),
            renderer=RawRepresentationRenderer(),
            repository=repository,
            clock=lambda: LATER,
        )
        assert second.replayed_snapshot is True
        assert second.snapshot.snapshot_id == first.snapshot.snapshot_id
        assert len(repository.snapshots(A, notebook_id)) == 1
        assert len(repository.logical_pages(A, notebook_id)) == 2
        assert first.run.new_logical_page_count == 2
        assert second.run.new_logical_page_count == 0


def test_standalone_lineage_replay_rejects_page_identity_before_failed_resume(
    engine: Engine,
) -> None:
    cover = b"synthetic-cover-collision"
    object_id = "obj_eeeeeeeeeeeeeeeeeeeeeeee"
    source_id = "src_eeeeeeeeeeeeeeeeeeeeeeee"
    notebook_id = issue_stable_id("gnnb", A, "service-collision")
    pages = (
        _source_page(
            principal_id=A,
            source_id=source_id,
            object_id=object_id,
            version_id="ver_eeeeeeeeeeeeeeeeeeeeeeee",
            page_number=1,
            content=cover,
        ),
    )
    request = LineageReconcileRequest(
        principal_id=A,
        request_id="lineage-collision-1",
        source_root_id="icloud-goodnotes",
        source_object_id=object_id,
        observation=_observation("Inbox/collision.pdf", cover, 1),
        pages=pages,
        notebook_id=notebook_id,
        observed_at=WHEN,
    )
    colliding = LineageReconcileRequest(
        principal_id=A,
        request_id=request.request_id,
        source_root_id=request.source_root_id,
        source_object_id=object_id,
        observation=request.observation,
        pages=(
            _source_page(
                principal_id=A,
                source_id=source_id,
                object_id=object_id,
                version_id="ver_ffffffffffffffffffffffff",
                page_number=1,
                content=cover,
            ),
        ),
        notebook_id=notebook_id,
        observed_at=LATER,
    )
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        service = GoodNotesLineageService()
        first = service.reconcile(
            request, renderer=RawRepresentationRenderer(), repository=repository, clock=lambda: WHEN
        )
        with pytest.raises(ValueError, match="bound to another ingestion"):
            service.reconcile(
                colliding,
                renderer=RawRepresentationRenderer(),
                repository=repository,
                clock=lambda: LATER,
            )
        held = repository.run_by_request(A, request.request_id)
        assert held is not None
        assert held.status is first.run.status
        failed = repository.update_run(
            replace(
                first.run,
                status=GoodNotesIngestionStatus.FAILED,
                error_code="STAGE_FAILED",
                error_class="Synthetic",
            )
        )
        with pytest.raises(ValueError, match="bound to another ingestion"):
            service.reconcile(
                colliding,
                renderer=RawRepresentationRenderer(),
                repository=repository,
                clock=lambda: LATER,
            )
        still_failed = repository.run_by_request(A, request.request_id)
        assert still_failed is not None
        assert still_failed.status is GoodNotesIngestionStatus.FAILED
        assert still_failed.error_code == "STAGE_FAILED"
        assert still_failed.ended_at == failed.ended_at
        replayed = service.reconcile(
            LineageReconcileRequest(
                principal_id=A,
                request_id=request.request_id,
                source_root_id=request.source_root_id,
                source_object_id=object_id,
                observation=request.observation,
                pages=pages,
                notebook_id=notebook_id,
                observed_at=LATER,
            ),
            renderer=RawRepresentationRenderer(),
            repository=repository,
            clock=lambda: LATER,
        )
        assert replayed.replayed_snapshot is True
        assert replayed.run.status is GoodNotesIngestionStatus.REPLAYED
        assert len(repository.logical_pages(A, notebook_id)) == 1


def test_standalone_lineage_replay_rejects_content_only_mismatch_before_failed_resume(
    engine: Engine,
) -> None:
    cover = b"synthetic-cover-content"
    object_id = "obj_121212121212121212121212"
    source_id = "src_121212121212121212121212"
    version_id = "ver_121212121212121212121212"
    notebook_id = issue_stable_id("gnnb", A, "service-content-collision")
    pages = (
        _source_page(
            principal_id=A,
            source_id=source_id,
            object_id=object_id,
            version_id=version_id,
            page_number=1,
            content=cover,
        ),
    )
    request = LineageReconcileRequest(
        principal_id=A,
        request_id="lineage-content-collision-1",
        source_root_id="icloud-goodnotes",
        source_object_id=object_id,
        observation=_observation("Inbox/content-collision.pdf", cover, 1),
        pages=pages,
        notebook_id=notebook_id,
        observed_at=WHEN,
    )
    colliding = replace(
        request,
        pages=(
            _source_page(
                principal_id=A,
                source_id=source_id,
                object_id=object_id,
                version_id=version_id,
                page_number=1,
                content=b"synthetic-cover-altered",
            ),
        ),
        observed_at=LATER,
    )
    assert colliding.observation == request.observation
    assert colliding.observation.sha256 == request.observation.sha256
    assert _sha(colliding.pages[0].content) != _sha(cover)
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        service = GoodNotesLineageService()
        first = service.reconcile(
            request, renderer=RawRepresentationRenderer(), repository=repository, clock=lambda: WHEN
        )
        page_version_id = first.positions[0].page_version_id
        assert page_version_id is not None
        held_version = repository.page_version(A, page_version_id)
        with pytest.raises(ValueError, match="bound to another ingestion"):
            service.reconcile(
                colliding,
                renderer=RawRepresentationRenderer(),
                repository=repository,
                clock=lambda: LATER,
            )
        held = repository.run_by_request(A, request.request_id)
        assert held is not None
        assert held.status is first.run.status
        assert held.ended_at == first.run.ended_at
        assert repository.page_positions(A, first.snapshot.snapshot_id) == first.positions
        assert repository.page_version(A, page_version_id) == held_version
        failed = repository.update_run(
            replace(
                first.run,
                status=GoodNotesIngestionStatus.FAILED,
                error_code="STAGE_FAILED",
                error_class="Synthetic",
            )
        )
        with pytest.raises(ValueError, match="bound to another ingestion"):
            service.reconcile(
                colliding,
                renderer=RawRepresentationRenderer(),
                repository=repository,
                clock=lambda: LATER,
            )
        still_failed = repository.run_by_request(A, request.request_id)
        assert still_failed is not None
        assert still_failed.status is GoodNotesIngestionStatus.FAILED
        assert still_failed.error_code == "STAGE_FAILED"
        assert still_failed.error_class == "Synthetic"
        assert still_failed.ended_at == failed.ended_at
        assert repository.page_positions(A, first.snapshot.snapshot_id) == first.positions
        assert repository.page_version(A, page_version_id) == held_version
        replayed = service.reconcile(
            replace(request, observed_at=LATER),
            renderer=RawRepresentationRenderer(),
            repository=repository,
            clock=lambda: LATER,
        )
        assert replayed.replayed_snapshot is True
        assert replayed.run.status is GoodNotesIngestionStatus.REPLAYED


def test_lineage_reorder_across_two_snapshots(engine: Engine) -> None:
    cover = b"reorder-cover-page"
    body = b"reorder-body-page"
    object_id = "obj_dddddddddddddddddddddddd"
    notebook_id = issue_stable_id("gnnb", A, "service-reorder")
    first_pages = (
        _source_page(
            principal_id=A,
            source_id="src_dddddddddddddddddddddddd",
            object_id=object_id,
            version_id="ver_dddddddddddddddddddddddd",
            page_number=1,
            content=cover,
        ),
        _source_page(
            principal_id=A,
            source_id="src_dddddddddddddddddddddddd",
            object_id=object_id,
            version_id="ver_dddddddddddddddddddddddd",
            page_number=2,
            content=body,
        ),
    )
    reordered_pages = (
        _source_page(
            principal_id=A,
            source_id="src_dddddddddddddddddddddddd",
            object_id=object_id,
            version_id="ver_eeeeeeeeeeeeeeeeeeeeeeee",
            page_number=1,
            content=body,
            observed_at=LATER,
        ),
        _source_page(
            principal_id=A,
            source_id="src_dddddddddddddddddddddddd",
            object_id=object_id,
            version_id="ver_eeeeeeeeeeeeeeeeeeeeeeee",
            page_number=2,
            content=cover,
            observed_at=LATER,
        ),
    )
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        service = GoodNotesLineageService()
        first = service.reconcile(
            LineageReconcileRequest(
                principal_id=A,
                request_id="lineage-reorder-1",
                source_root_id="icloud-goodnotes",
                source_object_id=object_id,
                observation=_observation("Inbox/reorder.pdf", cover + b"\x1f" + body, 2),
                pages=first_pages,
                notebook_id=notebook_id,
                observed_at=WHEN,
            ),
            renderer=RawRepresentationRenderer(),
            repository=repository,
            clock=lambda: WHEN,
        )
        second = service.reconcile(
            LineageReconcileRequest(
                principal_id=A,
                request_id="lineage-reorder-2",
                source_root_id="icloud-goodnotes",
                source_object_id=object_id,
                observation=_observation("Inbox/reorder.pdf", body + b"\x1f" + cover, 2),
                pages=reordered_pages,
                notebook_id=notebook_id,
                observed_at=LATER,
            ),
            renderer=RawRepresentationRenderer(),
            repository=repository,
            clock=lambda: LATER,
        )
        assert second.replayed_snapshot is False
        assert second.snapshot.snapshot_id != first.snapshot.snapshot_id
        assert len(repository.snapshots(A, notebook_id)) == 2
        assert len(repository.logical_pages(A, notebook_id)) == 2
        assert second.run.new_logical_page_count == 0
        first_ids = [item.logical_page_id for item in first.positions]
        second_ids = [item.logical_page_id for item in second.positions]
        assert set(first_ids) == set(second_ids)
        assert second_ids == list(reversed(first_ids))


def test_lineage_cross_principal_isolation_holds(engine: Engine) -> None:
    payload = b"isolated-cover"
    object_id = "obj_ffffffffffffffffffffffff"
    notebook_id = issue_stable_id("gnnb", "shared", "service-isolation")
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        service = GoodNotesLineageService()
        result = service.reconcile(
            LineageReconcileRequest(
                principal_id=A,
                request_id="lineage-isolation-a",
                source_root_id="icloud-goodnotes",
                source_object_id=object_id,
                observation=_observation("Inbox/isolated.pdf", payload, 1),
                pages=(
                    _source_page(
                        principal_id=A,
                        source_id="src_ffffffffffffffffffffffff",
                        object_id=object_id,
                        version_id="ver_ffffffffffffffffffffffff",
                        page_number=1,
                        content=payload,
                    ),
                ),
                notebook_id=notebook_id,
                observed_at=WHEN,
            ),
            renderer=RawRepresentationRenderer(),
            repository=repository,
            clock=lambda: WHEN,
        )
        assert repository.snapshots(B, notebook_id) == ()
        assert repository.logical_pages(B, notebook_id) == ()
        assert repository.snapshot(B, result.snapshot.snapshot_id) is None
        for page in repository.logical_pages(A, notebook_id):
            assert repository.logical_page(B, page.logical_page_id) is None


def test_mapped_renderer_regenerated_unchanged_persists_zero_new_logical_pages(
    engine: Engine,
) -> None:
    original = b"raw-cover-v1"
    regenerated = b"raw-cover-v2"
    shared = hashlib.sha256(b"normalized-cover").hexdigest()
    object_id = "obj_abababababababababababab"
    notebook_id = issue_stable_id("gnnb", A, "service-regen")
    renderer = MappedPageRenderer(
        mapping={
            _sha(original): (shared, None, None),
            _sha(regenerated): (shared, None, None),
        }
    )
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        service = GoodNotesLineageService()
        first = service.reconcile(
            LineageReconcileRequest(
                principal_id=A,
                request_id="lineage-regen-1",
                source_root_id="icloud-goodnotes",
                source_object_id=object_id,
                observation=_observation("Inbox/regen.pdf", original, 1),
                pages=(
                    _source_page(
                        principal_id=A,
                        source_id="src_abababababababababababab",
                        object_id=object_id,
                        version_id="ver_abababababababababababab",
                        page_number=1,
                        content=original,
                    ),
                ),
                notebook_id=notebook_id,
                observed_at=WHEN,
            ),
            renderer=renderer,
            repository=repository,
            clock=lambda: WHEN,
        )
        second = service.reconcile(
            LineageReconcileRequest(
                principal_id=A,
                request_id="lineage-regen-2",
                source_root_id="icloud-goodnotes",
                source_object_id=object_id,
                observation=_observation("Inbox/regen.pdf", regenerated, 1),
                pages=(
                    _source_page(
                        principal_id=A,
                        source_id="src_abababababababababababab",
                        object_id=object_id,
                        version_id="ver_cdcdcdcdcdcdcdcdcdcdcdcd",
                        page_number=1,
                        content=regenerated,
                        observed_at=LATER,
                    ),
                ),
                notebook_id=notebook_id,
                observed_at=LATER,
            ),
            renderer=renderer,
            repository=repository,
            clock=lambda: LATER,
        )
        assert second.replayed_snapshot is False
        assert len(repository.logical_pages(A, notebook_id)) == 1
        assert second.run.new_logical_page_count == 0
        assert second.positions[0].logical_page_id == first.positions[0].logical_page_id
        assert second.positions[0].match_method is GoodNotesMatchMethod.EXACT_NORMALIZED_RENDER


def test_visual_renderer_regenerated_pdf_persists_zero_new_logical_pages(engine: Engine) -> None:
    cover = (Rect(72, 400, 220, 220, 0.15),)
    body = (Rect(80, 80, 420, 520, 0.45),)
    original = vector_pdf((cover, body), producer="db-visual-a")
    regenerated = vector_pdf(
        (cover, body), producer="db-visual-b", comment="regenerated", dummy_objects=5
    )
    assert original != regenerated
    object_id = "obj_919191919191919191919191"
    notebook_id = issue_stable_id("gnnb", A, "service-visual-regen")
    renderer = production_page_renderer()

    def pages(pdf: bytes, version_id: str, observed_at: datetime) -> tuple[SourcePage, ...]:
        return tuple(
            _source_page(
                principal_id=A,
                source_id="src_919191919191919191919191",
                object_id=object_id,
                version_id=version_id,
                page_number=index,
                content=part,
                observed_at=observed_at,
            )
            for index, part in enumerate(split_admitted_pdf(pdf), start=1)
        )

    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        service = GoodNotesLineageService()
        first = service.reconcile(
            LineageReconcileRequest(
                principal_id=A,
                request_id="lineage-visual-1",
                source_root_id="icloud-goodnotes",
                source_object_id=object_id,
                observation=_observation("Inbox/visual.pdf", original, 2),
                pages=pages(original, "ver_919191919191919191919191", WHEN),
                notebook_id=notebook_id,
                observed_at=WHEN,
            ),
            renderer=renderer,
            repository=repository,
            clock=lambda: WHEN,
        )
        second = service.reconcile(
            LineageReconcileRequest(
                principal_id=A,
                request_id="lineage-visual-2",
                source_root_id="icloud-goodnotes",
                source_object_id=object_id,
                observation=_observation("Inbox/visual.pdf", regenerated, 2),
                pages=pages(regenerated, "ver_929292929292929292929292", LATER),
                notebook_id=notebook_id,
                observed_at=LATER,
            ),
            renderer=renderer,
            repository=repository,
            clock=lambda: LATER,
        )
        stored = repository.page_version(A, second.positions[0].page_version_id)
        assert stored is not None
        assert stored.exact_render_sha256 is not None
        assert stored.exact_render_sha256 != stored.content_sha256
        assert stored.normalized_render_sha256 is not None
        assert stored.normalized_render_sha256 != stored.content_sha256
        assert second.replayed_snapshot is False
        assert second.run.new_logical_page_count == 0
        assert {item.logical_page_id for item in first.positions} == {
            item.logical_page_id for item in second.positions
        }
        assert all(
            item.match_method is GoodNotesMatchMethod.EXACT_NORMALIZED_RENDER
            for item in second.positions
        )


@pytest.fixture
def engine(db_engine: Engine) -> Engine:
    return db_engine
