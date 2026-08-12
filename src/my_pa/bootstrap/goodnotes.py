"""Production composition for an explicitly admitted local GoodNotes source.

Construction is inert: it validates configuration and creates adapters, but it
does not enumerate a root, execute OCR, open a database connection, or activate
a watcher.  The caller supplies the admitted root, manifest, and exact local OCR
command; there is no live default.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy.engine import Connection

from my_pa.application.goodnotes import GoodNotesService
from my_pa.domain.goodnotes.models import GoodNotesSearchHit, ReconciliationReceipt
from my_pa.infrastructure.goodnotes.local import (
    BoundedLocalOCRTranscriber,
    ManifestGoodNotesSource,
)
from my_pa.infrastructure.persistence.goodnotes import PostgresGoodNotesRepository


@dataclass(frozen=True, slots=True)
class LocalGoodNotesRuntime:
    source: ManifestGoodNotesSource
    transcriber: BoundedLocalOCRTranscriber

    def reconcile(
        self,
        *,
        connection: Connection,
        principal_id: str,
        idempotency_key: str,
    ) -> ReconciliationReceipt:
        return GoodNotesService().reconcile(
            principal_id=principal_id,
            idempotency_key=idempotency_key,
            source=self.source,
            transcriber=self.transcriber,
            repository=PostgresGoodNotesRepository(connection),
        )

    def search(
        self,
        *,
        connection: Connection,
        principal_id: str,
        query: str,
        limit: int,
    ) -> tuple[GoodNotesSearchHit, ...]:
        return PostgresGoodNotesRepository(connection).search(principal_id, query, limit=limit)


def compose_local_goodnotes_runtime(
    *,
    admitted_root: Path,
    manifest_relative_path: PurePosixPath,
    ocr_command: tuple[str, ...],
    ocr_name: str,
    ocr_version: str,
) -> LocalGoodNotesRuntime:
    """Compose, but do not activate, the local read/OCR/reconciliation path."""

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
