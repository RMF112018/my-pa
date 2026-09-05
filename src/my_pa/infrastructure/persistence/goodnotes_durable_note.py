"""PostgreSQL durable-note store: lineage, stages, rasters, proposals, preview.

Composes existing Principal-scoped repositories. Does not duplicate SQL.
Not wired from gateway startup; a caller supplies the connection.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.engine import Connection

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import utc_now
from my_pa.domain.goodnotes.models import (
    GoodNotesDeliveryAttempt,
    GoodNotesDeliveryReceipt,
    GoodNotesEntityAssociation,
    GoodNotesEntityDirectoryRecord,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.goodnotes import PostgresGoodNotesRepository
from my_pa.infrastructure.persistence.goodnotes_delivery import PostgresGoodNotesDeliveryRepository
from my_pa.infrastructure.persistence.goodnotes_pull import _corrected_result_sha256
from my_pa.infrastructure.persistence.goodnotes_semantics import SqlGoodNotesSemanticRepository

__all__ = ["PostgresDurableNoteStore"]


class PostgresDurableNoteStore(PostgresGoodNotesRepository):
    """Production `GoodNotesDurableNoteStore` plus lineage/occurrence/delivery."""

    def __init__(self, connection: Connection) -> None:
        super().__init__(connection)
        self._delivery = PostgresGoodNotesDeliveryRepository(connection)
        self._semantics = SqlGoodNotesSemanticRepository(connection)

    def store_semantic_proposal(
        self,
        principal_id: str,
        run_id: str,
        page_version_id: str,
        schema_version: str,
        analyzer_name: str,
        analyzer_version: str,
        payload: dict[str, object],
    ) -> None:
        version = self.page_version(principal_id, page_version_id)
        if version is None:
            raise ValueError("the request names no stored GoodNotes page version")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        payload_digest = _corrected_result_sha256(payload)
        fingerprint = hashlib.sha256(
            f"{run_id}\x1f{page_version_id}\x1f{version.content_sha256}\x1f"
            f"{schema_version}\x1f{encoded}".encode()
        ).hexdigest()
        key = f"{run_id}:{page_version_id}"
        self._semantics.submit_proposal(
            principal_id=principal_id,
            run_id=run_id,
            page_version_id=page_version_id,
            content_sha256=version.content_sha256,
            schema_version=schema_version,
            analyzer_name=analyzer_name,
            analyzer_version=analyzer_version,
            idempotency_key=key,
            request_fingerprint=fingerprint,
            payload_sha256=payload_digest,
            payload=payload,
            correlation_id=issue_identifier(IdKind.CORRELATION),
            request_id=key,
            audit_id=issue_identifier(IdKind.AUDIT),
            created_at=utc_now(),
        )

    def entity_directory(self, principal_id: str) -> tuple[GoodNotesEntityDirectoryRecord, ...]:
        return self._delivery.entity_directory(principal_id)

    def store_entity_association(
        self, association: GoodNotesEntityAssociation
    ) -> GoodNotesEntityAssociation:
        return self._delivery.store_entity_association(association)

    def entity_associations_for_run(
        self, principal_id: str, run_id: str
    ) -> tuple[GoodNotesEntityAssociation, ...]:
        return self._delivery.entity_associations_for_run(principal_id, run_id)

    def store_delivery_receipt(self, receipt: GoodNotesDeliveryReceipt) -> GoodNotesDeliveryReceipt:
        return self._delivery.store_delivery_receipt(receipt)

    def delivery_receipt_by_key(
        self,
        principal_id: str,
        run_id: str,
        destination: str,
        summary_hash: str,
    ) -> GoodNotesDeliveryReceipt | None:
        return self._delivery.delivery_receipt_by_key(
            principal_id, run_id, destination, summary_hash
        )

    def delivery_receipts_for_run(
        self, principal_id: str, run_id: str
    ) -> tuple[GoodNotesDeliveryReceipt, ...]:
        return self._delivery.delivery_receipts_for_run(principal_id, run_id)

    def store_delivery_attempt(self, attempt: GoodNotesDeliveryAttempt) -> GoodNotesDeliveryAttempt:
        return self._delivery.store_delivery_attempt(attempt)

    def delivery_attempt(
        self, principal_id: str, attempt_id: str
    ) -> GoodNotesDeliveryAttempt | None:
        return self._delivery.delivery_attempt(principal_id, attempt_id)

    def delivery_attempts_for_token(
        self, principal_id: str, idempotency_token: str
    ) -> tuple[GoodNotesDeliveryAttempt, ...]:
        return self._delivery.delivery_attempts_for_token(principal_id, idempotency_token)
