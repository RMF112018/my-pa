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
    GoodNotesService,
    PageTranscriber,
    ReadOnlyGoodNotesSource,
    ReconciliationConflictError,
)
from my_pa.domain.goodnotes.models import ReconciliationReceipt
from my_pa.infrastructure.goodnotes.local import BoundedLocalOCRTranscriber, ManifestGoodNotesSource
from my_pa.infrastructure.persistence.goodnotes import PostgresGoodNotesRepository


@dataclass(frozen=True, slots=True)
class LocalGoodNotesRuntime:
    source: ReadOnlyGoodNotesSource
    transcriber: PageTranscriber

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
        # Short admission/receipt connection: exact registry + enrollment
        # identity is proven before OCR/model execution, then closed.
        with engine.connect() as connection:
            repository = PostgresGoodNotesRepository(connection)
            service.admit(plan, repository)
            prior = repository.receipt(principal_id, idempotency_key)
            service.require_within_deadline(plan)
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
        )
        # The durable transaction starts only after OCR and the proposal gate.
        with engine.begin() as connection:
            receipt = service.persist(prepared, PostgresGoodNotesRepository(connection))
            service.require_within_deadline(plan)
            return receipt


def compose_local_goodnotes_runtime(
    *,
    admitted_root: Path,
    manifest_relative_path: PurePosixPath,
    ocr_command: tuple[str, ...],
    ocr_name: str,
    ocr_version: str,
) -> LocalGoodNotesRuntime:
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
    )
