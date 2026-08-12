"""Bounded, read-only GoodNotes reconciliation and human disposition."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Protocol

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.goodnotes.models import (
    GoodNotesPage,
    GoodNotesPageVersion,
    GoodNotesRegionProposal,
    GoodNotesSearchHit,
    ReconciliationReceipt,
    SourcePage,
    TranscribedRegion,
    issue_stable_id,
)


class ReadOnlyGoodNotesSource(Protocol):
    def inventory(self, principal_id: str) -> tuple[SourcePage, ...]: ...


class PageTranscriber(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def transcribe(self, page: SourcePage) -> tuple[TranscribedRegion, ...]: ...


class GoodNotesRepository(Protocol):
    def receipt(self, principal_id: str, idempotency_key: str) -> ReconciliationReceipt | None: ...

    def store_reconciliation(
        self,
        *,
        receipt: ReconciliationReceipt,
        pages: tuple[GoodNotesPage, ...],
        versions: tuple[GoodNotesPageVersion, ...],
        regions: tuple[GoodNotesRegionProposal, ...],
    ) -> ReconciliationReceipt: ...

    def decide_region(
        self,
        *,
        principal_id: str,
        region_id: str,
        disposition: str,
        corrected_text: str | None,
        decided_at: datetime,
    ) -> None: ...

    def search(
        self, principal_id: str, query: str, *, limit: int
    ) -> tuple[GoodNotesSearchHit, ...]: ...


class ReconciliationConflictError(ValueError):
    pass


class GoodNotesService:
    maximum_pages_per_reconciliation = 500

    def reconcile(
        self,
        *,
        principal_id: str,
        idempotency_key: str,
        source: ReadOnlyGoodNotesSource,
        transcriber: PageTranscriber,
        repository: GoodNotesRepository,
    ) -> ReconciliationReceipt:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if not idempotency_key or len(idempotency_key) > 200:
            raise ValueError("a bounded idempotency key is required")
        inventory = source.inventory(principal_id)
        if len(inventory) > self.maximum_pages_per_reconciliation:
            raise ValueError("the GoodNotes inventory exceeds the reconciliation bound")
        identity_keys = [(page.source_object_id, page.page_number) for page in inventory]
        if len(identity_keys) != len(set(identity_keys)):
            raise ValueError("the GoodNotes inventory repeats a page identity")
        if identity_keys != sorted(identity_keys):
            raise ValueError("the GoodNotes inventory is not canonically ordered")
        fingerprint = _inventory_fingerprint(inventory, transcriber)
        prior = repository.receipt(principal_id, idempotency_key)
        if prior is not None:
            if prior.request_fingerprint != fingerprint:
                raise ReconciliationConflictError(
                    "the idempotency key is already bound to another inventory"
                )
            return ReconciliationReceipt(
                receipt_id=prior.receipt_id,
                principal_id=prior.principal_id,
                idempotency_key=prior.idempotency_key,
                request_fingerprint=prior.request_fingerprint,
                page_version_ids=prior.page_version_ids,
                created_regions=prior.created_regions,
                replayed=True,
            )

        pages: list[GoodNotesPage] = []
        versions: list[GoodNotesPageVersion] = []
        regions: list[GoodNotesRegionProposal] = []
        for source_page in inventory:
            if source_page.principal_id != principal_id:
                raise ValueError("source inventory crossed its Principal boundary")
            digest = hashlib.sha256(source_page.content).hexdigest()
            page_id = issue_stable_id(
                "gnpg", source_page.source_object_id, str(source_page.page_number)
            )
            version_id = issue_stable_id(
                "gnver",
                page_id,
                source_page.source_version_id,
                source_page.representation_media_type,
                digest,
            )
            pages.append(
                GoodNotesPage(
                    page_id=page_id,
                    principal_id=principal_id,
                    source_id=source_page.source_id,
                    source_object_id=source_page.source_object_id,
                    page_number=source_page.page_number,
                )
            )
            versions.append(
                GoodNotesPageVersion(
                    page_version_id=version_id,
                    page_id=page_id,
                    source_version_id=source_page.source_version_id,
                    content_sha256=digest,
                    observed_at=source_page.observed_at,
                )
            )
            for ordinal, region in enumerate(transcriber.transcribe(source_page)):
                regions.append(
                    GoodNotesRegionProposal(
                        region_id=issue_stable_id("gnreg", version_id, str(ordinal)),
                        page_version_id=version_id,
                        ordinal=ordinal,
                        box=region.box,
                        transcription=region.text,
                        confidence=region.confidence,
                        extractor=transcriber.name,
                        extractor_version=transcriber.version,
                    )
                )
        receipt = ReconciliationReceipt(
            receipt_id=issue_stable_id("gnrec", principal_id, idempotency_key, fingerprint),
            principal_id=principal_id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            page_version_ids=tuple(version.page_version_id for version in versions),
            created_regions=len(regions),
        )
        return repository.store_reconciliation(
            receipt=receipt,
            pages=tuple(pages),
            versions=tuple(versions),
            regions=tuple(regions),
        )

    def accept_region(
        self,
        *,
        principal_id: str,
        region_id: str,
        corrected_text: str | None,
        decided_at: datetime,
        repository: GoodNotesRepository,
    ) -> None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if corrected_text is not None and (
            not corrected_text.strip() or len(corrected_text) > 20_000
        ):
            raise ValueError("corrected text must be non-empty and bounded")
        repository.decide_region(
            principal_id=principal_id,
            region_id=region_id,
            disposition="corrected_accepted" if corrected_text is not None else "accepted",
            corrected_text=corrected_text,
            decided_at=decided_at,
        )


def _inventory_fingerprint(inventory: tuple[SourcePage, ...], transcriber: PageTranscriber) -> str:
    digest = hashlib.sha256()
    digest.update(f"{transcriber.name}\x1f{transcriber.version}".encode())
    for page in inventory:
        digest.update(
            f"{page.principal_id}\x1f{page.source_id}\x1f{page.source_object_id}\x1f"
            f"{page.source_version_id}\x1f{page.page_number}\x1f"
            f"{page.representation_media_type}\x1f".encode()
        )
        digest.update(hashlib.sha256(page.content).digest())
    return digest.hexdigest()
