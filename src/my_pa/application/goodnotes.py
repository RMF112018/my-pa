"""Bounded, read-only GoodNotes reconciliation and human disposition."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from my_pa.application.model_gate import BoundedModelGate, ModelGateOutcome, StructuredModelProvider
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.goodnotes.models import (
    GoodNotesPage,
    GoodNotesPageVersion,
    GoodNotesRegionProposal,
    ReconciliationReceipt,
    SourcePage,
    TranscribedRegion,
    issue_stable_id,
)
from my_pa.domain.modeling.gate import ContextEvidence, ContextManifest


class ReadOnlyGoodNotesSource(Protocol):
    def inventory(self, principal_id: str) -> Iterable[SourcePage]: ...


class _Digest(Protocol):
    def update(self, value: bytes) -> None: ...


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


@dataclass(frozen=True, slots=True)
class PreparedGoodNotesReconciliation:
    plan: ReconciliationPlan
    receipt: ReconciliationReceipt
    pages: tuple[GoodNotesPage, ...]
    versions: tuple[GoodNotesPageVersion, ...]
    regions: tuple[GoodNotesRegionProposal, ...]
    model_gate_states: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoodNotesModelProposalBoundary:
    gate: BoundedModelGate
    provider: StructuredModelProvider
    provider_id: str
    model_id: str
    prompt_schema_version: str = "goodnotes-region-v1"
    policy_version: str = "goodnotes-local-v1"

    def invoke(
        self,
        *,
        principal_id: str,
        source_page: SourcePage,
        region: GoodNotesRegionProposal,
    ) -> ModelGateOutcome:
        evidence = ContextEvidence(
            reference_id=region.region_id,
            principal_id=principal_id,
            source_id=source_page.source_id,
            source_object_id=source_page.source_object_id,
            source_version_id=source_page.source_version_id,
            text=region.transcription,
            span_start=0,
            span_end=len(region.transcription),
        )
        return self.gate.invoke(
            self.provider,
            ContextManifest(
                principal_id=principal_id,
                purpose="goodnotes_review_proposal",
                provider_id=self.provider_id,
                model_id=self.model_id,
                prompt_schema_version=self.prompt_schema_version,
                policy_version=self.policy_version,
                evidence=(evidence,),
                external_disclosure_allowed=False,
            ),
        )


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
            _update_fingerprint(digest, page)
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
        )

    def prepare(
        self,
        *,
        plan: ReconciliationPlan,
        source: ReadOnlyGoodNotesSource,
        transcriber: PageTranscriber,
        model_boundary: GoodNotesModelProposalBoundary | None = None,
    ) -> PreparedGoodNotesReconciliation:
        started = self._monotonic()
        fingerprint = hashlib.sha256(f"{transcriber.name}\x1f{transcriber.version}".encode())
        pages: list[GoodNotesPage] = []
        versions: list[GoodNotesPageVersion] = []
        regions: list[GoodNotesRegionProposal] = []
        model_states: list[str] = []
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
            transcribed = transcriber.transcribe(source_page)
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
                if model_boundary is not None:
                    model_states.append(
                        model_boundary.invoke(
                            principal_id=plan.principal_id,
                            source_page=source_page,
                            region=region,
                        ).state
                    )
                    self._check_elapsed(started)
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
            model_gate_states=tuple(model_states),
        )

    def persist(
        self,
        prepared: PreparedGoodNotesReconciliation,
        repository: GoodNotesRepository,
    ) -> ReconciliationReceipt:
        prior = repository.receipt(prepared.plan.principal_id, prepared.plan.idempotency_key)
        if prior is not None:
            return self._replay_or_conflict(prior, prepared.plan.request_fingerprint)
        return repository.store_reconciliation(
            receipt=prepared.receipt,
            pages=prepared.pages,
            versions=prepared.versions,
            regions=prepared.regions,
        )

    def reconcile(
        self,
        *,
        principal_id: str,
        idempotency_key: str,
        source: ReadOnlyGoodNotesSource,
        transcriber: PageTranscriber,
        repository: GoodNotesRepository,
        model_boundary: GoodNotesModelProposalBoundary | None = None,
    ) -> ReconciliationReceipt:
        plan = self.plan(
            principal_id=principal_id,
            idempotency_key=idempotency_key,
            source=source,
            transcriber=transcriber,
        )
        prior = repository.receipt(principal_id, idempotency_key)
        if prior is not None:
            return self._replay_or_conflict(prior, plan.request_fingerprint)
        return self.persist(
            self.prepare(
                plan=plan,
                source=source,
                transcriber=transcriber,
                model_boundary=model_boundary,
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
