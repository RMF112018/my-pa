from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from my_pa.application.goodnotes import (
    GoodNotesSearchHit,
    GoodNotesService,
    ReconciliationConflictError,
    ReconciliationReceipt,
    SourcePage,
    TranscribedRegion,
)
from my_pa.domain.goodnotes.models import (
    GoodNotesPage,
    GoodNotesPageVersion,
    GoodNotesRegionProposal,
)
from my_pa.infrastructure.goodnotes.fixture import FixtureGoodNotesSource, FixturePageTranscriber

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
