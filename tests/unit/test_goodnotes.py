from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import ClassVar

import pytest

from my_pa.application.goodnotes import (
    GoodNotesReconciliationLimits,
    GoodNotesService,
    GoodNotesSourceLiveness,
    GoodNotesSourceLivenessReceipt,
    ReconciliationConflictError,
    ReconciliationReceipt,
    SourcePage,
    TranscribedRegion,
)
from my_pa.bootstrap.goodnotes import compose_local_goodnotes_runtime
from my_pa.domain.goodnotes.models import (
    GoodNotesIdentityStatus,
    GoodNotesIngestionRun,
    GoodNotesIngestionStatus,
    GoodNotesIngestionTrigger,
    GoodNotesLogicalPage,
    GoodNotesMatchEvidence,
    GoodNotesMatchMethod,
    GoodNotesNotebook,
    GoodNotesNotebookPath,
    GoodNotesPage,
    GoodNotesPagePosition,
    GoodNotesPageVersion,
    GoodNotesRegionProposal,
    GoodNotesRenderFingerprint,
    issue_stable_id,
)
from my_pa.infrastructure.goodnotes.fixture import FixtureGoodNotesSource, FixturePageTranscriber
from my_pa.infrastructure.goodnotes.local import (
    BoundedLocalOCRTranscriber,
    GoodNotesLocalSourceError,
    GoodNotesTranscriptionError,
    LocalGoodNotesObserver,
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


@pytest.mark.parametrize("relative_path", ["goodnotes-manifest.json", "notebook/page-0001.pdf"])
def test_local_source_refuses_hardlinked_files(tmp_path: Path, relative_path: str) -> None:
    source = _local_manifest(tmp_path)
    original = tmp_path / relative_path
    alias = tmp_path / "synthetic-hardlink"
    os.link(original, alias)
    with pytest.raises(GoodNotesLocalSourceError, match="not a bounded file"):
        source.inventory(A)
    alias.unlink()
    assert len(source.inventory(A)) == 1


@pytest.mark.parametrize("relative_path", ["goodnotes-manifest.json", "notebook/page-0001.pdf"])
def test_local_source_refuses_a_link_added_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative_path: str
) -> None:
    source = _local_manifest(tmp_path)
    original = tmp_path / relative_path
    inode = original.stat().st_ino
    read = os.read
    linked = False

    def read_then_link(descriptor: int, size: int) -> bytes:
        nonlocal linked
        chunk = read(descriptor, size)
        if not linked and os.fstat(descriptor).st_ino == inode:
            os.link(original, tmp_path / "synthetic-midread-hardlink")
            linked = True
        return chunk

    monkeypatch.setattr(os, "read", read_then_link)
    with pytest.raises(GoodNotesLocalSourceError, match="digest changed"):
        source.inventory(A)
    assert linked


def test_local_observer_records_missing_then_reappeared_without_false_success(
    tmp_path: Path,
) -> None:
    relative_path = PurePosixPath("notebook/source.pdf")
    source_path = tmp_path / str(relative_path)
    source_path.parent.mkdir()
    source_path.write_bytes(b"%PDF-1.7\nfirst\n%%EOF\n")
    observed_at = datetime.now(UTC)
    observer = LocalGoodNotesObserver(root=tmp_path, source_root_id="icloud-goodnotes")

    available = observer.liveness(
        relative_path,
        checked_at=observed_at,
        maximum_staleness=timedelta(minutes=5),
    )
    assert available.state is GoodNotesSourceLiveness.AVAILABLE
    assert available.safe_to_ingest is True

    source_path.unlink()
    missing = observer.liveness(
        relative_path,
        checked_at=observed_at + timedelta(seconds=1),
        maximum_staleness=timedelta(minutes=5),
        previous=available,
    )
    assert missing.state is GoodNotesSourceLiveness.MISSING
    assert missing.safe_to_ingest is False
    assert missing.current_sha256 is None
    assert missing.prior_sha256 == available.current_sha256

    source_path.write_bytes(b"%PDF-1.7\nreplacement\n%%EOF\n")
    reappeared = observer.liveness(
        relative_path,
        checked_at=observed_at + timedelta(seconds=2),
        maximum_staleness=timedelta(minutes=5),
        previous=missing,
    )
    assert reappeared.state is GoodNotesSourceLiveness.REAPPEARED
    assert reappeared.safe_to_ingest is False
    assert reappeared.reappeared_content_changed is True
    assert reappeared.prior_sha256 == available.current_sha256


def test_unacknowledged_reappearance_remains_non_ingestible(tmp_path: Path) -> None:
    observer, relative_path, checked_at, available, reappeared = _reappeared_source(tmp_path)

    repeated = observer.liveness(
        relative_path,
        checked_at=checked_at + timedelta(seconds=3),
        maximum_staleness=timedelta(minutes=5),
        previous=reappeared,
    )
    assert repeated.state is GoodNotesSourceLiveness.REAPPEARED
    assert repeated.safe_to_ingest is False
    assert repeated.prior_sha256 == available.current_sha256


def test_reappearance_acknowledgment_requires_a_matching_prior_reappearance(
    tmp_path: Path,
) -> None:
    relative_path = PurePosixPath("notebook/source.pdf")
    source_path = tmp_path / str(relative_path)
    source_path.parent.mkdir()
    source_path.write_bytes(b"%PDF-1.7\nsynthetic\n%%EOF\n")
    checked_at = datetime.now(UTC)
    observer = LocalGoodNotesObserver(root=tmp_path, source_root_id="icloud-goodnotes")
    available = observer.liveness(
        relative_path,
        checked_at=checked_at,
        maximum_staleness=timedelta(minutes=5),
    )

    with pytest.raises(GoodNotesLocalSourceError, match="requires a prior reappearance"):
        observer.liveness(
            relative_path,
            checked_at=checked_at + timedelta(seconds=1),
            maximum_staleness=timedelta(minutes=5),
            previous=available,
            acknowledged_reappearance_sha256=available.current_sha256,
        )


def test_acknowledged_unchanged_reappearance_becomes_available(tmp_path: Path) -> None:
    observer, relative_path, checked_at, available, reappeared = _reappeared_source(tmp_path)

    acknowledged = observer.liveness(
        relative_path,
        checked_at=checked_at + timedelta(seconds=3),
        maximum_staleness=timedelta(minutes=5),
        previous=reappeared,
        acknowledged_reappearance_sha256=reappeared.current_sha256,
    )
    assert acknowledged.state is GoodNotesSourceLiveness.AVAILABLE
    assert acknowledged.safe_to_ingest is True
    assert acknowledged.current_sha256 == reappeared.current_sha256
    assert acknowledged.prior_sha256 == available.current_sha256


def test_acknowledged_reappearance_that_changed_again_remains_non_ingestible(
    tmp_path: Path,
) -> None:
    observer, relative_path, checked_at, available, reappeared = _reappeared_source(tmp_path)
    (tmp_path / str(relative_path)).write_bytes(b"%PDF-1.7\nchanged-again\n%%EOF\n")

    changed_again = observer.liveness(
        relative_path,
        checked_at=checked_at + timedelta(seconds=3),
        maximum_staleness=timedelta(minutes=5),
        previous=reappeared,
        acknowledged_reappearance_sha256=reappeared.current_sha256,
    )
    assert changed_again.state is GoodNotesSourceLiveness.REAPPEARED
    assert changed_again.safe_to_ingest is False
    assert changed_again.current_sha256 != reappeared.current_sha256
    assert changed_again.prior_sha256 == available.current_sha256


def _reappeared_source(
    tmp_path: Path,
) -> tuple[
    LocalGoodNotesObserver,
    PurePosixPath,
    datetime,
    GoodNotesSourceLivenessReceipt,
    GoodNotesSourceLivenessReceipt,
]:
    relative_path = PurePosixPath("notebook/source.pdf")
    source_path = tmp_path / str(relative_path)
    source_path.parent.mkdir()
    source_path.write_bytes(b"%PDF-1.7\nfirst\n%%EOF\n")
    checked_at = datetime.now(UTC)
    observer = LocalGoodNotesObserver(root=tmp_path, source_root_id="icloud-goodnotes")
    available = observer.liveness(
        relative_path,
        checked_at=checked_at,
        maximum_staleness=timedelta(minutes=5),
    )
    source_path.unlink()
    missing = observer.liveness(
        relative_path,
        checked_at=checked_at + timedelta(seconds=1),
        maximum_staleness=timedelta(minutes=5),
        previous=available,
    )
    source_path.write_bytes(b"%PDF-1.7\nreplacement\n%%EOF\n")
    reappeared = observer.liveness(
        relative_path,
        checked_at=checked_at + timedelta(seconds=2),
        maximum_staleness=timedelta(minutes=5),
        previous=missing,
    )
    return observer, relative_path, checked_at, available, reappeared


def test_local_observer_staleness_is_explicit_bounded_and_binding_safe(tmp_path: Path) -> None:
    relative_path = PurePosixPath("notebook/source.pdf")
    source_path = tmp_path / str(relative_path)
    source_path.parent.mkdir()
    source_path.write_bytes(b"%PDF-1.7\nsynthetic\n%%EOF\n")
    checked_at = datetime.now(UTC)
    observer = LocalGoodNotesObserver(root=tmp_path, source_root_id="icloud-goodnotes")

    available = observer.liveness(
        relative_path,
        checked_at=checked_at,
        maximum_staleness=timedelta(minutes=5),
    )
    source_path.unlink()
    stale = observer.liveness(
        relative_path,
        checked_at=checked_at + timedelta(minutes=6),
        maximum_staleness=timedelta(minutes=5),
        previous=available,
    )
    assert stale.state is GoodNotesSourceLiveness.STALE
    assert stale.safe_to_ingest is False
    with pytest.raises(GoodNotesLocalSourceError, match="binding changed"):
        observer.liveness(
            PurePosixPath("notebook/other.pdf"),
            checked_at=checked_at + timedelta(seconds=1),
            maximum_staleness=timedelta(minutes=5),
            previous=stale,
        )


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


def test_local_ocr_launch_failure_is_redacted(tmp_path: Path) -> None:
    source = _local_manifest(tmp_path)
    transcriber = BoundedLocalOCRTranscriber(
        command=(str(tmp_path / "synthetic-private-missing-executable"),),
        name="missing_local_ocr",
        version="1",
    )
    with pytest.raises(GoodNotesTranscriptionError) as caught:
        transcriber.transcribe(source.inventory(A)[0])
    assert str(caught.value) == "the local OCR command did not start"


def test_production_goodnotes_composition_is_inert_until_called(tmp_path: Path) -> None:
    runtime = compose_local_goodnotes_runtime(
        admitted_root=tmp_path,
        manifest_relative_path=PurePosixPath("goodnotes-manifest.json"),
        ocr_command=(sys.executable, "/operator-supplied/local-ocr.py"),
        ocr_root=tmp_path,
        ocr_name="operator_local_ocr",
        ocr_version="1",
    )
    assert runtime.source.root == tmp_path.resolve()
    assert runtime.transcriber.command[0] == sys.executable


def test_local_ocr_refuses_an_executable_symlink_escaping_its_root(tmp_path: Path) -> None:
    source = _local_manifest(tmp_path)
    ocr_root = tmp_path / "ocr-root"
    ocr_root.mkdir()
    escaped = ocr_root / "ocr"
    escaped.symlink_to(Path(sys.executable))
    transcriber = BoundedLocalOCRTranscriber(
        command=(str(escaped),),
        name="escaped_local_ocr",
        version="1",
        executable_root=ocr_root,
    )
    with pytest.raises(GoodNotesTranscriptionError, match="escaped its admitted root"):
        transcriber.transcribe(source.inventory(A)[0])


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


def test_goodnotes_operator_cli_accepts_only_the_partition_binding_argument() -> None:
    from apps.cli.goodnotes import build_parser

    parser = build_parser()
    arguments = parser.parse_args(["reconcile", "--idempotency-key", "x", "--principal-id", A])
    assert arguments.principal_id == A


def test_issue_stable_id_accepts_lineage_prefixes() -> None:
    notebook = issue_stable_id("gnnb", "synthetic", "notebook")
    snapshot = issue_stable_id("gnsnap", "synthetic", "snapshot")
    logical = issue_stable_id("gnlp", "synthetic", "page")
    run = issue_stable_id("gnrun", "synthetic", "run")
    note = issue_stable_id("gnnt", "synthetic", "note")
    occurrence = issue_stable_id("gnocc", "synthetic", "occurrence")
    revision = issue_stable_id("gnrev", "synthetic", "revision")
    link = issue_stable_id("gnlink", "synthetic", "link")
    change = issue_stable_id("gnchg", "synthetic", "change")
    assert notebook.startswith("gnnb_") and len(notebook) == 29
    assert snapshot.startswith("gnsnap_") and len(snapshot) == 31
    assert logical.startswith("gnlp_") and len(logical) == 29
    assert run.startswith("gnrun_") and len(run) == 30
    assert note.startswith("gnnt_") and len(note) == 29
    assert occurrence.startswith("gnocc_") and len(occurrence) == 30
    assert revision.startswith("gnrev_") and len(revision) == 30
    assert link.startswith("gnlink_") and len(link) == 31
    assert change.startswith("gnchg_") and len(change) == 30
    assert issue_stable_id("gnpg", "page") != notebook
    with pytest.raises(ValueError, match="unknown GoodNotes identity prefix"):
        issue_stable_id("gnxx", "synthetic")


def test_notebook_identity_is_not_a_path() -> None:
    notebook = GoodNotesNotebook(
        notebook_id=issue_stable_id("gnnb", "alpha"),
        principal_id=A,
        source_root_id="icloud-goodnotes",
        identity_status=GoodNotesIdentityStatus.ACTIVE,
        created_at=WHEN,
        last_observed_at=WHEN,
        label="Alpha",
    )
    assert "path" not in {item.name for item in fields(GoodNotesNotebook)}
    with pytest.raises(ValueError, match="not a filesystem path"):
        GoodNotesNotebook(
            notebook_id=notebook.notebook_id,
            principal_id=A,
            source_root_id="/Users/synthetic/GoodNotes",
            identity_status=GoodNotesIdentityStatus.ACTIVE,
            created_at=WHEN,
            last_observed_at=WHEN,
        )
    observed = GoodNotesNotebookPath(
        principal_id=A,
        notebook_id=notebook.notebook_id,
        path="Inbox/alpha.pdf",
        first_seen_at=WHEN,
        last_seen_at=WHEN,
        is_current=True,
    )
    assert observed.path != notebook.notebook_id
    with pytest.raises(ValueError, match="invalid gnnb identifier"):
        GoodNotesNotebook(
            notebook_id=issue_stable_id("gnpg", "not-a-notebook"),
            principal_id=A,
            source_root_id="icloud-goodnotes",
            identity_status=GoodNotesIdentityStatus.ACTIVE,
            created_at=WHEN,
            last_observed_at=WHEN,
        )


def test_logical_page_identity_has_no_page_number() -> None:
    page = GoodNotesLogicalPage(
        logical_page_id=issue_stable_id("gnlp", "alpha"),
        principal_id=A,
        notebook_id=issue_stable_id("gnnb", "alpha"),
        created_at=WHEN,
        last_seen_at=WHEN,
        identity_status=GoodNotesIdentityStatus.AMBIGUOUS,
    )
    assert "page_number" not in {item.name for item in fields(GoodNotesLogicalPage)}
    assert page.logical_page_id.startswith("gnlp_")
    position = GoodNotesPagePosition(
        principal_id=A,
        snapshot_id=issue_stable_id("gnsnap", "one"),
        page_number=3,
        logical_page_id=page.logical_page_id,
        created_at=WHEN,
        match_method=GoodNotesMatchMethod.UNRESOLVED,
    )
    assert position.page_number == 3
    later = GoodNotesPagePosition(
        principal_id=A,
        snapshot_id=issue_stable_id("gnsnap", "two"),
        page_number=1,
        logical_page_id=page.logical_page_id,
        created_at=WHEN,
        match_method=GoodNotesMatchMethod.EXACT_NORMALIZED_RENDER,
        match_confidence=1.0,
    )
    assert later.logical_page_id == position.logical_page_id
    assert later.page_number != position.page_number


def test_lineage_enums_and_optional_version_fingerprint_defaults() -> None:
    assert {member.value for member in GoodNotesIdentityStatus} == {
        "ACTIVE",
        "AMBIGUOUS",
        "RETIRED",
    }
    assert GoodNotesMatchMethod.ORDINAL_WEAK.value == "ORDINAL_WEAK"
    assert GoodNotesIngestionStatus.BUSY.value == "BUSY"
    assert GoodNotesIngestionTrigger.REPLAY.value == "REPLAY"
    version = GoodNotesPageVersion(
        page_version_id=issue_stable_id("gnver", "page"),
        page_id=issue_stable_id("gnpg", "page"),
        source_version_id="ver_aaaaaaaaaaaaaaaaaaaaaaaa",
        content_sha256="a" * 64,
        observed_at=WHEN,
    )
    assert version.logical_page_id is None
    assert version.exact_render_sha256 is None
    assert version.normalized_render_sha256 is None
    fingerprint = GoodNotesRenderFingerprint(
        normalized_render_sha256="b" * 64,
        perceptual_hash="phash-synthetic",
        render_width=1200,
        render_height=1600,
        renderer_name="synthetic",
        renderer_version="1",
        render_profile_version="v1",
    )
    assert fingerprint.render_width == 1200
    evidence = GoodNotesMatchEvidence(
        match_method=GoodNotesMatchMethod.SEQUENCE_TIEBREAK,
        confidence=0.5,
        prior_page_version_id=version.page_version_id,
    )
    assert evidence.prior_page_version_id == version.page_version_id
    run = GoodNotesIngestionRun(
        run_id=issue_stable_id("gnrun", "manual"),
        principal_id=A,
        source_root_id="icloud-goodnotes",
        trigger_type=GoodNotesIngestionTrigger.MANUAL,
        request_id="req-1",
        idempotency_key="req-1",
        request_fingerprint="c" * 64,
        started_at=WHEN,
        status=GoodNotesIngestionStatus.PENDING,
    )
    assert run.snapshot_count == 0
    assert run.ended_at is None
