"""Notebook identity survives rename and source-object churn without using path."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from my_pa.application.goodnotes_lineage import (
    GoodNotesLineageService,
    LineageReconcileRequest,
    ObservedNotebookFile,
    resolve_notebook_identity,
)
from my_pa.domain.goodnotes.models import GoodNotesIdentityStatus, SourcePage, issue_stable_id
from my_pa.infrastructure.goodnotes.render import MappedPageRenderer, RawRepresentationRenderer
from tests.unit.goodnotes_lineage_memory import MemoryLineageRepository

WHEN = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
ROOT_ID = "icloud-goodnotes"
OBJECT_A = "obj_aaaaaaaaaaaaaaaaaaaaaaaa"
OBJECT_B = "obj_bbbbbbbbbbbbbbbbbbbbbbbb"
OBJECT_C = "obj_cccccccccccccccccccccccc"
SHARED_VISUAL = "c" * 64


def _page(
    object_id: str, content: bytes, version: str = "ver_aaaaaaaaaaaaaaaaaaaaaaaa"
) -> SourcePage:
    return SourcePage(
        principal_id=A,
        source_id="src_aaaaaaaaaaaaaaaaaaaaaaaa",
        source_object_id=object_id,
        source_version_id=version,
        page_number=1,
        observed_at=WHEN,
        content=content,
    )


def _observation(payload: bytes, path: str) -> ObservedNotebookFile:
    return ObservedNotebookFile(
        relative_path=path,
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        mtime_ns=1,
        page_count=1,
    )


def _request(
    payload: bytes,
    *,
    object_id: str,
    request_id: str,
    path: str,
    notebook_id: str | None = None,
    version: str = "ver_aaaaaaaaaaaaaaaaaaaaaaaa",
) -> LineageReconcileRequest:
    return LineageReconcileRequest(
        principal_id=A,
        request_id=request_id,
        source_root_id=ROOT_ID,
        source_object_id=object_id,
        observation=_observation(payload, path),
        pages=(_page(object_id, payload, version),),
        notebook_id=notebook_id,
        observed_at=WHEN,
    )


def test_rename_with_stable_source_object_keeps_notebook_id() -> None:
    payload = b"notebook-bytes"
    repository = MemoryLineageRepository()
    service = GoodNotesLineageService()
    first = service.reconcile(
        _request(payload, object_id=OBJECT_A, request_id="id-1", path="Inbox/alpha.pdf"),
        renderer=RawRepresentationRenderer(),
        repository=repository,
        clock=lambda: WHEN,
    )
    second = service.reconcile(
        _request(
            b"notebook-bytes-changed",
            object_id=OBJECT_A,
            request_id="id-2",
            path="Archive/renamed.pdf",
            version="ver_bbbbbbbbbbbbbbbbbbbbbbbb",
        ),
        renderer=RawRepresentationRenderer(),
        repository=repository,
        clock=lambda: WHEN,
    )
    assert first.notebook.notebook_id == second.notebook.notebook_id
    assert first.notebook.notebook_id == issue_stable_id("gnnb", A, ROOT_ID, OBJECT_A)
    assert second.snapshot.observed_path == "Archive/renamed.pdf"


def test_source_object_churn_with_matching_raw_digest_reuses_notebook() -> None:
    payload = b"same-raw-bytes"
    repository = MemoryLineageRepository()
    service = GoodNotesLineageService()
    first = service.reconcile(
        _request(payload, object_id=OBJECT_A, request_id="digest-1", path="Inbox/one.pdf"),
        renderer=RawRepresentationRenderer(),
        repository=repository,
        clock=lambda: WHEN,
    )
    second = service.reconcile(
        _request(
            payload,
            object_id=OBJECT_B,
            request_id="digest-2",
            path="Inbox/two.pdf",
            version="ver_bbbbbbbbbbbbbbbbbbbbbbbb",
        ),
        renderer=RawRepresentationRenderer(),
        repository=repository,
        clock=lambda: WHEN,
    )
    assert second.notebook.notebook_id == first.notebook.notebook_id
    assert second.replayed_snapshot is True


def test_source_object_churn_with_unique_visual_match_reuses_notebook() -> None:
    first_bytes = b"visual-page-one"
    second_bytes = b"visual-page-one-regenerated"
    renderer = MappedPageRenderer(
        mapping={
            hashlib.sha256(first_bytes).hexdigest(): (SHARED_VISUAL, "fp", (8, 10)),
            hashlib.sha256(second_bytes).hexdigest(): (SHARED_VISUAL, "fp", (8, 10)),
        }
    )
    repository = MemoryLineageRepository()
    service = GoodNotesLineageService()
    first = service.reconcile(
        _request(first_bytes, object_id=OBJECT_A, request_id="vis-1", path="Inbox/one.pdf"),
        renderer=renderer,
        repository=repository,
        clock=lambda: WHEN,
    )
    second = service.reconcile(
        _request(
            second_bytes,
            object_id=OBJECT_B,
            request_id="vis-2",
            path="Inbox/two.pdf",
            version="ver_bbbbbbbbbbbbbbbbbbbbbbbb",
        ),
        renderer=renderer,
        repository=repository,
        clock=lambda: WHEN,
    )
    assert second.notebook.notebook_id == first.notebook.notebook_id
    assert second.replayed_snapshot is False
    assert second.run.new_logical_page_count == 0


def test_two_notebooks_that_could_match_are_ambiguous() -> None:
    payload = b"template-page"
    renderer = MappedPageRenderer(
        mapping={
            hashlib.sha256(payload).hexdigest(): (SHARED_VISUAL, "fp", (8, 10)),
        }
    )
    repository = MemoryLineageRepository()
    service = GoodNotesLineageService()
    left_id = issue_stable_id("gnnb", "left")
    right_id = issue_stable_id("gnnb", "right")
    service.reconcile(
        _request(
            payload,
            object_id=OBJECT_A,
            request_id="amb-1",
            path="Inbox/left.pdf",
            notebook_id=left_id,
        ),
        renderer=renderer,
        repository=repository,
        clock=lambda: WHEN,
    )
    service.reconcile(
        _request(
            payload,
            object_id=OBJECT_B,
            request_id="amb-2",
            path="Inbox/right.pdf",
            notebook_id=right_id,
            version="ver_bbbbbbbbbbbbbbbbbbbbbbbb",
        ),
        renderer=renderer,
        repository=repository,
        clock=lambda: WHEN,
    )
    third = service.reconcile(
        _request(
            payload,
            object_id=OBJECT_C,
            request_id="amb-3",
            path="Inbox/third.pdf",
            version="ver_cccccccccccccccccccccccc",
        ),
        renderer=renderer,
        repository=repository,
        clock=lambda: WHEN,
    )
    assert third.notebook.identity_status is GoodNotesIdentityStatus.AMBIGUOUS
    assert third.notebook.notebook_id not in {left_id, right_id}


def test_caller_supplied_notebook_id_wins() -> None:
    supplied = issue_stable_id("gnnb", "caller")
    request = _request(
        b"any-bytes",
        object_id=OBJECT_A,
        request_id="caller-1",
        path="Inbox/x.pdf",
        notebook_id=supplied,
    )
    notebook_id, status = resolve_notebook_identity(
        request,
        principal_id=A,
        repository=MemoryLineageRepository(),
        normalized_render_sha256s=("d" * 64,),
    )
    assert notebook_id == supplied
    assert status is GoodNotesIdentityStatus.ACTIVE
