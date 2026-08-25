"""Server-bound replay arbitration for Relationship Intelligence writes."""

from __future__ import annotations

from sqlalchemy import ColumnElement, Connection, Table, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from my_pa.contracts.ports import (
    RepositoryFailureError,
    WriteRequestConflictError,
    WriteRequestEvidence,
    WriteRequestRepository,
    WriteRequestResult,
)
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    relationship_write_request_evidence,
    relationship_write_requests,
)

__all__ = ["SqlWriteRequestRepository"]


def _mine(table: Table, principal_id: str) -> ColumnElement[bool]:
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Table, principal_id: str, values: dict[str, object]) -> dict[str, object]:
    return principal_bound_values(values, table, capture_context(principal_id))


class SqlWriteRequestRepository(WriteRequestRepository):
    """Reserve at the database unique and read back a concurrent winner."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def reserve(
        self,
        principal_id: str,
        capability: str,
        request_id: str,
        request_digest: str,
    ) -> WriteRequestResult | None:
        inserted = self._connection.execute(
            pg_insert(relationship_write_requests)
            .values(
                _bound(
                    relationship_write_requests,
                    principal_id,
                    {
                        "capability": capability,
                        "request_id": request_id,
                        "request_digest": request_digest,
                    },
                )
            )
            .on_conflict_do_nothing(
                index_elements=[
                    relationship_write_requests.c.principal_id,
                    relationship_write_requests.c.capability,
                    relationship_write_requests.c.request_id,
                ]
            )
            .returning(relationship_write_requests.c.request_id)
        ).first()
        if inserted is not None:
            return None

        row = self._connection.execute(
            select(relationship_write_requests).where(
                _mine(relationship_write_requests, principal_id),
                relationship_write_requests.c.capability == capability,
                relationship_write_requests.c.request_id == request_id,
            )
        ).one()
        if str(row.request_digest) != request_digest:
            raise WriteRequestConflictError
        if row.result_family is None or row.result_id is None or row.completed_at is None:
            # An ON CONFLICT loser waits for the winning transaction. Seeing its
            # row incomplete afterwards means stored state is inconsistent, not
            # a condition a caller can repair by changing its request.
            raise RepositoryFailureError
        evidence = tuple(
            WriteRequestEvidence(
                sequence=int(link.sequence),
                role=str(link.role),
                entity_observation_id=link.entity_observation_id,
                capture_span_id=link.capture_span_id,
                knowledge_id=link.knowledge_id,
            )
            for link in self._connection.execute(
                select(relationship_write_request_evidence)
                .where(
                    _mine(relationship_write_request_evidence, principal_id),
                    relationship_write_request_evidence.c.capability == capability,
                    relationship_write_request_evidence.c.request_id == request_id,
                )
                .order_by(relationship_write_request_evidence.c.sequence)
            )
        )
        return WriteRequestResult(
            result_family=str(row.result_family),
            result_id=str(row.result_id),
            result_secondary_id=row.result_secondary_id,
            result_version=row.result_version,
            result_state=row.result_state,
            result_subtype=row.result_subtype,
            result_requirement=row.result_requirement,
            result_disposition=row.result_disposition,
            result_assertion_id=row.result_assertion_id,
            result_classification=row.result_classification,
            result_method=row.result_method,
            result_at=row.result_at,
            result_digest=row.result_digest,
            result_count=row.result_count,
            result_created=row.result_created,
            receipt_id=row.receipt_id,
            audit_id=row.audit_id,
            evidence=evidence,
        )

    def complete(
        self,
        principal_id: str,
        capability: str,
        request_id: str,
        request_digest: str,
        result: WriteRequestResult,
    ) -> None:
        completed = self._connection.execute(
            update(relationship_write_requests)
            .where(
                _mine(relationship_write_requests, principal_id),
                relationship_write_requests.c.capability == capability,
                relationship_write_requests.c.request_id == request_id,
                relationship_write_requests.c.request_digest == request_digest,
                relationship_write_requests.c.completed_at.is_(None),
            )
            .values(
                result_family=result.result_family,
                result_id=result.result_id,
                result_secondary_id=result.result_secondary_id,
                result_version=result.result_version,
                result_state=result.result_state,
                result_subtype=result.result_subtype,
                result_requirement=result.result_requirement,
                result_disposition=result.result_disposition,
                result_assertion_id=result.result_assertion_id,
                result_classification=result.result_classification,
                result_method=result.result_method,
                result_at=result.result_at,
                result_digest=result.result_digest,
                result_count=result.result_count,
                result_created=result.result_created,
                receipt_id=result.receipt_id,
                audit_id=result.audit_id,
                completed_at=func.now(),
            )
            .returning(relationship_write_requests.c.request_id)
        ).first()
        if completed is None:
            raise RepositoryFailureError
        if result.evidence:
            self._connection.execute(
                insert(relationship_write_request_evidence),
                [
                    _bound(
                        relationship_write_request_evidence,
                        principal_id,
                        {
                            "capability": capability,
                            "request_id": request_id,
                            "sequence": link.sequence,
                            "role": link.role,
                            "entity_observation_id": link.entity_observation_id,
                            "capture_span_id": link.capture_span_id,
                            "knowledge_id": link.knowledge_id,
                        },
                    )
                    for link in result.evidence
                ],
            )
