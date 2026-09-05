"""Bounded, read-only GoodNotes reconciliation and human disposition."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.goodnotes.liveness import (
    GoodNotesSourceLiveness as GoodNotesSourceLiveness,
)
from my_pa.domain.goodnotes.liveness import (
    GoodNotesSourceLivenessReceipt as GoodNotesSourceLivenessReceipt,
)
from my_pa.domain.goodnotes.models import (
    GoodNotesPage,
    GoodNotesPageVersion,
    GoodNotesRegionProposal,
    GoodNotesSourceBinding,
    ReconciliationReceipt,
    SourcePage,
    TranscribedRegion,
    issue_stable_id,
)


class ReadOnlyGoodNotesSource(Protocol):
    def inventory(self, principal_id: str) -> Iterable[SourcePage]: ...


class _Digest(Protocol):
    def update(self, value: bytes) -> None: ...


class PageTranscriber(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def transcribe(
        self, page: SourcePage, *, timeout_seconds: float
    ) -> tuple[TranscribedRegion, ...]: ...


class GoodNotesRepository(Protocol):
    def receipt(self, principal_id: str, idempotency_key: str) -> ReconciliationReceipt | None: ...

    def require_admitted_sources(
        self, principal_id: str, bindings: tuple[GoodNotesSourceBinding, ...]
    ) -> None: ...

    def store_reconciliation(
        self,
        *,
        receipt: ReconciliationReceipt,
        pages: tuple[GoodNotesPage, ...],
        versions: tuple[GoodNotesPageVersion, ...],
        regions: tuple[GoodNotesRegionProposal, ...],
    ) -> ReconciliationReceipt: ...


def require_available_liveness(
    receipt: GoodNotesSourceLivenessReceipt,
    *,
    source_root_id: str,
    relative_path: str,
    content_sha256: str,
    at: datetime,
) -> None:
    """Bind settled bytes to an AVAILABLE server observation before ingestion."""
    if not isinstance(receipt, GoodNotesSourceLivenessReceipt):
        raise TypeError("a server-generated GoodNotes liveness receipt is required")
    if not receipt.safe_to_ingest:
        raise ValueError("the GoodNotes source is not available for ingestion")
    if (
        receipt.source_root_id != source_root_id
        or receipt.relative_path != relative_path
        or receipt.current_sha256 != content_sha256
    ):
        raise ValueError("the GoodNotes liveness receipt does not match the settled source")
    age = (at - receipt.checked_at).total_seconds()
    if age < 0 or age > receipt.maximum_staleness_seconds:
        raise ValueError("the GoodNotes liveness receipt is stale")


class ReconciliationConflictError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GoodNotesReconciliationLimits:
    maximum_pages: int = 100
    maximum_page_bytes: int = 25 * 1_048_576
    maximum_aggregate_bytes: int = 100 * 1_048_576
    maximum_regions_per_page: int = 250
    maximum_aggregate_regions: int = 2_000
    maximum_aggregate_transcription_chars: int = 2_000_000
    maximum_elapsed_seconds: float = 300.0

    def __post_init__(self) -> None:
        if not 1 <= self.maximum_pages <= 500:
            raise ValueError("the GoodNotes page bound is invalid")
        if not 1 <= self.maximum_page_bytes <= 25 * 1_048_576:
            raise ValueError("the GoodNotes page byte bound is invalid")
        if not self.maximum_page_bytes <= self.maximum_aggregate_bytes <= 500 * 1_048_576:
            raise ValueError("the GoodNotes aggregate byte bound is invalid")
        if not 1 <= self.maximum_regions_per_page <= 250:
            raise ValueError("the GoodNotes per-page region bound is invalid")
        if not self.maximum_regions_per_page <= self.maximum_aggregate_regions <= 10_000:
            raise ValueError("the GoodNotes aggregate region bound is invalid")
        if not 1 <= self.maximum_aggregate_transcription_chars <= 5_000_000:
            raise ValueError("the GoodNotes transcription bound is invalid")
        if not 1 <= self.maximum_elapsed_seconds <= 600:
            raise ValueError("the GoodNotes elapsed-time bound is invalid")


@dataclass(frozen=True, slots=True)
class ReconciliationPlan:
    principal_id: str
    idempotency_key: str
    request_fingerprint: str
    page_count: int
    aggregate_bytes: int
    source_bindings: tuple[GoodNotesSourceBinding, ...]
    started_at_monotonic: float


@dataclass(frozen=True, slots=True)
class PreparedGoodNotesReconciliation:
    plan: ReconciliationPlan
    receipt: ReconciliationReceipt
    pages: tuple[GoodNotesPage, ...]
    versions: tuple[GoodNotesPageVersion, ...]
    regions: tuple[GoodNotesRegionProposal, ...]


class GoodNotesService:
    def __init__(
        self,
        *,
        limits: GoodNotesReconciliationLimits | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limits = limits or GoodNotesReconciliationLimits()
        self._monotonic = monotonic

    def plan(
        self,
        *,
        principal_id: str,
        idempotency_key: str,
        source: ReadOnlyGoodNotesSource,
        transcriber: PageTranscriber,
    ) -> ReconciliationPlan:
        self._validate_request(principal_id, idempotency_key)
        started = self._monotonic()
        digest = hashlib.sha256(f"{transcriber.name}\x1f{transcriber.version}".encode())
        identities: list[tuple[str, int]] = []
        source_bindings: set[GoodNotesSourceBinding] = set()
        aggregate_bytes = 0
        count = 0
        for page in _inventory(source, principal_id):
            self._check_elapsed(started)
            self._validate_page(page, principal_id)
            count += 1
            if count > self.limits.maximum_pages:
                raise ValueError("the GoodNotes inventory exceeds the page bound")
            if len(page.content) > self.limits.maximum_page_bytes:
                raise ValueError("a GoodNotes page exceeds the byte bound")
            aggregate_bytes += len(page.content)
            if aggregate_bytes > self.limits.maximum_aggregate_bytes:
                raise ValueError("the GoodNotes inventory exceeds the aggregate byte bound")
            identities.append((page.source_object_id, page.page_number))
            source_bindings.add(
                GoodNotesSourceBinding(
                    source_id=page.source_id,
                    source_object_id=page.source_object_id,
                    source_version_id=page.source_version_id,
                )
            )
            _update_fingerprint(digest, page)
        if count == 0:
            raise ValueError("the GoodNotes inventory contains no admitted page")
        if len(identities) != len(set(identities)):
            raise ValueError("the GoodNotes inventory repeats a page identity")
        if identities != sorted(identities):
            raise ValueError("the GoodNotes inventory is not canonically ordered")
        return ReconciliationPlan(
            principal_id=principal_id,
            idempotency_key=idempotency_key,
            request_fingerprint=digest.hexdigest(),
            page_count=count,
            aggregate_bytes=aggregate_bytes,
            source_bindings=tuple(sorted(source_bindings)),
            started_at_monotonic=started,
        )

    @staticmethod
    def admit(plan: ReconciliationPlan, repository: GoodNotesRepository) -> None:
        """Fail closed unless registry identity and Principal enrollment match.

        Ordinary knowledge search is enrollment-scoped and reads accepted
        GoodNotes text as ``text/plain``. Therefore an exact manifest version
        is eligible only when its source/object relation exists and this
        Principal has enrolled that object with ``text/plain`` admitted.
        """
        repository.require_admitted_sources(plan.principal_id, plan.source_bindings)

    def require_within_deadline(self, plan: ReconciliationPlan) -> None:
        """Apply the one reconciliation deadline across plan, OCR, and persistence."""
        self._check_elapsed(plan.started_at_monotonic)

    def prepare(
        self,
        *,
        plan: ReconciliationPlan,
        source: ReadOnlyGoodNotesSource,
        transcriber: PageTranscriber,
    ) -> PreparedGoodNotesReconciliation:
        started = plan.started_at_monotonic
        fingerprint = hashlib.sha256(f"{transcriber.name}\x1f{transcriber.version}".encode())
        pages: list[GoodNotesPage] = []
        versions: list[GoodNotesPageVersion] = []
        regions: list[GoodNotesRegionProposal] = []
        aggregate_bytes = 0
        transcription_chars = 0
        for source_page in _inventory(source, plan.principal_id):
            self._check_elapsed(started)
            self._validate_page(source_page, plan.principal_id)
            aggregate_bytes += len(source_page.content)
            if (
                len(pages) >= self.limits.maximum_pages
                or aggregate_bytes > self.limits.maximum_aggregate_bytes
            ):
                raise ValueError("the GoodNotes inventory changed beyond its bound")
            _update_fingerprint(fingerprint, source_page)
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
            page = GoodNotesPage(
                page_id=page_id,
                principal_id=plan.principal_id,
                source_id=source_page.source_id,
                source_object_id=source_page.source_object_id,
                page_number=source_page.page_number,
            )
            version = GoodNotesPageVersion(
                page_version_id=version_id,
                page_id=page_id,
                source_version_id=source_page.source_version_id,
                content_sha256=digest,
                observed_at=source_page.observed_at,
            )
            remaining = self.limits.maximum_elapsed_seconds - (self._monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("the GoodNotes reconciliation exceeded its elapsed-time bound")
            transcribed = transcriber.transcribe(source_page, timeout_seconds=remaining)
            self._check_elapsed(started)
            if len(transcribed) > self.limits.maximum_regions_per_page:
                raise ValueError("a GoodNotes page exceeds the region bound")
            if len(regions) + len(transcribed) > self.limits.maximum_aggregate_regions:
                raise ValueError("the GoodNotes inventory exceeds the aggregate region bound")
            pages.append(page)
            versions.append(version)
            for ordinal, raw_region in enumerate(transcribed):
                transcription_chars += len(raw_region.text)
                if transcription_chars > self.limits.maximum_aggregate_transcription_chars:
                    raise ValueError("GoodNotes transcription exceeds the aggregate text bound")
                region = GoodNotesRegionProposal(
                    region_id=issue_stable_id("gnreg", version_id, str(ordinal)),
                    page_version_id=version_id,
                    ordinal=ordinal,
                    box=raw_region.box,
                    transcription=raw_region.text,
                    confidence=raw_region.confidence,
                    extractor=transcriber.name,
                    extractor_version=transcriber.version,
                )
                regions.append(region)
        if (
            fingerprint.hexdigest() != plan.request_fingerprint
            or len(pages) != plan.page_count
            or aggregate_bytes != plan.aggregate_bytes
        ):
            raise ReconciliationConflictError("the source inventory changed during reconciliation")
        receipt = ReconciliationReceipt(
            receipt_id=issue_stable_id(
                "gnrec", plan.principal_id, plan.idempotency_key, plan.request_fingerprint
            ),
            principal_id=plan.principal_id,
            idempotency_key=plan.idempotency_key,
            request_fingerprint=plan.request_fingerprint,
            page_version_ids=tuple(version.page_version_id for version in versions),
            created_regions=len(regions),
        )
        return PreparedGoodNotesReconciliation(
            plan=plan,
            receipt=receipt,
            pages=tuple(pages),
            versions=tuple(versions),
            regions=tuple(regions),
        )

    def persist(
        self,
        prepared: PreparedGoodNotesReconciliation,
        repository: GoodNotesRepository,
    ) -> ReconciliationReceipt:
        self.require_within_deadline(prepared.plan)
        self.admit(prepared.plan, repository)
        prior = repository.receipt(prepared.plan.principal_id, prepared.plan.idempotency_key)
        if prior is not None:
            return self._replay_or_conflict(prior, prepared.plan.request_fingerprint)
        receipt = repository.store_reconciliation(
            receipt=prepared.receipt,
            pages=prepared.pages,
            versions=prepared.versions,
            regions=prepared.regions,
        )
        self.require_within_deadline(prepared.plan)
        return receipt

    def reconcile(
        self,
        *,
        principal_id: str,
        idempotency_key: str,
        source: ReadOnlyGoodNotesSource,
        transcriber: PageTranscriber,
        repository: GoodNotesRepository,
    ) -> ReconciliationReceipt:
        plan = self.plan(
            principal_id=principal_id,
            idempotency_key=idempotency_key,
            source=source,
            transcriber=transcriber,
        )
        self.admit(plan, repository)
        prior = repository.receipt(principal_id, idempotency_key)
        if prior is not None:
            return self._replay_or_conflict(prior, plan.request_fingerprint)
        return self.persist(
            self.prepare(
                plan=plan,
                source=source,
                transcriber=transcriber,
            ),
            repository,
        )

    def _validate_request(self, principal_id: str, idempotency_key: str) -> None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if not idempotency_key or len(idempotency_key) > 200:
            raise ValueError("a bounded idempotency key is required")

    @staticmethod
    def _validate_page(page: SourcePage, principal_id: str) -> None:
        if page.principal_id != principal_id:
            raise ValueError("source inventory crossed its Principal boundary")

    def _check_elapsed(self, started: float) -> None:
        if self._monotonic() - started > self.limits.maximum_elapsed_seconds:
            raise TimeoutError("the GoodNotes reconciliation exceeded its elapsed-time bound")

    @staticmethod
    def _replay_or_conflict(
        prior: ReconciliationReceipt, fingerprint: str
    ) -> ReconciliationReceipt:
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


def _update_fingerprint(digest: _Digest, page: SourcePage) -> None:
    digest.update(
        f"{page.principal_id}\x1f{page.source_id}\x1f{page.source_object_id}\x1f"
        f"{page.source_version_id}\x1f{page.page_number}\x1f"
        f"{page.representation_media_type}\x1f".encode()
    )
    digest.update(hashlib.sha256(page.content).digest())


def _inventory(source: ReadOnlyGoodNotesSource, principal_id: str) -> Iterable[SourcePage]:
    streaming = getattr(source, "stream_inventory", None)
    return source.inventory(principal_id) if streaming is None else streaming(principal_id)
