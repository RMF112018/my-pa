"""Principal-bound GoodNotes page-version work and semantic proposal receipts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ColumnElement, Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from my_pa.contracts.ports import (
    GoodNotesProposalAdmission,
    GoodNotesProposalConflictError,
    GoodNotesSemanticRepository,
    RepositoryFailureError,
)
from my_pa.domain.goodnotes.models import (
    GoodNotesPageRaster,
    GoodNotesPageWork,
    GoodNotesSemanticProposal,
    issue_stable_id,
)
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    goodnotes_ingestion_runs,
    goodnotes_page_positions,
    goodnotes_page_rasters,
    goodnotes_page_versions,
    goodnotes_semantic_proposals,
    goodnotes_source_snapshots,
)

__all__ = ["SqlGoodNotesSemanticRepository"]


def _mine(table: Table, principal_id: str) -> ColumnElement[bool]:
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Table, principal_id: str, values: dict[str, object]) -> dict[str, object]:
    return principal_bound_values(values, table, capture_context(principal_id))


def _work_from_row(row: object) -> GoodNotesPageWork:
    mapping = row._mapping  # type: ignore[attr-defined]
    return GoodNotesPageWork(
        run_id=str(mapping["run_id"]),
        page_version_id=str(mapping["page_version_id"]),
        principal_id=str(mapping["principal_id"]),
        content_sha256=str(mapping["content_sha256"]),
        logical_page_id=(
            None if mapping["logical_page_id"] is None else str(mapping["logical_page_id"])
        ),
        renderer_name=None if mapping["renderer_name"] is None else str(mapping["renderer_name"]),
        renderer_version=(
            None if mapping["renderer_version"] is None else str(mapping["renderer_version"])
        ),
        render_profile_version=(
            None
            if mapping["render_profile_version"] is None
            else str(mapping["render_profile_version"])
        ),
    )


def _proposal_from_row(row: object, *, replayed: bool) -> GoodNotesSemanticProposal:
    mapping = row._mapping  # type: ignore[attr-defined]
    return GoodNotesSemanticProposal(
        proposal_id=str(mapping["proposal_id"]),
        principal_id=str(mapping["principal_id"]),
        run_id=str(mapping["run_id"]),
        page_version_id=str(mapping["page_version_id"]),
        content_sha256=str(mapping["content_sha256"]),
        schema_version=str(mapping["schema_version"]),
        analyzer_name=str(mapping["analyzer_name"]),
        analyzer_version=str(mapping["analyzer_version"]),
        idempotency_key=str(mapping["idempotency_key"]),
        request_fingerprint=str(mapping["request_fingerprint"]),
        payload_sha256=str(mapping["payload_sha256"]),
        created_at=mapping["created_at"],
        replayed=replayed,
    )


def _raster_from_row(row: object) -> GoodNotesPageRaster:
    mapping = row._mapping  # type: ignore[attr-defined]
    payload = bytes(mapping["png_bytes"])
    return GoodNotesPageRaster(
        principal_id=str(mapping["principal_id"]),
        page_version_id=str(mapping["page_version_id"]),
        run_id=str(mapping["run_id"]),
        exact_render_sha256=str(mapping["exact_render_sha256"]),
        png_sha256=str(mapping["png_sha256"]),
        byte_length=int(mapping["byte_length"]),
        png_bytes=payload,
        renderer_name=str(mapping["renderer_name"]),
        renderer_version=str(mapping["renderer_version"]),
        render_profile_version=str(mapping["render_profile_version"]),
        created_at=mapping["created_at"],
        media_type=str(mapping["media_type"]),
    )


class SqlGoodNotesSemanticRepository(GoodNotesSemanticRepository):
    """Page-version work and insert-only proposal receipts on the caller's connection."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def page_work(
        self, principal_id: str, run_id: str, page_version_id: str
    ) -> GoodNotesPageWork | None:
        try:
            row = self._connection.execute(
                select(
                    goodnotes_ingestion_runs.c.run_id,
                    goodnotes_page_versions.c.page_version_id,
                    goodnotes_page_versions.c.principal_id,
                    goodnotes_page_versions.c.content_sha256,
                    goodnotes_page_versions.c.logical_page_id,
                    goodnotes_page_versions.c.renderer_name,
                    goodnotes_page_versions.c.renderer_version,
                    goodnotes_page_versions.c.render_profile_version,
                )
                .select_from(
                    goodnotes_ingestion_runs.join(
                        goodnotes_source_snapshots,
                        (_mine(goodnotes_source_snapshots, principal_id))
                        & (
                            goodnotes_source_snapshots.c.run_id == goodnotes_ingestion_runs.c.run_id
                        ),
                    )
                    .join(
                        goodnotes_page_positions,
                        (_mine(goodnotes_page_positions, principal_id))
                        & (
                            goodnotes_page_positions.c.snapshot_id
                            == goodnotes_source_snapshots.c.snapshot_id
                        ),
                    )
                    .join(
                        goodnotes_page_versions,
                        (_mine(goodnotes_page_versions, principal_id))
                        & (
                            goodnotes_page_versions.c.page_version_id
                            == goodnotes_page_positions.c.page_version_id
                        ),
                    )
                )
                .where(
                    _mine(goodnotes_ingestion_runs, principal_id),
                    goodnotes_ingestion_runs.c.run_id == run_id,
                    goodnotes_page_versions.c.page_version_id == page_version_id,
                )
            ).one_or_none()
        except SQLAlchemyError:
            failure = RepositoryFailureError("the request could not be completed")
            raise failure from None
        return None if row is None else _work_from_row(row)

    def page_raster(
        self, principal_id: str, run_id: str, page_version_id: str
    ) -> GoodNotesPageRaster | None:
        try:
            row = self._connection.execute(
                select(goodnotes_page_rasters)
                .select_from(
                    goodnotes_page_rasters.join(
                        goodnotes_ingestion_runs,
                        (_mine(goodnotes_ingestion_runs, principal_id))
                        & (goodnotes_ingestion_runs.c.run_id == goodnotes_page_rasters.c.run_id),
                    )
                    .join(
                        goodnotes_source_snapshots,
                        (_mine(goodnotes_source_snapshots, principal_id))
                        & (
                            goodnotes_source_snapshots.c.run_id == goodnotes_ingestion_runs.c.run_id
                        ),
                    )
                    .join(
                        goodnotes_page_positions,
                        (_mine(goodnotes_page_positions, principal_id))
                        & (
                            goodnotes_page_positions.c.snapshot_id
                            == goodnotes_source_snapshots.c.snapshot_id
                        )
                        & (
                            goodnotes_page_positions.c.page_version_id
                            == goodnotes_page_rasters.c.page_version_id
                        ),
                    )
                )
                .where(
                    _mine(goodnotes_page_rasters, principal_id),
                    goodnotes_page_rasters.c.run_id == run_id,
                    goodnotes_page_rasters.c.page_version_id == page_version_id,
                )
            ).one_or_none()
        except SQLAlchemyError:
            failure = RepositoryFailureError("the request could not be completed")
            raise failure from None
        return None if row is None else _raster_from_row(row)

    def submit_proposal(
        self,
        *,
        principal_id: str,
        run_id: str,
        page_version_id: str,
        content_sha256: str,
        schema_version: str,
        analyzer_name: str,
        analyzer_version: str,
        idempotency_key: str,
        request_fingerprint: str,
        payload_sha256: str,
        payload: dict[str, object],
        correlation_id: str,
        request_id: str,
        audit_id: str | None,
        created_at: datetime,
    ) -> GoodNotesProposalAdmission:
        try:
            return self._submit(
                principal_id=principal_id,
                run_id=run_id,
                page_version_id=page_version_id,
                content_sha256=content_sha256,
                schema_version=schema_version,
                analyzer_name=analyzer_name,
                analyzer_version=analyzer_version,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                payload_sha256=payload_sha256,
                payload=payload,
                correlation_id=correlation_id,
                request_id=request_id,
                audit_id=audit_id,
                created_at=created_at,
            )
        except GoodNotesProposalConflictError:
            raise
        except SQLAlchemyError:
            failure = RepositoryFailureError("the request could not be completed")
            raise failure from None

    def _submit(
        self,
        *,
        principal_id: str,
        run_id: str,
        page_version_id: str,
        content_sha256: str,
        schema_version: str,
        analyzer_name: str,
        analyzer_version: str,
        idempotency_key: str,
        request_fingerprint: str,
        payload_sha256: str,
        payload: dict[str, object],
        correlation_id: str,
        request_id: str,
        audit_id: str | None,
        created_at: datetime,
    ) -> GoodNotesProposalAdmission:
        prior = self._proposal_for(principal_id, idempotency_key)
        if prior is not None:
            if prior.request_fingerprint != request_fingerprint:
                raise GoodNotesProposalConflictError(
                    "the idempotency key is bound to a different request"
                )
            return GoodNotesProposalAdmission(proposal=prior, created=False)

        proposal_id = issue_stable_id("gnprp", principal_id, idempotency_key, request_fingerprint)
        inserted = self._connection.execute(
            pg_insert(goodnotes_semantic_proposals)
            .values(
                **_bound(
                    goodnotes_semantic_proposals,
                    principal_id,
                    {
                        "proposal_id": proposal_id,
                        "run_id": run_id,
                        "page_version_id": page_version_id,
                        "content_sha256": content_sha256,
                        "schema_version": schema_version,
                        "analyzer_name": analyzer_name,
                        "analyzer_version": analyzer_version,
                        "idempotency_key": idempotency_key,
                        "request_fingerprint": request_fingerprint,
                        "payload_sha256": payload_sha256,
                        "payload": payload,
                        "created_at": created_at,
                        "correlation_id": correlation_id,
                        "audit_id": audit_id,
                        "request_id": request_id,
                    },
                )
            )
            .on_conflict_do_nothing(constraint="one_goodnotes_semantic_proposal_key")
            .returning(goodnotes_semantic_proposals.c.proposal_id)
        ).first()
        if inserted is None:
            stored = self._proposal_for(principal_id, idempotency_key)
            if stored is None:
                raise RepositoryFailureError("the request could not be completed")
            if stored.request_fingerprint != request_fingerprint:
                raise GoodNotesProposalConflictError(
                    "the idempotency key is bound to a different request"
                )
            return GoodNotesProposalAdmission(proposal=stored, created=False)
        stored = self._proposal_for(principal_id, idempotency_key)
        if stored is None:
            raise RepositoryFailureError("the request could not be completed")
        return GoodNotesProposalAdmission(
            proposal=GoodNotesSemanticProposal(
                proposal_id=stored.proposal_id,
                principal_id=principal_id,
                run_id=stored.run_id,
                page_version_id=stored.page_version_id,
                content_sha256=stored.content_sha256,
                schema_version=stored.schema_version,
                analyzer_name=stored.analyzer_name,
                analyzer_version=stored.analyzer_version,
                idempotency_key=stored.idempotency_key,
                request_fingerprint=stored.request_fingerprint,
                payload_sha256=stored.payload_sha256,
                created_at=stored.created_at,
                replayed=False,
            ),
            created=True,
        )

    def _proposal_for(
        self, principal_id: str, idempotency_key: str
    ) -> GoodNotesSemanticProposal | None:
        row = self._connection.execute(
            select(*goodnotes_semantic_proposals.c).where(
                _mine(goodnotes_semantic_proposals, principal_id),
                goodnotes_semantic_proposals.c.idempotency_key == idempotency_key,
            )
        ).one_or_none()
        if row is None:
            return None
        return _proposal_from_row(row, replayed=True)
