"""Production composition for an explicitly admitted local GoodNotes source.

Construction is inert.  The engine-based reconciliation deliberately closes
the receipt transaction before any OCR/model work and opens the write
transaction only after all bounded external work has completed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy.engine import Engine

from my_pa.application.goodnotes import (
    GoodNotesModelProposalBoundary,
    GoodNotesService,
    PageTranscriber,
    ReadOnlyGoodNotesSource,
    ReconciliationConflictError,
)
from my_pa.application.model_gate import BoundedModelGate
from my_pa.domain.goodnotes.models import ReconciliationReceipt
from my_pa.domain.modeling.gate import ContextManifest, ModelProposal, ModelRoutePolicy
from my_pa.infrastructure.goodnotes.local import BoundedLocalOCRTranscriber, ManifestGoodNotesSource
from my_pa.infrastructure.persistence.goodnotes import PostgresGoodNotesRepository


@dataclass(slots=True)
class _DisabledLocalProvider:
    provider_id: str = "goodnotes_local_disabled"
    model_id: str = "none"
    is_external: bool = False

    def propose(self, manifest: ContextManifest) -> tuple[ModelProposal, ...]:
        raise RuntimeError("a disabled model provider cannot be invoked")


@dataclass(frozen=True, slots=True)
class LocalGoodNotesRuntime:
    source: ReadOnlyGoodNotesSource
    transcriber: PageTranscriber
    model_boundary: GoodNotesModelProposalBoundary

    def reconcile(
        self,
        *,
        engine: Engine,
        principal_id: str,
        idempotency_key: str,
    ) -> ReconciliationReceipt:
        service = GoodNotesService()
        plan = service.plan(
            principal_id=principal_id,
            idempotency_key=idempotency_key,
            source=self.source,
            transcriber=self.transcriber,
        )
        # Short receipt-only connection: closed before OCR/model execution.
        with engine.connect() as connection:
            prior = PostgresGoodNotesRepository(connection).receipt(principal_id, idempotency_key)
        if prior is not None:
            if prior.request_fingerprint != plan.request_fingerprint:
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
        prepared = service.prepare(
            plan=plan,
            source=self.source,
            transcriber=self.transcriber,
            model_boundary=self.model_boundary,
        )
        # The durable transaction starts only after OCR and the proposal gate.
        with engine.begin() as connection:
            return service.persist(prepared, PostgresGoodNotesRepository(connection))


def compose_local_goodnotes_runtime(
    *,
    admitted_root: Path,
    manifest_relative_path: PurePosixPath,
    ocr_command: tuple[str, ...],
    ocr_name: str,
    ocr_version: str,
) -> LocalGoodNotesRuntime:
    provider = _DisabledLocalProvider()
    return LocalGoodNotesRuntime(
        source=ManifestGoodNotesSource(
            root=admitted_root,
            manifest_relative_path=manifest_relative_path,
        ),
        transcriber=BoundedLocalOCRTranscriber(
            command=ocr_command,
            name=ocr_name,
            version=ocr_version,
        ),
        model_boundary=GoodNotesModelProposalBoundary(
            gate=BoundedModelGate(route=ModelRoutePolicy.DISABLED),
            provider=provider,
            provider_id=provider.provider_id,
            model_id=provider.model_id,
        ),
    )
