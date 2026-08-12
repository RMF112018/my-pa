"""PostgreSQL repository for Principal-partitioned GoodNotes proposals and decisions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    ColumnElement,
    Table,
    and_,
    func,
    insert,
    literal_column,
    or_,
    select,
    tuple_,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from my_pa.domain.goodnotes.models import (
    GoodNotesPage,
    GoodNotesPageVersion,
    GoodNotesRegionProposal,
    GoodNotesSearchHit,
    ReconciliationReceipt,
    issue_stable_id,
)
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    goodnotes_page_versions,
    goodnotes_pages,
    goodnotes_reconciliation_receipts,
    goodnotes_region_proposals,
    goodnotes_review_decisions,
)


def _mine(table: Table, principal_id: str) -> ColumnElement[bool]:
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Table, principal_id: str, values: dict[str, object]) -> dict[str, object]:
    return principal_bound_values(values, table, capture_context(principal_id))


class PostgresGoodNotesRepository:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def receipt(self, principal_id: str, idempotency_key: str) -> ReconciliationReceipt | None:
        row = (
            self.connection.execute(
                select(goodnotes_reconciliation_receipts).where(
                    _mine(goodnotes_reconciliation_receipts, principal_id),
                    goodnotes_reconciliation_receipts.c.idempotency_key == idempotency_key,
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _receipt(row)

    def store_reconciliation(
        self,
        *,
        receipt: ReconciliationReceipt,
        pages: tuple[GoodNotesPage, ...],
        versions: tuple[GoodNotesPageVersion, ...],
        regions: tuple[GoodNotesRegionProposal, ...],
    ) -> ReconciliationReceipt:
        for page in pages:
            self.connection.execute(
                pg_insert(goodnotes_pages)
                .values(
                    _bound(
                        goodnotes_pages,
                        page.principal_id,
                        {
                            "page_id": page.page_id,
                            "source_id": page.source_id,
                            "source_object_id": page.source_object_id,
                            "page_number": page.page_number,
                        },
                    )
                )
                .on_conflict_do_nothing()
            )
        for version in versions:
            self.connection.execute(
                pg_insert(goodnotes_page_versions)
                .values(
                    _bound(
                        goodnotes_page_versions,
                        receipt.principal_id,
                        {
                            "page_version_id": version.page_version_id,
                            "page_id": version.page_id,
                            "source_version_id": version.source_version_id,
                            "content_sha256": version.content_sha256,
                            "observed_at": version.observed_at,
                        },
                    )
                )
                .on_conflict_do_nothing()
            )
        for region in regions:
            self.connection.execute(
                pg_insert(goodnotes_region_proposals)
                .values(
                    _bound(
                        goodnotes_region_proposals,
                        receipt.principal_id,
                        {
                            "region_id": region.region_id,
                            "page_version_id": region.page_version_id,
                            "ordinal": region.ordinal,
                            "box": {
                                "x": region.box.x,
                                "y": region.box.y,
                                "width": region.box.width,
                                "height": region.box.height,
                            },
                            "transcription": region.transcription,
                            "confidence": region.confidence,
                            "extractor": region.extractor,
                            "extractor_version": region.extractor_version,
                        },
                    )
                )
                .on_conflict_do_nothing()
            )
        self.connection.execute(
            pg_insert(goodnotes_reconciliation_receipts)
            .values(
                _bound(
                    goodnotes_reconciliation_receipts,
                    receipt.principal_id,
                    {
                        "receipt_id": receipt.receipt_id,
                        "idempotency_key": receipt.idempotency_key,
                        "request_fingerprint": receipt.request_fingerprint,
                        "page_version_ids": list(receipt.page_version_ids),
                        "created_regions": receipt.created_regions,
                    },
                )
            )
            .on_conflict_do_nothing()
        )
        stored = self.receipt(receipt.principal_id, receipt.idempotency_key)
        if stored is None or stored.request_fingerprint != receipt.request_fingerprint:
            raise ValueError("the idempotency key is bound to another reconciliation")
        return stored

    def decide_region(
        self,
        *,
        principal_id: str,
        region_id: str,
        disposition: str,
        corrected_text: str | None,
        decided_at: datetime,
    ) -> None:
        decision_id = issue_stable_id(
            "gnrec", principal_id, region_id, disposition, decided_at.isoformat()
        )
        decision = self.connection.execute(
            insert(goodnotes_review_decisions)
            .values(
                _bound(
                    goodnotes_review_decisions,
                    principal_id,
                    {
                        "decision_id": decision_id,
                        "region_id": region_id,
                        "disposition": disposition,
                        "corrected_text": corrected_text,
                        "decided_at": decided_at,
                    },
                )
            )
            .returning(goodnotes_review_decisions.c.decision_id)
        ).scalar_one()
        if decision != decision_id:
            raise RuntimeError("the stored review decision identity changed")

    def search(
        self, principal_id: str, query: str, *, limit: int
    ) -> tuple[GoodNotesSearchHit, ...]:
        if not query.strip() or not 1 <= limit <= 200:
            raise ValueError("a non-empty bounded lexical query is required")
        accepted_text = func.coalesce(
            goodnotes_review_decisions.c.corrected_text,
            goodnotes_region_proposals.c.transcription,
        )
        text_query = func.websearch_to_tsquery(literal_column("'simple'::regconfig"), query)
        lexical_match = or_(
            and_(
                goodnotes_review_decisions.c.corrected_text.is_(None),
                func.to_tsvector(
                    literal_column("'simple'::regconfig"),
                    goodnotes_region_proposals.c.transcription,
                ).op("@@")(text_query),
            ),
            and_(
                goodnotes_review_decisions.c.corrected_text.is_not(None),
                func.to_tsvector(
                    literal_column("'simple'::regconfig"),
                    goodnotes_review_decisions.c.corrected_text,
                ).op("@@")(text_query),
            ),
        )
        statement = (
            select(
                goodnotes_region_proposals.c.region_id,
                goodnotes_page_versions.c.page_version_id,
                goodnotes_page_versions.c.source_version_id,
                goodnotes_pages.c.page_number,
                accepted_text.label("accepted_text"),
                (goodnotes_review_decisions.c.corrected_text.is_not(None)).label("corrected"),
            )
            .select_from(
                goodnotes_review_decisions.join(
                    goodnotes_region_proposals,
                    tuple_(
                        goodnotes_region_proposals.c.principal_id,
                        goodnotes_region_proposals.c.region_id,
                    )
                    == tuple_(
                        goodnotes_review_decisions.c.principal_id,
                        goodnotes_review_decisions.c.region_id,
                    ),
                )
                .join(
                    goodnotes_page_versions,
                    tuple_(
                        goodnotes_page_versions.c.principal_id,
                        goodnotes_page_versions.c.page_version_id,
                    )
                    == tuple_(
                        goodnotes_region_proposals.c.principal_id,
                        goodnotes_region_proposals.c.page_version_id,
                    ),
                )
                .join(
                    goodnotes_pages,
                    tuple_(goodnotes_pages.c.principal_id, goodnotes_pages.c.page_id)
                    == tuple_(
                        goodnotes_page_versions.c.principal_id,
                        goodnotes_page_versions.c.page_id,
                    ),
                )
            )
            .where(
                _mine(goodnotes_review_decisions, principal_id),
                goodnotes_review_decisions.c.disposition.in_(("accepted", "corrected_accepted")),
                lexical_match,
            )
            .order_by(goodnotes_review_decisions.c.decided_at.desc())
            .limit(limit)
        )
        return tuple(
            GoodNotesSearchHit(
                region_id=row["region_id"],
                page_version_id=row["page_version_id"],
                source_version_id=row["source_version_id"],
                page_number=row["page_number"],
                accepted_text=row["accepted_text"],
                corrected=row["corrected"],
            )
            for row in self.connection.execute(statement).mappings()
        )


def _receipt(row: object) -> ReconciliationReceipt:
    values = row  # mapping-like SQLAlchemy row
    return ReconciliationReceipt(
        receipt_id=values["receipt_id"],  # type: ignore[index]
        principal_id=values["principal_id"],  # type: ignore[index]
        idempotency_key=values["idempotency_key"],  # type: ignore[index]
        request_fingerprint=values["request_fingerprint"],  # type: ignore[index]
        page_version_ids=tuple(values["page_version_ids"]),  # type: ignore[index]
        created_regions=values["created_regions"],  # type: ignore[index]
    )
