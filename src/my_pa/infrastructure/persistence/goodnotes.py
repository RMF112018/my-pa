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
    update,
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
    GoodNotesIdentityStatus,
    GoodNotesIngestionRun,
    GoodNotesIngestionStatus,
    GoodNotesIngestionTrigger,
    GoodNotesLogicalPage,
    GoodNotesMatchMethod,
    GoodNotesNotebook,
    GoodNotesNotebookPath,
    GoodNotesPage,
    GoodNotesPagePosition,
    GoodNotesPageVersion,
    GoodNotesPriorPageEvidence,
    GoodNotesRegionProposal,
    GoodNotesReviewCase,
    GoodNotesSourceBinding,
    GoodNotesSourceSnapshot,
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
    goodnotes_ingestion_runs,
    goodnotes_logical_pages,
    goodnotes_notebook_paths,
    goodnotes_notebooks,
    goodnotes_page_positions,
    goodnotes_page_versions,
    goodnotes_pages,
    goodnotes_reconciliation_receipts,
    goodnotes_region_proposals,
    goodnotes_review_decisions,
    goodnotes_source_snapshots,
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

    def store_notebook(self, notebook: GoodNotesNotebook) -> GoodNotesNotebook:
        expected = _bound(
            goodnotes_notebooks,
            notebook.principal_id,
            {
                "notebook_id": notebook.notebook_id,
                "source_root_id": notebook.source_root_id,
                "label": notebook.label,
                "identity_status": notebook.identity_status.value,
                "created_at": notebook.created_at,
                "last_observed_at": notebook.last_observed_at,
            },
        )
        self.connection.execute(
            pg_insert(goodnotes_notebooks).values(expected).on_conflict_do_nothing()
        )
        stored = self.notebook(notebook.principal_id, notebook.notebook_id)
        if stored is None:
            raise ValueError("the GoodNotes notebook could not be stored")
        if stored.source_root_id != notebook.source_root_id:
            raise ValueError("the stable GoodNotes notebook identity collided with other content")
        if (
            stored.last_observed_at != notebook.last_observed_at
            or stored.label != notebook.label
            or stored.identity_status != notebook.identity_status
        ):
            self.connection.execute(
                update(goodnotes_notebooks)
                .where(
                    _mine(goodnotes_notebooks, notebook.principal_id),
                    goodnotes_notebooks.c.notebook_id == notebook.notebook_id,
                )
                .values(
                    last_observed_at=notebook.last_observed_at,
                    label=notebook.label,
                    identity_status=notebook.identity_status.value,
                )
            )
            stored = self.notebook(notebook.principal_id, notebook.notebook_id)
            if stored is None:
                raise ValueError("the GoodNotes notebook could not be stored")
        return stored

    def notebook(self, principal_id: str, notebook_id: str) -> GoodNotesNotebook | None:
        row = (
            self.connection.execute(
                select(goodnotes_notebooks).where(
                    _mine(goodnotes_notebooks, principal_id),
                    goodnotes_notebooks.c.notebook_id == notebook_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _notebook(row)

    def record_notebook_path(self, observed: GoodNotesNotebookPath) -> GoodNotesNotebookPath:
        if observed.is_current:
            self.connection.execute(
                update(goodnotes_notebook_paths)
                .where(
                    _mine(goodnotes_notebook_paths, observed.principal_id),
                    goodnotes_notebook_paths.c.notebook_id == observed.notebook_id,
                    goodnotes_notebook_paths.c.is_current.is_(True),
                    goodnotes_notebook_paths.c.path != observed.path,
                )
                .values(is_current=False)
            )
        expected = _bound(
            goodnotes_notebook_paths,
            observed.principal_id,
            {
                "notebook_id": observed.notebook_id,
                "path": observed.path,
                "first_seen_at": observed.first_seen_at,
                "last_seen_at": observed.last_seen_at,
                "first_snapshot_id": observed.first_snapshot_id,
                "last_snapshot_id": observed.last_snapshot_id,
                "is_current": observed.is_current,
            },
        )
        self.connection.execute(
            pg_insert(goodnotes_notebook_paths)
            .values(expected)
            .on_conflict_do_update(
                index_elements=["principal_id", "notebook_id", "path"],
                set_={
                    "last_seen_at": observed.last_seen_at,
                    "last_snapshot_id": observed.last_snapshot_id,
                    "is_current": observed.is_current,
                },
            )
        )
        stored = self.notebook_path(observed.principal_id, observed.notebook_id, observed.path)
        if stored is None:
            raise ValueError("the GoodNotes notebook path could not be stored")
        return stored

    def notebook_path(
        self, principal_id: str, notebook_id: str, path: str
    ) -> GoodNotesNotebookPath | None:
        row = (
            self.connection.execute(
                select(goodnotes_notebook_paths).where(
                    _mine(goodnotes_notebook_paths, principal_id),
                    goodnotes_notebook_paths.c.notebook_id == notebook_id,
                    goodnotes_notebook_paths.c.path == path,
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _notebook_path(row)

    def notebook_paths(
        self, principal_id: str, notebook_id: str
    ) -> tuple[GoodNotesNotebookPath, ...]:
        rows = (
            self.connection.execute(
                select(goodnotes_notebook_paths)
                .where(
                    _mine(goodnotes_notebook_paths, principal_id),
                    goodnotes_notebook_paths.c.notebook_id == notebook_id,
                )
                .order_by(goodnotes_notebook_paths.c.first_seen_at, goodnotes_notebook_paths.c.path)
            )
            .mappings()
            .all()
        )
        return tuple(_notebook_path(row) for row in rows)

    def store_snapshot(self, snapshot: GoodNotesSourceSnapshot) -> GoodNotesSourceSnapshot:
        expected = _bound(
            goodnotes_source_snapshots,
            snapshot.principal_id,
            {
                "snapshot_id": snapshot.snapshot_id,
                "notebook_id": snapshot.notebook_id,
                "source_object_id": snapshot.source_object_id,
                "observed_path": snapshot.observed_path,
                "raw_sha256": snapshot.raw_sha256,
                "size_bytes": snapshot.size_bytes,
                "mtime_ns": snapshot.mtime_ns,
                "page_count": snapshot.page_count,
                "observed_at": snapshot.observed_at,
                "settled_at": snapshot.settled_at,
                "run_id": snapshot.run_id,
            },
        )
        self.connection.execute(
            pg_insert(goodnotes_source_snapshots).values(expected).on_conflict_do_nothing()
        )
        replayed = self.snapshot_by_bytes(
            snapshot.principal_id, snapshot.notebook_id, snapshot.raw_sha256
        )
        if replayed is not None:
            return replayed
        stored = self.snapshot(snapshot.principal_id, snapshot.snapshot_id)
        if stored is None:
            raise ValueError("the GoodNotes snapshot could not be stored")
        _require_identical(
            self.connection,
            goodnotes_source_snapshots,
            snapshot.principal_id,
            goodnotes_source_snapshots.c.snapshot_id == snapshot.snapshot_id,
            expected,
            "snapshot",
        )
        return stored

    def snapshot(self, principal_id: str, snapshot_id: str) -> GoodNotesSourceSnapshot | None:
        row = (
            self.connection.execute(
                select(goodnotes_source_snapshots).where(
                    _mine(goodnotes_source_snapshots, principal_id),
                    goodnotes_source_snapshots.c.snapshot_id == snapshot_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _snapshot(row)

    def snapshot_by_bytes(
        self, principal_id: str, notebook_id: str, raw_sha256: str
    ) -> GoodNotesSourceSnapshot | None:
        row = (
            self.connection.execute(
                select(goodnotes_source_snapshots).where(
                    _mine(goodnotes_source_snapshots, principal_id),
                    goodnotes_source_snapshots.c.notebook_id == notebook_id,
                    goodnotes_source_snapshots.c.raw_sha256 == raw_sha256,
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _snapshot(row)

    def store_logical_page(self, page: GoodNotesLogicalPage) -> GoodNotesLogicalPage:
        expected = _bound(
            goodnotes_logical_pages,
            page.principal_id,
            {
                "logical_page_id": page.logical_page_id,
                "notebook_id": page.notebook_id,
                "created_at": page.created_at,
                "last_seen_at": page.last_seen_at,
                "identity_status": page.identity_status.value,
            },
        )
        self.connection.execute(
            pg_insert(goodnotes_logical_pages).values(expected).on_conflict_do_nothing()
        )
        stored = self.logical_page(page.principal_id, page.logical_page_id)
        if stored is None:
            raise ValueError("the GoodNotes logical page could not be stored")
        if stored.notebook_id != page.notebook_id:
            raise ValueError(
                "the stable GoodNotes logical page identity collided with other content"
            )
        if (
            stored.last_seen_at != page.last_seen_at
            or stored.identity_status != page.identity_status
        ):
            self.connection.execute(
                update(goodnotes_logical_pages)
                .where(
                    _mine(goodnotes_logical_pages, page.principal_id),
                    goodnotes_logical_pages.c.logical_page_id == page.logical_page_id,
                )
                .values(
                    last_seen_at=page.last_seen_at,
                    identity_status=page.identity_status.value,
                )
            )
            stored = self.logical_page(page.principal_id, page.logical_page_id)
            if stored is None:
                raise ValueError("the GoodNotes logical page could not be stored")
        return stored

    def logical_page(self, principal_id: str, logical_page_id: str) -> GoodNotesLogicalPage | None:
        row = (
            self.connection.execute(
                select(goodnotes_logical_pages).where(
                    _mine(goodnotes_logical_pages, principal_id),
                    goodnotes_logical_pages.c.logical_page_id == logical_page_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _logical_page(row)

    def logical_pages(
        self, principal_id: str, notebook_id: str
    ) -> tuple[GoodNotesLogicalPage, ...]:
        rows = (
            self.connection.execute(
                select(goodnotes_logical_pages)
                .where(
                    _mine(goodnotes_logical_pages, principal_id),
                    goodnotes_logical_pages.c.notebook_id == notebook_id,
                )
                .order_by(
                    goodnotes_logical_pages.c.created_at,
                    goodnotes_logical_pages.c.logical_page_id,
                )
            )
            .mappings()
            .all()
        )
        return tuple(_logical_page(row) for row in rows)

    def snapshots(self, principal_id: str, notebook_id: str) -> tuple[GoodNotesSourceSnapshot, ...]:
        rows = (
            self.connection.execute(
                select(goodnotes_source_snapshots)
                .where(
                    _mine(goodnotes_source_snapshots, principal_id),
                    goodnotes_source_snapshots.c.notebook_id == notebook_id,
                )
                .order_by(
                    goodnotes_source_snapshots.c.observed_at,
                    goodnotes_source_snapshots.c.snapshot_id,
                )
            )
            .mappings()
            .all()
        )
        return tuple(_snapshot(row) for row in rows)

    def page_version(self, principal_id: str, page_version_id: str) -> GoodNotesPageVersion | None:
        row = (
            self.connection.execute(
                select(goodnotes_page_versions).where(
                    _mine(goodnotes_page_versions, principal_id),
                    goodnotes_page_versions.c.page_version_id == page_version_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _page_version_row(row)

    def prior_page_evidence(
        self, principal_id: str, notebook_id: str
    ) -> tuple[GoodNotesPriorPageEvidence, ...]:
        pages = self.logical_pages(principal_id, notebook_id)
        if not pages:
            return ()
        snapshots = self.snapshots(principal_id, notebook_id)
        rank = {item.snapshot_id: index for index, item in enumerate(snapshots)}
        latest: dict[str, GoodNotesPagePosition] = {}
        for snapshot in snapshots:
            for position in self.page_positions(principal_id, snapshot.snapshot_id):
                current = latest.get(position.logical_page_id)
                if current is None or rank[position.snapshot_id] >= rank[current.snapshot_id]:
                    latest[position.logical_page_id] = position
        evidence: list[GoodNotesPriorPageEvidence] = []
        for page in pages:
            latest_position = latest.get(page.logical_page_id)
            if latest_position is None:
                continue
            version = (
                None
                if latest_position.page_version_id is None
                else self.page_version(principal_id, latest_position.page_version_id)
            )
            evidence.append(
                GoodNotesPriorPageEvidence(
                    logical_page_id=page.logical_page_id,
                    last_page_number=latest_position.page_number,
                    last_page_version_id=latest_position.page_version_id,
                    exact_render_sha256=None if version is None else version.content_sha256,
                    normalized_render_sha256=(
                        None if version is None else version.normalized_render_sha256
                    ),
                    perceptual_hash=None if version is None else version.perceptual_hash,
                    render_width=None if version is None else version.render_width,
                    render_height=None if version is None else version.render_height,
                )
            )
        return tuple(evidence)

    def store_page_version_render(
        self, *, page: GoodNotesPage, version: GoodNotesPageVersion
    ) -> GoodNotesPageVersion:
        principal_id = page.principal_id
        expected_page = _bound(
            goodnotes_pages,
            principal_id,
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
            principal_id,
            goodnotes_pages.c.page_id == page.page_id,
            expected_page,
            "page",
        )
        expected_version = _bound(
            goodnotes_page_versions,
            principal_id,
            {
                "page_version_id": version.page_version_id,
                "page_id": version.page_id,
                "source_version_id": version.source_version_id,
                "content_sha256": version.content_sha256,
                "observed_at": version.observed_at,
                "logical_page_id": version.logical_page_id,
                "normalized_render_sha256": version.normalized_render_sha256,
                "perceptual_hash": version.perceptual_hash,
                "render_width": version.render_width,
                "render_height": version.render_height,
                "renderer_name": version.renderer_name,
                "renderer_version": version.renderer_version,
                "render_profile_version": version.render_profile_version,
            },
        )
        identity_fields = {
            "page_version_id": version.page_version_id,
            "page_id": version.page_id,
            "source_version_id": version.source_version_id,
            "content_sha256": version.content_sha256,
            "observed_at": version.observed_at,
        }
        self.connection.execute(
            pg_insert(goodnotes_page_versions).values(expected_version).on_conflict_do_nothing()
        )
        stored = self.page_version(principal_id, version.page_version_id)
        if stored is None:
            raise ValueError("the GoodNotes page version could not be stored")
        bound_identity = _bound(goodnotes_page_versions, principal_id, identity_fields)
        _require_identical(
            self.connection,
            goodnotes_page_versions,
            principal_id,
            goodnotes_page_versions.c.page_version_id == version.page_version_id,
            bound_identity,
            "page version",
        )
        if (
            stored.logical_page_id != version.logical_page_id
            or stored.normalized_render_sha256 != version.normalized_render_sha256
            or stored.perceptual_hash != version.perceptual_hash
            or stored.render_width != version.render_width
            or stored.render_height != version.render_height
            or stored.renderer_name != version.renderer_name
            or stored.renderer_version != version.renderer_version
            or stored.render_profile_version != version.render_profile_version
        ):
            if stored.logical_page_id not in {None, version.logical_page_id}:
                raise ValueError(
                    "the stable GoodNotes page version identity collided with other content"
                )
            self.connection.execute(
                update(goodnotes_page_versions)
                .where(
                    _mine(goodnotes_page_versions, principal_id),
                    goodnotes_page_versions.c.page_version_id == version.page_version_id,
                )
                .values(
                    logical_page_id=version.logical_page_id,
                    normalized_render_sha256=version.normalized_render_sha256,
                    perceptual_hash=version.perceptual_hash,
                    render_width=version.render_width,
                    render_height=version.render_height,
                    renderer_name=version.renderer_name,
                    renderer_version=version.renderer_version,
                    render_profile_version=version.render_profile_version,
                )
            )
            stored = self.page_version(principal_id, version.page_version_id)
            if stored is None:
                raise ValueError("the GoodNotes page version could not be stored")
        return stored

    def store_page_position(self, position: GoodNotesPagePosition) -> GoodNotesPagePosition:
        expected = _bound(
            goodnotes_page_positions,
            position.principal_id,
            {
                "snapshot_id": position.snapshot_id,
                "page_number": position.page_number,
                "logical_page_id": position.logical_page_id,
                "page_version_id": position.page_version_id,
                "match_method": position.match_method.value,
                "match_confidence": position.match_confidence,
                "prior_page_version_id": position.prior_page_version_id,
                "created_at": position.created_at,
            },
        )
        self.connection.execute(
            pg_insert(goodnotes_page_positions).values(expected).on_conflict_do_nothing()
        )
        _require_identical(
            self.connection,
            goodnotes_page_positions,
            position.principal_id,
            (goodnotes_page_positions.c.snapshot_id == position.snapshot_id)
            & (goodnotes_page_positions.c.page_number == position.page_number),
            expected,
            "page position",
        )
        stored = self.page_position(
            position.principal_id, position.snapshot_id, position.page_number
        )
        if stored is None:
            raise ValueError("the GoodNotes page position could not be stored")
        return stored

    def page_position(
        self, principal_id: str, snapshot_id: str, page_number: int
    ) -> GoodNotesPagePosition | None:
        row = (
            self.connection.execute(
                select(goodnotes_page_positions).where(
                    _mine(goodnotes_page_positions, principal_id),
                    goodnotes_page_positions.c.snapshot_id == snapshot_id,
                    goodnotes_page_positions.c.page_number == page_number,
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _page_position(row)

    def page_positions(
        self, principal_id: str, snapshot_id: str
    ) -> tuple[GoodNotesPagePosition, ...]:
        rows = (
            self.connection.execute(
                select(goodnotes_page_positions)
                .where(
                    _mine(goodnotes_page_positions, principal_id),
                    goodnotes_page_positions.c.snapshot_id == snapshot_id,
                )
                .order_by(goodnotes_page_positions.c.page_number)
            )
            .mappings()
            .all()
        )
        return tuple(_page_position(row) for row in rows)

    def create_run(self, run: GoodNotesIngestionRun) -> GoodNotesIngestionRun:
        expected = _bound(
            goodnotes_ingestion_runs,
            run.principal_id,
            {
                "run_id": run.run_id,
                "source_root_id": run.source_root_id,
                "trigger_type": run.trigger_type.value,
                "request_id": run.request_id,
                "idempotency_key": run.idempotency_key,
                "request_fingerprint": run.request_fingerprint,
                "started_at": run.started_at,
                "ended_at": run.ended_at,
                "status": run.status.value,
                "lease_owner": run.lease_owner,
                "lease_expires_at": run.lease_expires_at,
                "snapshot_count": run.snapshot_count,
                "page_count": run.page_count,
                "new_logical_page_count": run.new_logical_page_count,
                "changed_page_count": run.changed_page_count,
                "ambiguous_page_count": run.ambiguous_page_count,
                "error_code": run.error_code,
                "error_class": run.error_class,
            },
        )
        self.connection.execute(
            pg_insert(goodnotes_ingestion_runs).values(expected).on_conflict_do_nothing()
        )
        stored = self.run_by_request(run.principal_id, run.request_id)
        if stored is None:
            raise ValueError("the GoodNotes ingestion run could not be stored")
        if stored.request_fingerprint != run.request_fingerprint:
            raise ValueError("the request id is bound to another ingestion")
        return stored

    def run(self, principal_id: str, run_id: str) -> GoodNotesIngestionRun | None:
        row = (
            self.connection.execute(
                select(goodnotes_ingestion_runs).where(
                    _mine(goodnotes_ingestion_runs, principal_id),
                    goodnotes_ingestion_runs.c.run_id == run_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _run(row)

    def run_by_request(self, principal_id: str, request_id: str) -> GoodNotesIngestionRun | None:
        row = (
            self.connection.execute(
                select(goodnotes_ingestion_runs).where(
                    _mine(goodnotes_ingestion_runs, principal_id),
                    goodnotes_ingestion_runs.c.request_id == request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _run(row)

    def update_run(self, run: GoodNotesIngestionRun) -> GoodNotesIngestionRun:
        stored = self.run(run.principal_id, run.run_id)
        if stored is None:
            raise ValueError("the request names no stored GoodNotes ingestion run")
        if stored.request_fingerprint != run.request_fingerprint:
            raise ValueError("the request id is bound to another ingestion")
        self.connection.execute(
            update(goodnotes_ingestion_runs)
            .where(
                _mine(goodnotes_ingestion_runs, run.principal_id),
                goodnotes_ingestion_runs.c.run_id == run.run_id,
            )
            .values(
                ended_at=run.ended_at,
                status=run.status.value,
                lease_owner=run.lease_owner,
                lease_expires_at=run.lease_expires_at,
                snapshot_count=run.snapshot_count,
                page_count=run.page_count,
                new_logical_page_count=run.new_logical_page_count,
                changed_page_count=run.changed_page_count,
                ambiguous_page_count=run.ambiguous_page_count,
                error_code=run.error_code,
                error_class=run.error_class,
            )
        )
        updated = self.run(run.principal_id, run.run_id)
        if updated is None:
            raise ValueError("the GoodNotes ingestion run could not be updated")
        return updated


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


def _notebook(row: object) -> GoodNotesNotebook:
    values = row  # mapping-like SQLAlchemy row
    return GoodNotesNotebook(
        notebook_id=values["notebook_id"],  # type: ignore[index]
        principal_id=values["principal_id"],  # type: ignore[index]
        source_root_id=values["source_root_id"],  # type: ignore[index]
        identity_status=GoodNotesIdentityStatus(values["identity_status"]),  # type: ignore[index]
        created_at=values["created_at"],  # type: ignore[index]
        last_observed_at=values["last_observed_at"],  # type: ignore[index]
        label=values["label"],  # type: ignore[index]
    )


def _notebook_path(row: object) -> GoodNotesNotebookPath:
    values = row  # mapping-like SQLAlchemy row
    return GoodNotesNotebookPath(
        principal_id=values["principal_id"],  # type: ignore[index]
        notebook_id=values["notebook_id"],  # type: ignore[index]
        path=values["path"],  # type: ignore[index]
        first_seen_at=values["first_seen_at"],  # type: ignore[index]
        last_seen_at=values["last_seen_at"],  # type: ignore[index]
        is_current=bool(values["is_current"]),  # type: ignore[index]
        first_snapshot_id=values["first_snapshot_id"],  # type: ignore[index]
        last_snapshot_id=values["last_snapshot_id"],  # type: ignore[index]
    )


def _snapshot(row: object) -> GoodNotesSourceSnapshot:
    values = row  # mapping-like SQLAlchemy row
    return GoodNotesSourceSnapshot(
        snapshot_id=values["snapshot_id"],  # type: ignore[index]
        principal_id=values["principal_id"],  # type: ignore[index]
        notebook_id=values["notebook_id"],  # type: ignore[index]
        source_object_id=values["source_object_id"],  # type: ignore[index]
        observed_path=values["observed_path"],  # type: ignore[index]
        raw_sha256=values["raw_sha256"],  # type: ignore[index]
        size_bytes=int(values["size_bytes"]),  # type: ignore[index]
        page_count=int(values["page_count"]),  # type: ignore[index]
        observed_at=values["observed_at"],  # type: ignore[index]
        settled_at=values["settled_at"],  # type: ignore[index]
        run_id=values["run_id"],  # type: ignore[index]
        mtime_ns=values["mtime_ns"],  # type: ignore[index]
    )


def _page_version_row(row: object) -> GoodNotesPageVersion:
    values = row  # mapping-like SQLAlchemy row
    return GoodNotesPageVersion(
        page_version_id=values["page_version_id"],  # type: ignore[index]
        page_id=values["page_id"],  # type: ignore[index]
        source_version_id=values["source_version_id"],  # type: ignore[index]
        content_sha256=values["content_sha256"],  # type: ignore[index]
        observed_at=values["observed_at"],  # type: ignore[index]
        logical_page_id=values["logical_page_id"],  # type: ignore[index]
        normalized_render_sha256=values["normalized_render_sha256"],  # type: ignore[index]
        perceptual_hash=values["perceptual_hash"],  # type: ignore[index]
        render_width=values["render_width"],  # type: ignore[index]
        render_height=values["render_height"],  # type: ignore[index]
        renderer_name=values["renderer_name"],  # type: ignore[index]
        renderer_version=values["renderer_version"],  # type: ignore[index]
        render_profile_version=values["render_profile_version"],  # type: ignore[index]
    )


def _logical_page(row: object) -> GoodNotesLogicalPage:
    values = row  # mapping-like SQLAlchemy row
    return GoodNotesLogicalPage(
        logical_page_id=values["logical_page_id"],  # type: ignore[index]
        principal_id=values["principal_id"],  # type: ignore[index]
        notebook_id=values["notebook_id"],  # type: ignore[index]
        created_at=values["created_at"],  # type: ignore[index]
        last_seen_at=values["last_seen_at"],  # type: ignore[index]
        identity_status=GoodNotesIdentityStatus(values["identity_status"]),  # type: ignore[index]
    )


def _page_position(row: object) -> GoodNotesPagePosition:
    values = row  # mapping-like SQLAlchemy row
    confidence = values["match_confidence"]  # type: ignore[index]
    return GoodNotesPagePosition(
        principal_id=values["principal_id"],  # type: ignore[index]
        snapshot_id=values["snapshot_id"],  # type: ignore[index]
        page_number=int(values["page_number"]),  # type: ignore[index]
        logical_page_id=values["logical_page_id"],  # type: ignore[index]
        created_at=values["created_at"],  # type: ignore[index]
        match_method=GoodNotesMatchMethod(values["match_method"]),  # type: ignore[index]
        page_version_id=values["page_version_id"],  # type: ignore[index]
        match_confidence=None if confidence is None else float(confidence),
        prior_page_version_id=values["prior_page_version_id"],  # type: ignore[index]
    )


def _run(row: object) -> GoodNotesIngestionRun:
    values = row  # mapping-like SQLAlchemy row
    return GoodNotesIngestionRun(
        run_id=values["run_id"],  # type: ignore[index]
        principal_id=values["principal_id"],  # type: ignore[index]
        source_root_id=values["source_root_id"],  # type: ignore[index]
        trigger_type=GoodNotesIngestionTrigger(values["trigger_type"]),  # type: ignore[index]
        request_id=values["request_id"],  # type: ignore[index]
        idempotency_key=values["idempotency_key"],  # type: ignore[index]
        request_fingerprint=values["request_fingerprint"],  # type: ignore[index]
        started_at=values["started_at"],  # type: ignore[index]
        status=GoodNotesIngestionStatus(values["status"]),  # type: ignore[index]
        ended_at=values["ended_at"],  # type: ignore[index]
        lease_owner=values["lease_owner"],  # type: ignore[index]
        lease_expires_at=values["lease_expires_at"],  # type: ignore[index]
        snapshot_count=int(values["snapshot_count"]),  # type: ignore[index]
        page_count=int(values["page_count"]),  # type: ignore[index]
        new_logical_page_count=int(values["new_logical_page_count"]),  # type: ignore[index]
        changed_page_count=int(values["changed_page_count"]),  # type: ignore[index]
        ambiguous_page_count=int(values["ambiguous_page_count"]),  # type: ignore[index]
        error_code=values["error_code"],  # type: ignore[index]
        error_class=values["error_class"],  # type: ignore[index]
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
