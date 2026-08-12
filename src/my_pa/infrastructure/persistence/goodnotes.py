"""PostgreSQL repository for Principal-partitioned GoodNotes proposals and decisions."""

from __future__ import annotations

import hashlib

from sqlalchemy import (
    ColumnElement,
    Table,
    any_,
    func,
    insert,
    literal,
    select,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from my_pa.contracts.ports import ReviewDecisionRequest
from my_pa.domain.capture.proposal import ProposalState, RiskClass
from my_pa.domain.capture.review import (
    Disposition,
    ReviewConflictError,
    ReviewDecision,
    ReviewNotFoundError,
    ReviewUnsupportedError,
)
from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.goodnotes.models import (
    GoodNotesPage,
    GoodNotesPageVersion,
    GoodNotesRegionProposal,
    GoodNotesReviewCase,
    GoodNotesSourceBinding,
    ReconciliationReceipt,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    enrollment_objects,
    enrollments,
    goodnotes_page_versions,
    goodnotes_pages,
    goodnotes_reconciliation_receipts,
    goodnotes_region_proposals,
    goodnotes_review_decisions,
    source_object_versions,
    source_objects,
    sources,
)


def _mine(table: Table, principal_id: str) -> ColumnElement[bool]:
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Table, principal_id: str, values: dict[str, object]) -> dict[str, object]:
    return principal_bound_values(values, table, capture_context(principal_id))


def _stable_canonical_id(kind: IdKind, principal_id: str, region_id: str) -> str:
    suffix = hashlib.sha256(
        f"goodnotes\x1f{kind.value}\x1f{principal_id}\x1f{region_id}".encode()
    ).hexdigest()[:24]
    return make_identifier(kind, suffix)


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

    def require_admitted_sources(
        self, principal_id: str, bindings: tuple[GoodNotesSourceBinding, ...]
    ) -> None:
        """Bind each manifest version to registry truth and searchable scope."""
        if not bindings:
            raise ValueError("a GoodNotes reconciliation requires a source binding")
        for binding in bindings:
            admitted = self.connection.execute(
                select(literal(1))
                .select_from(
                    source_object_versions.join(
                        source_objects,
                        source_objects.c.source_object_id
                        == source_object_versions.c.source_object_id,
                    )
                    .join(sources, sources.c.source_id == source_objects.c.source_id)
                    .join(
                        enrollment_objects,
                        enrollment_objects.c.source_object_id == source_objects.c.source_object_id,
                    )
                    .join(
                        enrollments,
                        enrollments.c.enrollment_id == enrollment_objects.c.enrollment_id,
                    )
                )
                .where(
                    source_object_versions.c.version_id == binding.source_version_id,
                    source_objects.c.source_object_id == binding.source_object_id,
                    source_objects.c.source_id == binding.source_id,
                    sources.c.source_id == binding.source_id,
                    enrollments.c.source_id == binding.source_id,
                    partition_criterion(enrollments, capture_context(principal_id)),
                    literal("text/plain") == any_(enrollments.c.media_types),
                )
                .limit(1)
            ).scalar_one_or_none()
            if admitted is None:
                raise ValueError(
                    "the GoodNotes manifest is not bound to an enrolled registry version"
                )

    def store_reconciliation(
        self,
        *,
        receipt: ReconciliationReceipt,
        pages: tuple[GoodNotesPage, ...],
        versions: tuple[GoodNotesPageVersion, ...],
        regions: tuple[GoodNotesRegionProposal, ...],
    ) -> ReconciliationReceipt:
        for page in pages:
            expected_page = _bound(
                goodnotes_pages,
                page.principal_id,
                {
                    "page_id": page.page_id,
                    "source_id": page.source_id,
                    "source_object_id": page.source_object_id,
                    "page_number": page.page_number,
                },
            )
            self.connection.execute(
                pg_insert(goodnotes_pages).values(expected_page).on_conflict_do_nothing()
            )
            _require_identical(
                self.connection,
                goodnotes_pages,
                page.principal_id,
                goodnotes_pages.c.page_id == page.page_id,
                expected_page,
                "page",
            )
        for version in versions:
            expected_version = _bound(
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
            self.connection.execute(
                pg_insert(goodnotes_page_versions).values(expected_version).on_conflict_do_nothing()
            )
            _require_identical(
                self.connection,
                goodnotes_page_versions,
                receipt.principal_id,
                goodnotes_page_versions.c.page_version_id == version.page_version_id,
                expected_version,
                "page version",
            )
        observed_by_version = {version.page_version_id: version.observed_at for version in versions}
        for region in regions:
            expected = _bound(
                goodnotes_region_proposals,
                receipt.principal_id,
                {
                    "region_id": region.region_id,
                    "proposal_id": _stable_canonical_id(
                        IdKind.PROPOSAL, receipt.principal_id, region.region_id
                    ),
                    "review_case_id": _stable_canonical_id(
                        IdKind.REVIEW_CASE, receipt.principal_id, region.region_id
                    ),
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
                    "opened_at": observed_by_version[region.page_version_id],
                },
            )
            self.connection.execute(
                pg_insert(goodnotes_region_proposals).values(expected).on_conflict_do_nothing()
            )
            _require_identical(
                self.connection,
                goodnotes_region_proposals,
                receipt.principal_id,
                goodnotes_region_proposals.c.region_id == region.region_id,
                expected,
                "region",
            )
        expected_receipt = _bound(
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
        self.connection.execute(
            pg_insert(goodnotes_reconciliation_receipts)
            .values(expected_receipt)
            .on_conflict_do_nothing()
        )
        _require_identical(
            self.connection,
            goodnotes_reconciliation_receipts,
            receipt.principal_id,
            goodnotes_reconciliation_receipts.c.idempotency_key == receipt.idempotency_key,
            expected_receipt,
            "receipt",
        )
        stored = self.receipt(receipt.principal_id, receipt.idempotency_key)
        if stored is None or stored.request_fingerprint != receipt.request_fingerprint:
            raise ValueError("the idempotency key is bound to another reconciliation")
        return stored


def _require_identical(
    connection: Connection,
    table: Table,
    principal_id: str,
    identity: ColumnElement[bool],
    expected: dict[str, object],
    kind: str,
) -> None:
    row = (
        connection.execute(select(table).where(_mine(table, principal_id), identity))
        .mappings()
        .one_or_none()
    )
    if row is None or any(row[key] != value for key, value in expected.items()):
        raise ValueError(f"the stable GoodNotes {kind} identity collided with other content")


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


def goodnotes_review_cases(
    connection: Connection, *, principal_id: str, limit: int
) -> tuple[GoodNotesReviewCase, ...]:
    if limit < 1:
        raise ValueError("a review page contains at least one case")
    latest_sequence = (
        select(func.max(goodnotes_review_decisions.c.sequence))
        .where(
            goodnotes_review_decisions.c.review_case_id
            == goodnotes_region_proposals.c.review_case_id
        )
        .correlate(goodnotes_region_proposals)
        .scalar_subquery()
    )
    latest_disposition = (
        select(goodnotes_review_decisions.c.disposition)
        .where(
            goodnotes_review_decisions.c.review_case_id
            == goodnotes_region_proposals.c.review_case_id
        )
        .order_by(goodnotes_review_decisions.c.sequence.desc())
        .limit(1)
        .correlate(goodnotes_region_proposals)
        .scalar_subquery()
    )
    rows = connection.execute(
        select(
            goodnotes_region_proposals.c.review_case_id,
            goodnotes_region_proposals.c.proposal_id,
            goodnotes_region_proposals.c.region_id,
            goodnotes_region_proposals.c.page_version_id,
            goodnotes_region_proposals.c.principal_id,
            goodnotes_region_proposals.c.confidence,
            goodnotes_region_proposals.c.opened_at,
            func.coalesce(latest_sequence, 0).label("review_version"),
            latest_disposition.label("latest_disposition"),
        )
        .where(_mine(goodnotes_region_proposals, principal_id))
        .order_by(
            goodnotes_region_proposals.c.opened_at,
            goodnotes_region_proposals.c.review_case_id,
        )
        .limit(limit)
    ).mappings()
    cases: list[GoodNotesReviewCase] = []
    for row in rows:
        disposition = (
            None if row["latest_disposition"] is None else Disposition(row["latest_disposition"])
        )
        cases.append(
            GoodNotesReviewCase(
                review_case_id=row["review_case_id"],
                proposal_id=row["proposal_id"],
                region_id=row["region_id"],
                page_version_id=row["page_version_id"],
                principal_id=row["principal_id"],
                confidence=float(row["confidence"]),
                opened_at=row["opened_at"],
                proposal_state=_goodnotes_state(disposition),
                risk_class=RiskClass.MODERATE,
                review_version=int(row["review_version"]),
                latest_disposition=disposition,
            )
        )
    return tuple(cases)


def is_goodnotes_review_case(
    connection: Connection, *, review_case_id: str, principal_id: str
) -> bool:
    return (
        connection.execute(
            select(goodnotes_region_proposals.c.review_case_id).where(
                goodnotes_region_proposals.c.review_case_id == review_case_id,
                _mine(goodnotes_region_proposals, principal_id),
            )
        ).scalar_one_or_none()
        is not None
    )


def decide_goodnotes_review(
    connection: Connection, request: ReviewDecisionRequest
) -> ReviewDecision:
    case = connection.execute(
        select(
            goodnotes_region_proposals.c.region_id,
            goodnotes_region_proposals.c.review_case_id,
        )
        .where(
            goodnotes_region_proposals.c.review_case_id == request.review_case_id,
            _mine(goodnotes_region_proposals, request.principal_id),
        )
        .with_for_update(of=goodnotes_region_proposals)
    ).one_or_none()
    if case is None:
        raise ReviewNotFoundError("the request names no stored review case")
    decisions = connection.execute(
        select(goodnotes_review_decisions.c.sequence, goodnotes_review_decisions.c.disposition)
        .where(goodnotes_review_decisions.c.review_case_id == request.review_case_id)
        .order_by(goodnotes_review_decisions.c.sequence)
    ).all()
    if any(
        Disposition(row.disposition) in {Disposition.ACCEPT, Disposition.CORRECT_AND_ACCEPT}
        for row in decisions
    ):
        raise ReviewConflictError("an accepted review case is terminal")
    current = len(decisions)
    if current != request.expected_review_version:
        raise ReviewConflictError("the expected review version is stale")
    if request.disposition in {Disposition.REPROCESS, Disposition.ESCALATE}:
        raise ReviewUnsupportedError("the requested disposition has no eligible route")
    sequence = current + 1
    decision_id = issue_identifier(IdKind.REVIEW_DECISION)
    accepted = request.disposition in {Disposition.ACCEPT, Disposition.CORRECT_AND_ACCEPT}
    knowledge_id = issue_identifier(IdKind.KNOWLEDGE) if accepted else None
    connection.execute(
        insert(goodnotes_review_decisions).values(
            _bound(
                goodnotes_review_decisions,
                request.principal_id,
                {
                    "decision_id": decision_id,
                    "region_id": str(case.region_id),
                    "review_case_id": request.review_case_id,
                    "sequence": sequence,
                    "disposition": request.disposition.value,
                    "corrected_text": request.corrected_value,
                    "knowledge_id": knowledge_id,
                    "correlation_id": request.correlation_id,
                    "audit_id": request.audit_id,
                    "decided_at": request.decided_at,
                },
            )
        )
    )
    state = _goodnotes_state(request.disposition)
    return ReviewDecision(
        decision_id=decision_id,
        review_case_id=request.review_case_id,
        sequence=sequence,
        disposition=request.disposition,
        principal_id=request.principal_id,
        correlation_id=request.correlation_id,
        audit_id=request.audit_id,
        decided_at=request.decided_at,
        proposal_state=state,
        normalized_value=request.corrected_value,
    )


def _goodnotes_state(disposition: Disposition | None) -> ProposalState:
    if disposition is None:
        return ProposalState.NEEDS_REVIEW
    return {
        Disposition.ACCEPT: ProposalState.ACCEPTED,
        Disposition.CORRECT_AND_ACCEPT: ProposalState.CORRECTED_ACCEPTED,
        Disposition.REJECT: ProposalState.REJECTED,
        Disposition.DEFER: ProposalState.DEFERRED,
        Disposition.MARK_UNRESOLVED: ProposalState.UNRESOLVED,
    }[disposition]
