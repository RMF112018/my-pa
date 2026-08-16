from __future__ import annotations

import hashlib
import inspect
import os
import stat
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import pytest

from my_pa.application.goodnotes_lineage import (
    LineageReconcileRequest,
    ObservedNotebookFile,
    match_logical_pages,
)
from my_pa.domain.goodnotes.models import (
    GoodNotesIdentityStatus,
    GoodNotesMatchMethod,
    GoodNotesPriorPageEvidence,
    PageRender,
    SourcePage,
    issue_stable_id,
)
from my_pa.infrastructure.goodnotes.local import (
    GoodNotesLocalSourceError,
    LocalGoodNotesObserver,
    ManifestGoodNotesSource,
)
from my_pa.infrastructure.goodnotes.render import MappedPageRenderer, RawRepresentationRenderer

WHEN = datetime(2026, 8, 16, 16, 0, tzinfo=UTC)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
NOTEBOOK = issue_stable_id("gnnb", "synthetic", "notebook")
COVER = issue_stable_id("gnlp", "synthetic", "cover")
BODY = issue_stable_id("gnlp", "synthetic", "body")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _render(
    payload: bytes,
    *,
    normalized: str | None = None,
    fingerprint: str | None = None,
    width: int | None = None,
    height: int | None = None,
) -> PageRender:
    exact = _sha(payload)
    return PageRender(
        exact_render_sha256=exact,
        normalized_render_sha256=normalized or exact,
        renderer_name="synthetic",
        renderer_version="1",
        render_profile_version="test",
        perceptual_hash=fingerprint,
        perceptual_algorithm="test-double",
        perceptual_algorithm_version="1",
        width=width,
        height=height,
    )


def _prior(
    logical_page_id: str,
    page_number: int,
    payload: bytes,
    *,
    normalized: str | None = None,
    fingerprint: str | None = None,
    width: int | None = None,
    height: int | None = None,
) -> GoodNotesPriorPageEvidence:
    render = _render(
        payload, normalized=normalized, fingerprint=fingerprint, width=width, height=height
    )
    return GoodNotesPriorPageEvidence(
        logical_page_id=logical_page_id,
        last_page_number=page_number,
        last_page_version_id=issue_stable_id("gnver", logical_page_id, str(page_number)),
        exact_render_sha256=render.exact_render_sha256,
        normalized_render_sha256=render.normalized_render_sha256,
        perceptual_hash=fingerprint,
        render_width=width,
        render_height=height,
    )


def test_raw_representation_renderer_hashes_admitted_bytes() -> None:
    payload = b"%PDF-1.7\nsynthetic page\n%%EOF\n"
    render = RawRepresentationRenderer().render(payload)
    digest = _sha(payload)
    assert render.exact_render_sha256 == digest
    assert render.normalized_render_sha256 == digest
    assert render.perceptual_hash is None
    assert render.width is None and render.height is None
    assert render.renderer_name == "raw-representation"
    assert render.render_profile_version == "raw-representation-v1"


def test_mapped_renderer_can_give_different_bytes_the_same_normalized_sha() -> None:
    first = b"raw-bytes-one"
    second = b"raw-bytes-two-regenerated"
    shared = _sha(b"normalized-visual")
    renderer = MappedPageRenderer(
        mapping={
            _sha(first): (shared, "fp-cover", (1200, 1600)),
            _sha(second): (shared, "fp-cover", (1200, 1600)),
        }
    )
    assert renderer.render(first).normalized_render_sha256 == shared
    assert renderer.render(second).normalized_render_sha256 == shared
    assert renderer.render(first).exact_render_sha256 != renderer.render(second).exact_render_sha256


def test_regenerated_unchanged_reuses_logical_page() -> None:
    original = b"cover-v1"
    regenerated = b"cover-v2-same-visual"
    shared = _sha(b"cover-visual")
    prior = (
        _prior(COVER, 1, original, normalized=shared, fingerprint="fp-cover", width=8, height=10),
    )
    matches = match_logical_pages(
        notebook_id=NOTEBOOK,
        current=(
            (
                1,
                _render(regenerated, normalized=shared, fingerprint="fp-cover", width=8, height=10),
            ),
        ),
        prior=prior,
    )
    assert len(matches) == 1
    assert matches[0].logical_page_id == COVER
    assert matches[0].is_new is False
    assert matches[0].match_method is GoodNotesMatchMethod.EXACT_NORMALIZED_RENDER


def test_reorder_keeps_logical_ids_and_changes_positions() -> None:
    cover = b"cover-bytes"
    body = b"body-bytes"
    prior = (_prior(COVER, 1, cover), _prior(BODY, 2, body))
    matches = match_logical_pages(
        notebook_id=NOTEBOOK,
        current=((1, _render(body)), (2, _render(cover))),
        prior=prior,
    )
    by_number = {item.page_number: item for item in matches}
    assert {item.logical_page_id for item in matches} == {COVER, BODY}
    assert by_number[1].logical_page_id == BODY
    assert by_number[2].logical_page_id == COVER
    assert all(not item.is_new for item in matches)


def test_append_creates_only_the_new_logical_page() -> None:
    cover = b"cover-bytes"
    body = b"body-bytes"
    added = b"appended-bytes"
    prior = (_prior(COVER, 1, cover), _prior(BODY, 2, body))
    matches = match_logical_pages(
        notebook_id=NOTEBOOK,
        current=((1, _render(cover)), (2, _render(body)), (3, _render(added))),
        prior=prior,
    )
    by_number = {item.page_number: item for item in matches}
    assert by_number[1].logical_page_id == COVER
    assert by_number[2].logical_page_id == BODY
    assert by_number[3].is_new is True
    assert by_number[3].logical_page_id not in {COVER, BODY}
    assert sum(item.is_new for item in matches) == 1


def test_shared_fingerprint_is_ambiguous_and_not_silently_picked() -> None:
    shared = "fp-shared"
    prior = (
        _prior(COVER, 1, b"one", fingerprint=shared, width=8, height=10),
        _prior(BODY, 2, b"two", fingerprint=shared, width=8, height=10),
    )
    matches = match_logical_pages(
        notebook_id=NOTEBOOK,
        current=(
            (1, _render(b"new-one", fingerprint=shared, width=8, height=10)),
            (2, _render(b"new-two", fingerprint=shared, width=8, height=10)),
        ),
        prior=prior,
    )
    assert all(item.identity_status is GoodNotesIdentityStatus.AMBIGUOUS for item in matches)
    assert all(item.match_method is GoodNotesMatchMethod.UNRESOLVED for item in matches)
    assert all(item.is_new for item in matches)
    assert {item.logical_page_id for item in matches}.isdisjoint({COVER, BODY})


def test_page_number_alone_never_matches() -> None:
    prior = (_prior(COVER, 1, b"old-cover"), _prior(BODY, 2, b"old-body"))
    matches = match_logical_pages(
        notebook_id=NOTEBOOK,
        current=((1, _render(b"unrelated-one")), (2, _render(b"unrelated-two"))),
        prior=prior,
    )
    assert all(item.is_new for item in matches)
    assert all(item.match_method is GoodNotesMatchMethod.UNRESOLVED for item in matches)
    assert {item.logical_page_id for item in matches}.isdisjoint({COVER, BODY})


def test_matcher_source_does_not_read_transcription() -> None:
    source = inspect.getsource(match_logical_pages)
    assert "transcription" not in source


def test_sequence_tiebreak_only_when_one_candidate_remains() -> None:
    cover = b"cover-bytes"
    body = b"body-bytes"
    prior = (_prior(COVER, 1, cover), _prior(BODY, 2, body))
    matches = match_logical_pages(
        notebook_id=NOTEBOOK,
        current=((1, _render(cover)), (2, _render(b"moved-neighbor"))),
        prior=prior,
    )
    by_number = {item.page_number: item for item in matches}
    assert by_number[1].logical_page_id == COVER
    assert by_number[2].logical_page_id == BODY
    assert by_number[2].match_method is GoodNotesMatchMethod.SEQUENCE_TIEBREAK
    assert by_number[2].is_new is False


def _write_pdf(root: Path, relative: str, payload: bytes | None = None) -> bytes:
    content = payload or b"%PDF-1.7\nsynthetic notebook page\n%%EOF\n"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def test_observer_records_settle_metadata(tmp_path: Path) -> None:
    payload = _write_pdf(tmp_path, "Inbox/alpha.pdf")
    observer = LocalGoodNotesObserver(root=tmp_path, source_root_id="icloud-goodnotes")
    observed = observer.settle(PurePosixPath("Inbox/alpha.pdf"), page_count=3)
    assert observed.relative_path == "Inbox/alpha.pdf"
    assert observed.size_bytes == len(payload)
    assert observed.sha256 == _sha(payload)
    assert observed.mtime_ns > 0
    assert observed.page_count == 3
    assert observed.media_type == "application/pdf"
    assert observed.content == payload


def test_observer_fails_closed_on_mid_read_stat_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_pdf(tmp_path, "Inbox/alpha.pdf")
    observer = LocalGoodNotesObserver(root=tmp_path, source_root_id="icloud-goodnotes")
    original = os.fstat
    regular_reads = {"n": 0}

    def flaky(fd: int) -> os.stat_result:
        result = original(fd)
        if stat.S_ISREG(result.st_mode):
            regular_reads["n"] += 1
            if regular_reads["n"] >= 2:

                class Mutated:
                    def __init__(self, inner: os.stat_result) -> None:
                        self._inner = inner

                    def __getattr__(self, name: str) -> object:
                        if name == "st_mtime_ns":
                            return int(self._inner.st_mtime_ns) + 1
                        return getattr(self._inner, name)

                return Mutated(result)  # type: ignore[return-value]
        return result

    monkeypatch.setattr(os, "fstat", flaky)
    with pytest.raises(GoodNotesLocalSourceError, match="digest changed"):
        observer.settle(PurePosixPath("Inbox/alpha.pdf"))


def test_observer_fails_closed_on_digest_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_pdf(tmp_path, "Inbox/alpha.pdf")
    observer = LocalGoodNotesObserver(root=tmp_path, source_root_id="icloud-goodnotes")
    from my_pa.infrastructure.goodnotes import local as local_mod

    calls = {"n": 0}
    original = local_mod._read_admitted

    def mutating(*args: object, **kwargs: object) -> object:
        result = original(*args, **kwargs)
        calls["n"] += 1
        if calls["n"] == 1:
            (tmp_path / "Inbox" / "alpha.pdf").write_bytes(b"%PDF-1.7\nmutated\n%%EOF\n")
        return result

    monkeypatch.setattr(local_mod, "_read_admitted", mutating)
    with pytest.raises(GoodNotesLocalSourceError, match="digest changed"):
        observer.settle(PurePosixPath("Inbox/alpha.pdf"))


def test_observer_refuses_path_escape_symlink_root_oversize_and_unsupported(
    tmp_path: Path,
) -> None:
    _write_pdf(tmp_path, "Inbox/alpha.pdf")
    observer = LocalGoodNotesObserver(root=tmp_path, source_root_id="icloud-goodnotes")
    with pytest.raises(GoodNotesLocalSourceError, match="relative"):
        observer.settle(PurePosixPath("../outside.pdf"))
    with pytest.raises(GoodNotesLocalSourceError, match="unsupported"):
        (tmp_path / "notes.txt").write_text("not a page")
        observer.settle(PurePosixPath("notes.txt"))
    bounded = LocalGoodNotesObserver(
        root=tmp_path, source_root_id="icloud-goodnotes", maximum_file_bytes=8
    )
    with pytest.raises(GoodNotesLocalSourceError, match="bounded file"):
        bounded.settle(PurePosixPath("Inbox/alpha.pdf"))
    linked = tmp_path / "linked-root"
    linked.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(GoodNotesLocalSourceError, match="cannot be a link"):
        LocalGoodNotesObserver(root=linked, source_root_id="icloud-goodnotes")
    with pytest.raises(GoodNotesLocalSourceError, match="not a filesystem path"):
        LocalGoodNotesObserver(root=tmp_path, source_root_id="/Users/synthetic/GoodNotes")
    with pytest.raises(GoodNotesLocalSourceError, match="explicit"):
        observer.observe(())


def test_existing_manifest_source_still_refuses_unsupported_and_oversize(tmp_path: Path) -> None:
    content = _write_pdf(tmp_path, "notebook/page-0001.bin")
    manifest = tmp_path / "goodnotes-manifest.json"
    manifest.write_text(
        '{"schema": "my-pa.goodnotes-local-source.v1", "pages": [{'
        f'"principal_id": "{A}",'
        '"source_id": "src_aaaaaaaaaaaaaaaaaaaaaaaa",'
        '"source_object_id": "obj_aaaaaaaaaaaaaaaaaaaaaaaa",'
        '"source_version_id": "ver_aaaaaaaaaaaaaaaaaaaaaaaa",'
        '"page_number": 1,'
        '"observed_at": "2026-08-16T16:00:00Z",'
        '"relative_path": "notebook/page-0001.bin",'
        f'"content_sha256": "{_sha(content)}",'
        '"media_type": "application/octet-stream"}]}'
    )
    source = ManifestGoodNotesSource(root=tmp_path)
    with pytest.raises(GoodNotesLocalSourceError, match="unsupported"):
        source.inventory(A)
    pdf = _write_pdf(tmp_path, "notebook/page-0001.pdf")
    manifest.write_text(
        '{"schema": "my-pa.goodnotes-local-source.v1", "pages": [{'
        f'"principal_id": "{A}",'
        '"source_id": "src_aaaaaaaaaaaaaaaaaaaaaaaa",'
        '"source_object_id": "obj_aaaaaaaaaaaaaaaaaaaaaaaa",'
        '"source_version_id": "ver_aaaaaaaaaaaaaaaaaaaaaaaa",'
        '"page_number": 1,'
        '"observed_at": "2026-08-16T16:00:00Z",'
        '"relative_path": "notebook/page-0001.pdf",'
        f'"content_sha256": "{_sha(pdf)}",'
        '"media_type": "application/pdf"}]}'
    )
    tight = ManifestGoodNotesSource(root=tmp_path, maximum_page_bytes=8)
    with pytest.raises(GoodNotesLocalSourceError, match="bounded file"):
        tight.inventory(A)


def test_lineage_request_keeps_supplied_notebook_id_across_path_rename() -> None:
    first = ObservedNotebookFile(
        relative_path="Inbox/alpha.pdf",
        size_bytes=12,
        sha256="a" * 64,
        mtime_ns=1,
        page_count=1,
    )
    renamed = replace(first, relative_path="Archive/alpha.pdf")
    request = LineageReconcileRequest(
        principal_id=A,
        request_id="req-1",
        source_root_id="icloud-goodnotes",
        source_object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
        observation=renamed,
        pages=(
            SourcePage(
                principal_id=A,
                source_id="src_aaaaaaaaaaaaaaaaaaaaaaaa",
                source_object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
                source_version_id="ver_aaaaaaaaaaaaaaaaaaaaaaaa",
                page_number=1,
                observed_at=WHEN,
                content=b"page-one",
            ),
        ),
        notebook_id=NOTEBOOK,
    )
    assert request.notebook_id == NOTEBOOK
    assert request.observation.relative_path == "Archive/alpha.pdf"
