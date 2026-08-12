from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import ClassVar

import pytest

from my_pa.application.goodnotes import (
    GoodNotesReconciliationLimits,
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

    def receipt(self, principal_id: str, idempotency_key: str) -> ReconciliationReceipt | None:
        return self.receipts.get((principal_id, idempotency_key))

    def require_admitted_sources(self, principal_id: str, bindings: tuple[object, ...]) -> None:
        if not bindings:
            raise ValueError("a reconciliation must bind at least one source version")

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
        def transcribe(
            self, page: SourcePage, *, timeout_seconds: float | None = None
        ) -> tuple[TranscribedRegion, ...]:
            del timeout_seconds
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


def test_manifest_source_and_bounded_local_ocr_reach_reconciliation(
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


def test_aggregate_bytes_regions_and_elapsed_time_are_fail_closed() -> None:
    two_pages = FixtureGoodNotesSource(
        pages=(
            replace(source().pages[0], content=b"123456"),
            replace(
                source().pages[0],
                source_object_id="obj_cccccccccccccccccccccccc",
                source_version_id="ver_cccccccccccccccccccccccc",
                page_number=2,
                content=b"abcdef",
            ),
        )
    )
    service = GoodNotesService(
        limits=GoodNotesReconciliationLimits(
            maximum_pages=2,
            maximum_page_bytes=10,
            maximum_aggregate_bytes=10,
        )
    )
    with pytest.raises(ValueError, match="aggregate byte"):
        service.plan(
            principal_id=A,
            idempotency_key="bounded",
            source=two_pages,
            transcriber=FixturePageTranscriber(),
        )

    times = iter((0.0, 2.0))
    timed = GoodNotesService(
        limits=GoodNotesReconciliationLimits(maximum_elapsed_seconds=1),
        monotonic=lambda: next(times),
    )
    with pytest.raises(TimeoutError, match="elapsed-time"):
        timed.plan(
            principal_id=A,
            idempotency_key="timed",
            source=source(),
            transcriber=FixturePageTranscriber(),
        )


def test_prepare_reuses_the_plan_deadline_instead_of_starting_a_second_window() -> None:
    times = iter((0.0, 0.1, 1.1))
    service = GoodNotesService(
        limits=GoodNotesReconciliationLimits(maximum_elapsed_seconds=1),
        monotonic=lambda: next(times),
    )
    plan = service.plan(
        principal_id=A,
        idempotency_key="one-deadline",
        source=source(),
        transcriber=FixturePageTranscriber(),
    )
    with pytest.raises(TimeoutError, match="elapsed-time"):
        service.prepare(
            plan=plan,
            source=source(),
            transcriber=FixturePageTranscriber(),
        )


def test_production_runtime_holds_no_database_connection_during_ocr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import my_pa.bootstrap.goodnotes as bootstrap

    class State:
        connected = False
        events: ClassVar[list[str]] = []

    state = State()

    class Context:
        def __init__(self, label: str) -> None:
            self.label = label

        def __enter__(self) -> object:
            assert not state.connected
            state.connected = True
            state.events.append(f"{self.label}-open")
            return object()

        def __exit__(self, *args: object) -> None:
            state.connected = False
            state.events.append(f"{self.label}-closed")

    class Engine:
        def connect(self) -> Context:
            return Context("receipt")

        def begin(self) -> Context:
            return Context("write")

    class Repository(MemoryRepository):
        def __init__(self, connection: object) -> None:
            super().__init__()

        def store_reconciliation(self, **kwargs: object) -> ReconciliationReceipt:
            assert state.connected
            return kwargs["receipt"]  # type: ignore[return-value]

    class Transcriber(FixturePageTranscriber):
        def transcribe(
            self, page: SourcePage, *, timeout_seconds: float | None = None
        ) -> tuple[TranscribedRegion, ...]:
            assert not state.connected
            state.events.append("ocr")
            return super().transcribe(page, timeout_seconds=timeout_seconds)

    monkeypatch.setattr(bootstrap, "PostgresGoodNotesRepository", Repository)
    composed = bootstrap.LocalGoodNotesRuntime(
        source=source(),
        transcriber=Transcriber(),
    )
    receipt = composed.reconcile(
        engine=Engine(), principal_id=A, idempotency_key="no-db-during-ocr"
    )
    assert receipt.created_regions == 1
    assert state.events == ["receipt-open", "receipt-closed", "ocr", "write-open", "write-closed"]


def test_goodnotes_operator_cli_never_accepts_a_principal_argument() -> None:
    from apps.cli.goodnotes import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "reconcile",
                "--idempotency-key",
                "x",
                "--principal",
                A,
            ]
        )
