"""Insert-only persistence of context-run metadata.

The application port has no update or delete. A `BEFORE UPDATE OR DELETE`
trigger on both tables makes that a server property as well. Rows hold
identifiers and digests; they do not hold query text, conversation context, or
excerpt text.
"""

from __future__ import annotations

from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from my_pa.contracts.ports import ContextRunRepository, RepositoryFailureError
from my_pa.domain.context.run import ContextRunRecord
from my_pa.infrastructure.persistence.tables import context_run_items, context_runs

__all__ = ["SqlContextRunRepository"]


class SqlContextRunRepository(ContextRunRepository):
    """Write one context run and its items on the caller's connection."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def record(self, run: ContextRunRecord) -> None:
        """Insert the run and its items. Principal-partitioned; insert-only."""
        try:
            self._connection.execute(
                context_runs.insert().values(
                    context_manifest_id=run.context_manifest_id,
                    principal_id=run.principal_id,
                    request_id=run.request_id,
                    correlation_id=run.correlation_id,
                    audit_id=run.audit_id,
                    transport=run.transport,
                    purpose=run.purpose,
                    query_fingerprint=run.query_fingerprint,
                    retrieval_mode=run.retrieval_mode.value,
                    ranking_version=run.ranking_version,
                    policy_version=run.policy_version,
                    generated_at=run.generated_at,
                    total_items=run.total_items,
                    total_bytes=run.total_bytes,
                    duration_ms=run.duration_ms,
                    outcome=run.outcome,
                    truncated=run.truncated,
                    truncation_reason=run.truncation_reason,
                )
            )
            for item in run.items:
                self._connection.execute(
                    context_run_items.insert().values(
                        context_manifest_id=run.context_manifest_id,
                        position=item.position,
                        principal_id=item.principal_id,
                        reference_id=item.reference_id,
                        plane=item.plane.value,
                        authority_class=item.authority_class.value,
                        lifecycle=item.lifecycle.value,
                        classification=item.classification.value,
                        excerpt_sha256=item.excerpt_sha256,
                        reason_codes=item.reason_codes,
                        source_id=item.source_id,
                        source_object_id=item.source_object_id,
                        source_version_id=item.source_version_id,
                        knowledge_id=item.knowledge_id,
                        capture_id=item.capture_id,
                        capture_version_id=item.capture_version_id,
                        product_id=item.product_id,
                        managed_document_id=item.managed_document_id,
                        managed_document_version_id=item.managed_document_version_id,
                        span_start=item.span_start,
                        span_end=item.span_end,
                    )
                )
        except SQLAlchemyError:
            failure = RepositoryFailureError("the request could not be completed")
            raise failure from None
