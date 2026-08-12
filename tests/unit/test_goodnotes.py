from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import pytest

from my_pa.application.goodnotes import (
    GoodNotesSearchHit,
    GoodNotesService,
    ReconciliationConflictError,
    ReconciliationReceipt,
    SourcePage,
    TranscribedRegion,
)
from my_pa.bootstrap.goodnotes import compose_local_goodnotes_runtime
from my_pa.domain.goodnotes.models import (
    GoodNotesPage,
    GoodNotesPageVersion,
    GoodNotesRegionProposal,
)
from my_pa.infrastructure.goodnotes.fixture import FixtureGoodNotesSource, FixturePageTranscriber
from my_pa.infrastructure.goodnotes.local import (
    BoundedLocalOCRTranscriber,
    GoodNotesLocalSourceError,
    GoodNotesTranscriptionError,
    ManifestGoodNotesSource,
)

WHEN = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
B = "prn_bbbbbbbbbbbbbbbbbbbbbbbb"


class MemoryRepository:
    def __init__(self) -> None:
        self.receipts: dict[tuple[str, str], ReconciliationReceipt] = {}
        self.pages: dict[tuple[str, str], GoodNotesPage] = {}
        self.versions: dict[tuple[str, str], GoodNotesPageVersion] = {}
        self.regions: dict[tuple[str, str], GoodNotesRegionProposal] = {}
        self.decisions: dict[tuple[str, str], tuple[str, str | None]] = {}

    def receipt(self, principal_id: str, idempotency_key: str) -> ReconciliationReceipt | None:
        return self.receipts.get((principal_id, idempotency_key))

    def store_reconciliation(
        self,
        *,
        receipt: ReconciliationReceipt,
        pages: tuple[GoodNotesPage, ...],
        versions: tuple[GoodNotesPageVersion, ...],
        regions: tuple[GoodNotesRegionProposal, ...],
    ) -> ReconciliationReceipt:
        self.receipts[(receipt.principal_id, receipt.idempotency_key)] = receipt
        self.pages.update({(page.principal_id, page.page_id): page for page in pages})
        self.versions.update(
            {(receipt.principal_id, version.page_version_id): version for version in versions}
        )
        self.regions.update(
            {(receipt.principal_id, region.region_id): region for region in regions}
        )
        return receipt

    def decide_region(
        self,
        *,
        principal_id: str,
        region_id: str,
        disposition: str,
        corrected_text: str | None,
        decided_at: datetime,
    ) -> None:
        if (principal_id, region_id) not in self.regions:
            raise ValueError("unknown region")
        self.decisions[(principal_id, region_id)] = (disposition, corrected_text)

    def search(
        self, principal_id: str, query: str, *, limit: int
    ) -> tuple[GoodNotesSearchHit, ...]:
        hits = []
        for (owner, region_id), (disposition, correction) in self.decisions.items():
            if owner != principal_id or disposition not in {"accepted", "corrected_accepted"}:
                continue
            region = self.regions[(owner, region_id)]
            text = correction or region.transcription
            if query.casefold() not in text.casefold():
                continue
            version = self.versions[(owner, region.page_version_id)]
            page = self.pages[(owner, version.page_id)]
            hits.append(
                GoodNotesSearchHit(
                    region_id=region_id,
                    page_version_id=version.page_version_id,
                    source_version_id=version.source_version_id,
                    page_number=page.page_number,
                    accepted_text=text,
                    corrected=correction is not None,
                )
            )
        return tuple(hits[:limit])


def source() -> FixtureGoodNotesSource:
    return FixtureGoodNotesSource(
        pages=(
            SourcePage(
                principal_id=A,
                source_id="src_aaaaaaaaaaaaaaaaaaaaaaaa",
                source_object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
                source_version_id="ver_aaaaaaaaaaaaaaaaaaaaaaaa",
                page_number=1,
                observed_at=WHEN,
                content=b"Synthetic alpha commitment",
            ),
            SourcePage(
                principal_id=B,
                source_id="src_bbbbbbbbbbbbbbbbbbbbbbbb",
                source_object_id="obj_bbbbbbbbbbbbbbbbbbbbbbbb",
                source_version_id="ver_bbbbbbbbbbbbbbbbbbbbbbbb",
                page_number=1,
                observed_at=WHEN,
                content=b"Synthetic beta decision",
            ),
        )
    )


def test_reconcile_is_stable_retry_safe_and_does_not_mix_principals() -> None:
    repository = MemoryRepository()
    service = GoodNotesService()
    first = service.reconcile(
        principal_id=A,
        idempotency_key="sync-1",
        source=source(),
        transcriber=FixturePageTranscriber(),
        repository=repository,
    )
    replay = service.reconcile(
        principal_id=A,
        idempotency_key="sync-1",
        source=source(),
        transcriber=FixturePageTranscriber(),
        repository=repository,
    )
    b = service.reconcile(
        principal_id=B,
        idempotency_key="sync-1",
        source=source(),
        transcriber=FixturePageTranscriber(),
        repository=repository,
    )
    assert replay.replayed and replay.receipt_id == first.receipt_id
    assert first.page_version_ids != b.page_version_ids
    assert len(repository.regions) == 2
    assert all(owner in {A, B} for owner, _ in repository.regions)


def test_changed_inventory_conflicts_with_consumed_idempotency_key() -> None:
    repository = MemoryRepository()
    service = GoodNotesService()
    original = source()
    service.reconcile(
        principal_id=A,
        idempotency_key="sync-1",
        source=original,
        transcriber=FixturePageTranscriber(),
        repository=repository,
    )
    changed = FixtureGoodNotesSource(
        pages=(replace(original.pages[0], content=b"changed source page"),)
    )
    with pytest.raises(ReconciliationConflictError):
        service.reconcile(
            principal_id=A,
            idempotency_key="sync-1",
            source=changed,
            transcriber=FixturePageTranscriber(),
            repository=repository,
        )


def test_transcriber_failure_leaves_no_deterministic_record() -> None:
    class BrokenTranscriber(FixturePageTranscriber):
        def transcribe(self, page: SourcePage) -> tuple[TranscribedRegion, ...]:
            raise RuntimeError("synthetic OCR failure")

    repository = MemoryRepository()
    with pytest.raises(RuntimeError, match="synthetic OCR failure"):
        GoodNotesService().reconcile(
            principal_id=A,
            idempotency_key="sync-broken",
            source=source(),
            transcriber=BrokenTranscriber(),
            repository=repository,
        )
    assert repository.pages == repository.versions == repository.regions == {}
    assert repository.receipts == {}


def test_review_correction_becomes_searchable_only_for_owning_principal() -> None:
    repository = MemoryRepository()
    service = GoodNotesService()
    service.reconcile(
        principal_id=A,
        idempotency_key="sync-1",
        source=source(),
        transcriber=FixturePageTranscriber(),
        repository=repository,
    )
    region_id = next(region for owner, region in repository.regions if owner == A)
    with pytest.raises(ValueError, match="unknown region"):
        service.accept_region(
            principal_id=B,
            region_id=region_id,
            corrected_text="foreign correction",
            decided_at=WHEN,
            repository=repository,
        )
    service.accept_region(
        principal_id=A,
        region_id=region_id,
        corrected_text="Reviewed alpha commitment",
        decided_at=WHEN,
        repository=repository,
    )
    hits = repository.search(A, "reviewed alpha", limit=10)
    assert len(hits) == 1 and hits[0].corrected
    assert hits[0].source_version_id == "ver_aaaaaaaaaaaaaaaaaaaaaaaa"
    assert repository.search(B, "reviewed alpha", limit=10) == ()


def _local_manifest(tmp_path: Path, *, digest: str | None = None) -> ManifestGoodNotesSource:
    root = tmp_path
    content = b"%PDF-1.7\nsynthetic rasterized GoodNotes page\n%%EOF\n"
    page = root / "notebook" / "page-0001.pdf"
    page.parent.mkdir()
    page.write_bytes(content)
    manifest = {
        "schema": "my-pa.goodnotes-local-source.v1",
        "pages": [
            {
                "principal_id": A,
                "source_id": "src_aaaaaaaaaaaaaaaaaaaaaaaa",
                "source_object_id": "obj_aaaaaaaaaaaaaaaaaaaaaaaa",
                "source_version_id": "ver_aaaaaaaaaaaaaaaaaaaaaaaa",
                "page_number": 1,
                "observed_at": "2026-08-12T10:00:00Z",
                "relative_path": "notebook/page-0001.pdf",
                "content_sha256": digest or hashlib.sha256(content).hexdigest(),
                "media_type": "application/pdf",
            }
        ],
    }
    (root / "goodnotes-manifest.json").write_text(json.dumps(manifest))
    return ManifestGoodNotesSource(root=root)


def _ocr_command(tmp_path: Path) -> tuple[str, ...]:
    script = tmp_path / "synthetic-local-ocr.py"
    script.write_text(
        "import json, sys\n"
        "payload = sys.stdin.buffer.read()\n"
        "assert payload.startswith(b'%PDF-')\n"
        "json.dump({'regions': [{'box': {'x': 0.1, 'y': 0.2, 'width': 0.7, "
        "'height': 0.3}, 'text': 'OCR alpha commitment', 'confidence': 0.93}]}, sys.stdout)\n"
    )
    return (sys.executable, str(script))


def test_manifest_source_and_bounded_local_ocr_reach_reconciliation_review_and_search(
    tmp_path: Path,
) -> None:
    source = _local_manifest(tmp_path)
    transcriber = BoundedLocalOCRTranscriber(
        command=_ocr_command(tmp_path),
        name="local_ocr_test_engine",
        version="1.0",
    )
    pages = source.inventory(A)
    assert len(pages) == 1
    assert pages[0].representation_media_type == "application/pdf"
    regions = transcriber.transcribe(pages[0])
    assert regions[0].text == "OCR alpha commitment"

    repository = MemoryRepository()
    service = GoodNotesService()
    receipt = service.reconcile(
        principal_id=A,
        idempotency_key="local-source-v1",
        source=source,
        transcriber=transcriber,
        repository=repository,
    )
    region_id = next(region for owner, region in repository.regions if owner == A)
    proposal = repository.regions[(A, region_id)]
    assert receipt.page_version_ids == (proposal.page_version_id,)
    assert proposal.extractor == "local_ocr_test_engine"
    service.accept_region(
        principal_id=A,
        region_id=region_id,
        corrected_text="Reviewed local alpha commitment",
        decided_at=WHEN,
        repository=repository,
    )
    [hit] = repository.search(A, "reviewed local", limit=10)
    assert hit.page_number == 1
    assert hit.source_version_id == "ver_aaaaaaaaaaaaaaaaaaaaaaaa"


def test_local_source_refuses_digest_drift_and_path_escape(tmp_path: Path) -> None:
    drifted = _local_manifest(tmp_path, digest="0" * 64)
    with pytest.raises(GoodNotesLocalSourceError, match="digest changed"):
        drifted.inventory(A)
    with pytest.raises(GoodNotesLocalSourceError, match="relative"):
        ManifestGoodNotesSource(
            root=tmp_path,
            manifest_relative_path=PurePosixPath("../outside.json"),
        )


def test_local_source_refuses_an_intermediate_link(tmp_path: Path) -> None:
    source = _local_manifest(tmp_path)
    actual = tmp_path / "notebook"
    moved = tmp_path / "moved-notebook"
    actual.rename(moved)
    actual.symlink_to(moved, target_is_directory=True)
    with pytest.raises(GoodNotesLocalSourceError, match="unavailable"):
        source.inventory(A)


def test_local_ocr_refuses_unbounded_or_malformed_output(tmp_path: Path) -> None:
    source = _local_manifest(tmp_path)
    script = tmp_path / "bad-local-ocr.py"
    script.write_text("import sys; sys.stdin.buffer.read(); sys.stdout.write('not-json')\n")
    transcriber = BoundedLocalOCRTranscriber(
        command=(sys.executable, str(script)),
        name="bad_local_ocr",
        version="1",
    )
    with pytest.raises(GoodNotesTranscriptionError, match="result is invalid"):
        transcriber.transcribe(source.inventory(A)[0])

    script.write_text("import sys; sys.stdin.buffer.read(); sys.stdout.write('x' * 100)\n")
    bounded = BoundedLocalOCRTranscriber(
        command=(sys.executable, str(script)),
        name="overwide_local_ocr",
        version="1",
        maximum_output_bytes=10,
    )
    with pytest.raises(GoodNotesTranscriptionError, match="no admissible result"):
        bounded.transcribe(source.inventory(A)[0])


def test_production_goodnotes_composition_is_inert_until_called(tmp_path: Path) -> None:
    runtime = compose_local_goodnotes_runtime(
        admitted_root=tmp_path,
        manifest_relative_path=PurePosixPath("goodnotes-manifest.json"),
        ocr_command=(sys.executable, "/operator-supplied/local-ocr.py"),
        ocr_name="operator_local_ocr",
        ocr_version="1",
    )
    assert runtime.source.root == tmp_path.resolve()
    assert runtime.transcriber.command[0] == sys.executable
