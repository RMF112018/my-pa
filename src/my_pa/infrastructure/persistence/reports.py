"""The general report plane's statements: publish, update, lifecycle, read, history.

Publish, replay, read and resolve are WP02's; update, archive / delete /
restore (`transition`) and the two histories are WP03's (contract C, D4-D10).

**Every statement is Principal-scoped.** Every SELECT composes `_mine`
(`partition_criterion`), every INSERT `_bound` (`principal_bound_values`), and
every join `matching_partition_criterion`. A report, receipt or association
target another Principal owns answers what one that does not exist answers.

**Publish writes in the order the schema requires, in one transaction:** the
content object, the root (its head cache names version 1 through a deferred
foreign key), version 1, its manifest and associations (both refused by the
insert guards unless written in the version's transaction), and last the
`publish`/`applied` receipt. The receipt's `UNIQUE (owner_principal_id,
operation, idempotency_key)` is what settles two concurrent writers of one key:
the writes run under a SAVEPOINT, and the loser's violation rolls back only
its own rows, after which the committed winner's receipt is read (a READ
COMMITTED statement sees it) and replayed or refused as a conflict by its
intent digest. A key found before writing is settled the same way.

**An update or a transition locks the root first** (`SELECT ... FOR UPDATE`,
Principal-scoped), then looks up its receipt (replay or conflict), then checks
the state and the compare-and-set value (`head_version_number` or
`lifecycle_revision`), and only then writes, under a SAVEPOINT with the same
key-constraint settle path as publish. Two writers of one report therefore
serialize on the root row: the second sees the first's committed root (READ
COMMITTED re-reads a locked row) and refuses as stale, or replays the first's
receipt. Every refusal is raised before the first write, so nothing of it is
written. An update writes a content object only for new content (D5), version
N+1 superseding N, its manifest, its associations (patched ones verified as a
publish's are, the rest copied verbatim with their observation) and moves the
head; a transition writes one event linked to its predecessor and moves the
lifecycle cache. No statement here deletes a row, and none updates a row but
the root's caches.

**A read recomputes before it answers.** The decoded content digest is
recomputed from the stored body and data, and the whole manifest is rebuilt
from the stored version, content and association rows with the shared
`build_version_manifest` (D10): the stored document must equal it canonically
and both stored digests must be its digest, else `ReportIntegrityError`. A
history page verifies every version it lists the same way. jsonb reproduces
the canonical bytes: keys are re-sorted by `canonical_json`, and every number
the domain admits prints back with the digits it was written with (`-0.0` is
normalized to `0.0` before hashing, because `numeric` has no negative zero).

Nothing here writes to a `knowledge.intelligence_*` table;
`intelligence_artifacts` is only read, to resolve an `intelligence_report`
association target.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import ColumnElement, Connection, Row, Table, select
from sqlalchemy.exc import IntegrityError

from my_pa.contracts.ports import (
    GeneralReportRepository,
    ReportAssociationTargetNotFoundError,
    ReportIdempotencyConflictError,
    ReportIntegrityError,
    ReportNotFoundError,
    ReportStaleLifecycleRevisionError,
    ReportStaleVersionError,
    ReportWithdrawnError,
)
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.reports.catalog import extract_search_text
from my_pa.domain.reports.content import ReportContent, canonical_json, content_of
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.lifecycle import LifecycleDecision, decide_lifecycle_transition
from my_pa.domain.reports.manifest import (
    ReportManifest,
    build_initial_manifest,
    build_version_manifest,
    manifest_digest,
)
from my_pa.domain.reports.publication import (
    PublicationReceipt,
    PublicationRequest,
    PublicationResult,
    RequestedAssociation,
)
from my_pa.domain.reports.records import (
    DEFAULT_HISTORY_PAGE,
    MAX_HISTORY_PAGE,
    MAX_HISTORY_PAGE_WITH_MANIFESTS,
    HistoryEntries,
    ReportHistoryPage,
    ReportLifecycleEventRecord,
    ReportRootRecord,
    ReportVersionRecord,
    ReportVersionSummary,
    StoredReportVersion,
)
from my_pa.domain.reports.revision import (
    LifecycleRequest,
    LifecycleResult,
    ReportSnapshot,
    UpdateRequest,
    UpdateResult,
    apply_patch,
    snapshot_of_version,
)
from my_pa.domain.reports.values import ReportAssociation
from my_pa.domain.reports.vocabulary import (
    MANIFEST_SCHEMA,
    AssociationTargetKind,
    AssociationVerification,
    ChangeKind,
    ContentEncoding,
    ContentFormat,
    LifecycleOperation,
    LifecycleState,
    ReceiptOperation,
    ReceiptOutcome,
    StorageKind,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence import conflicting_row
from my_pa.infrastructure.persistence.principal_scope import (
    PrincipalContext,
    capture_context,
    matching_partition_criterion,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    entities,
    intelligence_artifacts,
    projects,
    report_associations,
    report_content_objects,
    report_lifecycle_events,
    report_receipts,
    report_roots,
    report_version_manifests,
    report_versions,
)

__all__ = ["SqlGeneralReportRepository"]

#: The receipt constraint that admits one request per (owner, operation, key).
_KEY_CONSTRAINT: Final = "a_report_key_admits_one_request_per_operation"
_MAX_KEY_CHARACTERS: Final = 128

#: The table and identifier column each resolvable association kind names.
_TARGETS: Final[Mapping[AssociationTargetKind, tuple[Table, str]]] = {
    AssociationTargetKind.PROJECT: (projects, "project_id"),
    AssociationTargetKind.ENTITY: (entities, "entity_id"),
    AssociationTargetKind.STANDALONE_REPORT: (report_roots, "report_id"),
    AssociationTargetKind.INTELLIGENCE_REPORT: (intelligence_artifacts, "artifact_id"),
}

_TEXTUAL: Final = frozenset({ContentFormat.MARKDOWN, ContentFormat.TEXT})
_STRUCTURED: Final = frozenset({ContentFormat.JSON, ContentFormat.MIXED})


def _mine(table: Table, context: PrincipalContext) -> ColumnElement[bool]:
    return partition_criterion(table, context)


def _bound(values: dict[str, object], table: Table, context: PrincipalContext) -> dict[str, object]:
    return principal_bound_values(values, table, context)


def _constraint_name(error: IntegrityError) -> str | None:
    name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    return name if isinstance(name, str) else None


def _valid(value: str, kind: IdKind) -> bool:
    try:
        validate_identifier(value, kind)
    except InvalidIdentifierError:
        return False
    return True


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ReportValidationError(field, "naive")
    return value.astimezone(UTC)


# ---- publish -----------------------------------------------------------------------


def _find_publish(
    connection: Connection, idempotency_key: str, context: PrincipalContext
) -> PublicationResult | None:
    row = connection.execute(
        select(
            report_receipts.c.receipt_id,
            report_receipts.c.report_id,
            report_receipts.c.version_id,
            report_receipts.c.resulting_version_number,
            report_receipts.c.idempotency_key,
            report_receipts.c.intent_digest,
            report_receipts.c.outcome,
            report_receipts.c.issued_at,
            report_receipts.c.correlation_id,
            report_receipts.c.audit_id,
            report_versions.c.content_id,
            report_versions.c.manifest_sha256,
            report_versions.c.recorded_at,
            report_content_objects.c.format,
            report_content_objects.c.decoded_sha256,
            report_content_objects.c.decoded_byte_count,
            report_content_objects.c.canonical_sha256,
        )
        .join(
            report_versions,
            (report_versions.c.version_id == report_receipts.c.version_id)
            & matching_partition_criterion(report_versions, report_receipts),
        )
        .join(
            report_content_objects,
            (report_content_objects.c.content_id == report_versions.c.content_id)
            & matching_partition_criterion(report_content_objects, report_versions),
        )
        .where(
            _mine(report_receipts, context),
            report_receipts.c.operation == ReceiptOperation.PUBLISH.value,
            report_receipts.c.idempotency_key == idempotency_key,
        )
    ).one_or_none()
    if row is None:
        return None
    m = row._mapping
    return PublicationResult(
        receipt=PublicationReceipt(
            receipt_id=str(m["receipt_id"]),
            report_id=str(m["report_id"]),
            version_id=str(m["version_id"]),
            version_number=int(m["resulting_version_number"]),
            idempotency_key=str(m["idempotency_key"]),
            intent_digest=str(m["intent_digest"]),
            outcome=ReceiptOutcome(m["outcome"]),
            issued_at=m["issued_at"],
            correlation_id=str(m["correlation_id"]),
            audit_id=str(m["audit_id"]),
        ),
        content_id=str(m["content_id"]),
        format=ContentFormat(m["format"]),
        decoded_sha256=str(m["decoded_sha256"]),
        decoded_byte_count=int(m["decoded_byte_count"]),
        canonical_sha256=None if m["canonical_sha256"] is None else str(m["canonical_sha256"]),
        manifest_sha256=str(m["manifest_sha256"]),
        recorded_at=m["recorded_at"],
        replayed=True,
    )


def _settle(stored: PublicationResult, intent_digest: str) -> PublicationResult:
    """Replay a stored result of the same intent; refuse any other. Names neither."""
    if stored.receipt.intent_digest != intent_digest:
        raise ReportIdempotencyConflictError()
    return stored


def _resolve(
    connection: Connection,
    targets: Sequence[tuple[AssociationTargetKind, str]],
    context: PrincipalContext,
) -> frozenset[tuple[AssociationTargetKind, str]]:
    wanted: dict[AssociationTargetKind, set[str]] = {}
    for kind, ref in targets:
        if kind in _TARGETS:
            wanted.setdefault(kind, set()).add(ref)
    found: set[tuple[AssociationTargetKind, str]] = set()
    for kind, refs in wanted.items():
        table, column_name = _TARGETS[kind]
        column = table.c[column_name]
        rows = connection.execute(
            select(column).where(_mine(table, context), column.in_(sorted(refs)))
        ).all()
        found.update((kind, str(row[0])) for row in rows)
    return frozenset(found)


def _verified(
    connection: Connection,
    requested: Sequence[RequestedAssociation],
    context: PrincipalContext,
) -> tuple[ReportAssociation, ...]:
    resolved = _resolve(
        connection, [(item.target_kind, item.target_ref) for item in requested], context
    )
    stored: list[ReportAssociation] = []
    for item in requested:
        if item.target_kind is AssociationTargetKind.EXTERNAL_SOURCE:
            # Nothing here can check an external version, so it stays asserted text.
            stored.append(item.as_stored(AssociationVerification.ASSERTED))
        elif (item.target_kind, item.target_ref) in resolved and _version_verified(
            connection, item, context
        ):
            stored.append(item.as_stored(AssociationVerification.VERIFIED))
        else:
            raise ReportAssociationTargetNotFoundError()
    return tuple(stored)


def _version_verified(
    connection: Connection, item: RequestedAssociation, context: PrincipalContext
) -> bool:
    """Whether the association's `target_version_ref`, if any, is a version it can verify.

    Only a `standalone_report` has versions this plane can check: the ref must
    be a `grver_` of THAT report in the caller's scope. Every other verifiable
    kind has no version to check, so a non-null ref is refused rather than
    stored as `verified`. The refusal is the target's own not-found, so a
    foreign or absent version discloses nothing a foreign report would not.
    """
    ref = item.target_version_ref
    if ref is None:
        return True
    if item.target_kind is not AssociationTargetKind.STANDALONE_REPORT:
        return False
    if not _valid(ref, IdKind.REPORT_VERSION):
        return False
    row = connection.execute(
        select(report_versions.c.version_id).where(
            _mine(report_versions, context),
            report_versions.c.report_id == item.target_ref,
            report_versions.c.version_id == ref,
        )
    ).one_or_none()
    return row is not None


def _content_values(
    content: ReportContent, content_id: str, recorded_at: datetime
) -> dict[str, object]:
    values: dict[str, object] = {
        "content_id": content_id,
        "format": content.format.value,
        "original_encoding": content.encoding.value,
        "storage_kind": StorageKind.INLINE.value,
        "original_sha256": content.original_sha256,
        "original_byte_count": content.original_byte_count,
        "decoded_sha256": content.decoded_sha256,
        "decoded_byte_count": content.decoded_byte_count,
        "canonical_sha256": content.canonical_sha256,
        "created_at": recorded_at,
    }
    if content.format is not ContentFormat.JSON:
        values["inline_text"] = content.body
    # Omitted rather than `None` for textual content: bare `JSONB` writes a
    # Python `None` as the JSON `null`, not as SQL NULL.
    if content.format in _STRUCTURED:
        values["inline_data"] = content.data
    return values


def _write_publication(
    connection: Connection,
    request: PublicationRequest,
    associations: tuple[ReportAssociation, ...],
    *,
    context: PrincipalContext,
    idempotency_key: str,
    intent_digest: str,
    recorded_at: datetime,
    correlation_id: str,
    audit_id: str,
) -> PublicationResult:
    report_id = issue_identifier(IdKind.REPORT)
    version_id = issue_identifier(IdKind.REPORT_VERSION)
    content_id = issue_identifier(IdKind.REPORT_CONTENT)
    receipt_id = issue_identifier(IdKind.REPORT_RECEIPT)
    manifest = build_initial_manifest(
        request,
        report_id=report_id,
        version_id=version_id,
        content_id=content_id,
        associations=associations,
        recorded_at=recorded_at,
    )
    content = request.content
    connection.execute(
        report_content_objects.insert().values(
            **_bound(
                _content_values(content, content_id, recorded_at), report_content_objects, context
            )
        )
    )
    connection.execute(
        report_roots.insert().values(
            **_bound(
                {
                    "report_id": report_id,
                    "created_at": recorded_at,
                    "correlation_id": correlation_id,
                    "audit_id": audit_id,
                    "head_version_id": version_id,
                    "head_version_number": 1,
                    "lifecycle_state": LifecycleState.ACTIVE.value,
                    "lifecycle_revision": 0,
                    "lifecycle_event_id": None,
                },
                report_roots,
                context,
            )
        )
    )
    connection.execute(
        report_versions.insert().values(
            **_bound(
                {
                    "version_id": version_id,
                    "report_id": report_id,
                    "version_number": 1,
                    "supersedes_version_id": None,
                    "supersedes_version_number": None,
                    "content_id": content_id,
                    "change_kind": ChangeKind.INITIAL.value,
                    "title": request.title,
                    "report_type": request.report_type,
                    "topics": list(request.topics),
                    "tags": list(request.tags),
                    "summary": request.summary,
                    "report_date": request.report_date,
                    "coverage_start": request.coverage_start,
                    "coverage_end": request.coverage_end,
                    "metadata": dict(request.metadata),
                    "change_reason": None,
                    "manifest_sha256": manifest.sha256,
                    "recorded_at": recorded_at,
                    "correlation_id": correlation_id,
                    "audit_id": audit_id,
                    # WP04 C7: in the version's own INSERT, from the decoded content.
                    "search_text": extract_search_text(request.content),
                },
                report_versions,
                context,
            )
        )
    )
    connection.execute(
        report_version_manifests.insert().values(
            **_bound(
                {
                    "version_id": version_id,
                    "report_id": report_id,
                    "version_number": 1,
                    "manifest_schema": MANIFEST_SCHEMA,
                    "manifest": dict(manifest.document),
                    "manifest_sha256": manifest.sha256,
                    "recorded_at": recorded_at,
                },
                report_version_manifests,
                context,
            )
        )
    )
    for ordinal, association in enumerate(associations):
        verified = association.verification is AssociationVerification.VERIFIED
        connection.execute(
            report_associations.insert().values(
                **_bound(
                    {
                        "association_id": issue_identifier(IdKind.REPORT_ASSOCIATION),
                        "report_id": report_id,
                        "version_id": version_id,
                        "version_number": 1,
                        "ordinal": ordinal,
                        "target_kind": association.target_kind.value,
                        "target_ref": association.target_ref,
                        "target_version_ref": association.target_version_ref,
                        "relation": association.relation,
                        "verification": association.verification.value,
                        "observed_at": recorded_at if verified else None,
                        "recorded_at": recorded_at,
                    },
                    report_associations,
                    context,
                )
            )
        )
    connection.execute(
        report_receipts.insert().values(
            **_bound(
                {
                    "receipt_id": receipt_id,
                    "operation": ReceiptOperation.PUBLISH.value,
                    "idempotency_key": idempotency_key,
                    "intent_digest": intent_digest,
                    "report_id": report_id,
                    "outcome": ReceiptOutcome.APPLIED.value,
                    "version_id": version_id,
                    "resulting_version_number": 1,
                    "issued_at": recorded_at,
                    "correlation_id": correlation_id,
                    "audit_id": audit_id,
                },
                report_receipts,
                context,
            )
        )
    )
    return PublicationResult(
        receipt=PublicationReceipt(
            receipt_id=receipt_id,
            report_id=report_id,
            version_id=version_id,
            version_number=1,
            idempotency_key=idempotency_key,
            intent_digest=intent_digest,
            outcome=ReceiptOutcome.APPLIED,
            issued_at=recorded_at,
            correlation_id=correlation_id,
            audit_id=audit_id,
        ),
        content_id=content_id,
        format=content.format,
        decoded_sha256=content.decoded_sha256,
        decoded_byte_count=content.decoded_byte_count,
        canonical_sha256=content.canonical_sha256,
        manifest_sha256=manifest.sha256,
        recorded_at=recorded_at,
        replayed=False,
    )


# ---- read --------------------------------------------------------------------------


def _root(row: Row[Any]) -> ReportRootRecord:
    m = row._mapping
    return ReportRootRecord(
        report_id=str(m["report_id"]),
        created_at=m["created_at"],
        head_version_id=str(m["head_version_id"]),
        head_version_number=int(m["head_version_number"]),
        lifecycle_state=LifecycleState(m["lifecycle_state"]),
        lifecycle_revision=int(m["lifecycle_revision"]),
    )


def _version(row: Row[Any]) -> ReportVersionRecord:
    m = row._mapping
    return ReportVersionRecord(
        version_id=str(m["version_id"]),
        report_id=str(m["report_id"]),
        version_number=int(m["version_number"]),
        supersedes_version_id=m["supersedes_version_id"],
        change_kind=ChangeKind(m["change_kind"]),
        title=str(m["title"]),
        report_type=m["report_type"],
        topics=tuple(m["topics"]),
        tags=tuple(m["tags"]),
        summary=m["summary"],
        report_date=m["report_date"],
        coverage_start=m["coverage_start"],
        coverage_end=m["coverage_end"],
        metadata=m["metadata"],
        change_reason=m["change_reason"],
        content_id=str(m["content_id"]),
        manifest_sha256=str(m["manifest_sha256"]),
        recorded_at=m["recorded_at"],
    )


def _verified_content(row: Row[Any]) -> ReportContent:
    """Recompute the stored content's digests; refuse any the row does not match."""
    m = row._mapping
    content_format = ContentFormat(m["format"])
    if (
        m["storage_kind"] != StorageKind.INLINE.value
        or m["original_encoding"] != ContentEncoding.IDENTITY.value
    ):
        # WP02 writes only inline identity content; any other row is not one
        # this reader can recompute, so it refuses rather than trust it.
        raise ReportIntegrityError()
    try:
        content = content_of(
            content_format,
            body=None if content_format is ContentFormat.JSON else m["inline_text"],
            data=m["inline_data"] if content_format in _STRUCTURED else None,
        )
    except (ReportValidationError, ValueError, TypeError):
        raise ReportIntegrityError() from None
    if (
        content.decoded_sha256 != m["decoded_sha256"]
        or content.decoded_byte_count != m["decoded_byte_count"]
        or content.canonical_sha256 != m["canonical_sha256"]
        or content.original_sha256 != m["original_sha256"]
        or content.original_byte_count != m["original_byte_count"]
    ):
        raise ReportIntegrityError()
    return content


def _associations(rows: Sequence[Row[Any]]) -> tuple[ReportAssociation, ...]:
    return tuple(
        ReportAssociation(
            target_kind=AssociationTargetKind(row._mapping["target_kind"]),
            target_ref=str(row._mapping["target_ref"]),
            relation=str(row._mapping["relation"]),
            verification=AssociationVerification(row._mapping["verification"]),
            target_version_ref=row._mapping["target_version_ref"],
        )
        for row in rows
    )


def _association_rows(
    connection: Connection, version_id: str, context: PrincipalContext
) -> Sequence[Row[Any]]:
    return connection.execute(
        select(report_associations)
        .where(
            _mine(report_associations, context),
            report_associations.c.version_id == version_id,
        )
        .order_by(report_associations.c.ordinal)
    ).all()


def _expected_manifest(
    version: ReportVersionRecord,
    content: ReportContent,
    storage_kind: StorageKind,
    associations: Sequence[ReportAssociation],
) -> ReportManifest:
    """The whole manifest the stored rows of `version` require (D10), rebuilt."""
    return build_version_manifest(
        report_id=version.report_id,
        version_id=version.version_id,
        version_number=version.version_number,
        supersedes_version_id=version.supersedes_version_id,
        change_kind=version.change_kind,
        change_reason=version.change_reason,
        title=version.title,
        report_type=version.report_type,
        topics=version.topics,
        tags=version.tags,
        summary=version.summary,
        report_date=version.report_date,
        coverage_start=version.coverage_start,
        coverage_end=version.coverage_end,
        metadata=version.metadata,
        content=content,
        content_id=version.content_id,
        associations=associations,
        recorded_at=version.recorded_at,
        storage_kind=storage_kind,
    )


def _stored_version(
    connection: Connection,
    root: ReportRootRecord,
    version_row: Row[Any],
    context: PrincipalContext,
) -> StoredReportVersion:
    """Verify one version's rows and return them, or raise `ReportIntegrityError`.

    The content digests are recomputed from the stored body and data, and the
    whole manifest is rebuilt from the version, content and association rows
    with the shared builder: the stored document must equal it canonically and
    both stored digests must be its digest. A manifest that names another
    title, version, number, byte count or association is therefore refused
    whatever digests were stored with it.
    """
    try:
        version = _version(version_row)
    except (KeyError, TypeError, ValueError):
        raise ReportIntegrityError() from None
    if version.report_id != root.report_id:
        raise ReportIntegrityError()
    content_row = connection.execute(
        select(report_content_objects).where(
            _mine(report_content_objects, context),
            report_content_objects.c.content_id == version.content_id,
        )
    ).one()
    content = _verified_content(content_row)
    storage_kind = StorageKind(content_row._mapping["storage_kind"])
    manifest_row = connection.execute(
        select(
            report_version_manifests.c.manifest, report_version_manifests.c.manifest_sha256
        ).where(
            _mine(report_version_manifests, context),
            report_version_manifests.c.version_id == version.version_id,
        )
    ).one()
    manifest: Mapping[str, Any] = manifest_row[0]
    try:
        associations = _associations(_association_rows(connection, version.version_id, context))
        expected = _expected_manifest(version, content, storage_kind, associations)
        consistent = (
            canonical_json(manifest) == expected.canonical
            and manifest_digest(manifest)
            == expected.sha256
            == manifest_row[1]
            == version.manifest_sha256
        )
    except (ReportValidationError, KeyError, TypeError, ValueError):
        consistent = False
    if not consistent:
        raise ReportIntegrityError()
    return StoredReportVersion(
        root=root,
        version=version,
        content_id=version.content_id,
        storage_kind=storage_kind,
        content=content,
        manifest=manifest,
        associations=associations,
    )


def _find_root(
    connection: Connection, report_id: str, context: PrincipalContext, *, lock: bool = False
) -> ReportRootRecord | None:
    """The caller's root of `report_id`, `FOR UPDATE` when `lock`, or `None`."""
    if not _valid(report_id, IdKind.REPORT):
        return None
    statement = select(report_roots).where(
        _mine(report_roots, context), report_roots.c.report_id == report_id
    )
    if lock:
        statement = statement.with_for_update()
    row = connection.execute(statement).one_or_none()
    return None if row is None else _root(row)


def _read_version(
    connection: Connection,
    report_id: str,
    *,
    version_id: str | None,
    version_number: int | None,
    context: PrincipalContext,
    root: ReportRootRecord | None = None,
) -> StoredReportVersion | None:
    if version_id is not None and version_number is not None:
        raise ReportValidationError("version", "exclusive")
    if version_id is not None and not _valid(version_id, IdKind.REPORT_VERSION):
        return None
    if root is None:
        root = _find_root(connection, report_id, context)
    if root is None:
        return None
    selector: ColumnElement[bool]
    if version_number is not None:
        selector = report_versions.c.version_number == version_number
    else:
        selector = report_versions.c.version_id == (version_id or root.head_version_id)
    version_row = connection.execute(
        select(report_versions).where(
            _mine(report_versions, context), report_versions.c.report_id == report_id, selector
        )
    ).one_or_none()
    if version_row is None:
        return None
    return _stored_version(connection, root, version_row, context)


# ---- update ------------------------------------------------------------------------


def _find_update(
    connection: Connection, idempotency_key: str, context: PrincipalContext
) -> UpdateResult | None:
    row = connection.execute(
        select(
            report_receipts.c.receipt_id,
            report_receipts.c.report_id,
            report_receipts.c.outcome,
            report_receipts.c.expected_version_number,
            report_receipts.c.version_id,
            report_receipts.c.resulting_version_number,
            report_receipts.c.idempotency_key,
            report_receipts.c.intent_digest,
            report_receipts.c.issued_at,
            report_receipts.c.correlation_id,
            report_receipts.c.audit_id,
            report_versions.c.change_kind,
            report_versions.c.content_id,
            report_versions.c.manifest_sha256,
            report_content_objects.c.decoded_sha256,
        )
        .join(
            report_versions,
            (report_versions.c.version_id == report_receipts.c.version_id)
            & matching_partition_criterion(report_versions, report_receipts),
        )
        .join(
            report_content_objects,
            (report_content_objects.c.content_id == report_versions.c.content_id)
            & matching_partition_criterion(report_content_objects, report_versions),
        )
        .where(
            _mine(report_receipts, context),
            report_receipts.c.operation == ReceiptOperation.UPDATE.value,
            report_receipts.c.idempotency_key == idempotency_key,
        )
    ).one_or_none()
    if row is None:
        return None
    m = row._mapping
    outcome = ReceiptOutcome(m["outcome"])
    return UpdateResult(
        receipt_id=str(m["receipt_id"]),
        report_id=str(m["report_id"]),
        outcome=outcome,
        expected_version=int(m["expected_version_number"]),
        version_id=str(m["version_id"]),
        version_number=int(m["resulting_version_number"]),
        change_kind=ChangeKind(m["change_kind"]) if outcome is ReceiptOutcome.APPLIED else None,
        content_id=str(m["content_id"]),
        decoded_sha256=str(m["decoded_sha256"]),
        manifest_sha256=str(m["manifest_sha256"]),
        idempotency_key=str(m["idempotency_key"]),
        intent_digest=str(m["intent_digest"]),
        issued_at=m["issued_at"],
        correlation_id=str(m["correlation_id"]),
        audit_id=str(m["audit_id"]),
        replayed=True,
    )


def _settle_update(stored: UpdateResult, intent_digest: str) -> UpdateResult:
    if stored.intent_digest != intent_digest:
        raise ReportIdempotencyConflictError()
    return stored


def _insert_receipt(
    connection: Connection, values: dict[str, object], context: PrincipalContext
) -> None:
    connection.execute(report_receipts.insert().values(**_bound(values, report_receipts, context)))


def _write_update(
    connection: Connection,
    request: UpdateRequest,
    head: StoredReportVersion,
    result: ReportSnapshot,
    change_kind: ChangeKind | None,
    patched: tuple[ReportAssociation, ...] | None,
    *,
    context: PrincipalContext,
    idempotency_key: str,
    intent_digest: str,
    recorded_at: datetime,
    correlation_id: str,
    audit_id: str,
) -> UpdateResult:
    receipt_id = issue_identifier(IdKind.REPORT_RECEIPT)
    report_id = head.root.report_id
    expected = request.expected_version
    common: dict[str, object] = {
        "receipt_id": receipt_id,
        "operation": ReceiptOperation.UPDATE.value,
        "idempotency_key": idempotency_key,
        "intent_digest": intent_digest,
        "report_id": report_id,
        "expected_version_number": expected,
        "issued_at": recorded_at,
        "correlation_id": correlation_id,
        "audit_id": audit_id,
    }
    if change_kind is None:
        # D5: the snapshot is the head's; the receipt names the head it found.
        _insert_receipt(
            connection,
            {
                **common,
                "outcome": ReceiptOutcome.NO_OP.value,
                "version_id": head.version.version_id,
                "resulting_version_number": expected,
            },
            context,
        )
        return UpdateResult(
            receipt_id=receipt_id,
            report_id=report_id,
            outcome=ReceiptOutcome.NO_OP,
            expected_version=expected,
            version_id=head.version.version_id,
            version_number=expected,
            change_kind=None,
            content_id=head.content_id,
            decoded_sha256=head.content.decoded_sha256,
            manifest_sha256=head.version.manifest_sha256,
            idempotency_key=idempotency_key,
            intent_digest=intent_digest,
            issued_at=recorded_at,
            correlation_id=correlation_id,
            audit_id=audit_id,
            replayed=False,
        )
    number = expected + 1
    version_id = issue_identifier(IdKind.REPORT_VERSION)
    reused = result.content_key == (
        head.content.format.value,
        head.content.encoding.value,
        head.content.decoded_sha256,
    )
    content_id = head.content_id if reused else issue_identifier(IdKind.REPORT_CONTENT)
    carried: Sequence[Row[Any]] = ()
    if patched is None:
        carried = _association_rows(connection, head.version.version_id, context)
        associations = _associations(carried)
    else:
        associations = patched
    manifest = build_version_manifest(
        report_id=report_id,
        version_id=version_id,
        version_number=number,
        supersedes_version_id=head.version.version_id,
        change_kind=change_kind,
        change_reason=request.change_reason,
        title=result.title,
        report_type=result.report_type,
        topics=result.topics,
        tags=result.tags,
        summary=result.summary,
        report_date=result.report_date,
        coverage_start=result.coverage_start,
        coverage_end=result.coverage_end,
        metadata=result.metadata,
        content=result.content,
        content_id=content_id,
        associations=associations,
        recorded_at=recorded_at,
    )
    if not reused:
        connection.execute(
            report_content_objects.insert().values(
                **_bound(
                    _content_values(result.content, content_id, recorded_at),
                    report_content_objects,
                    context,
                )
            )
        )
    connection.execute(
        report_versions.insert().values(
            **_bound(
                {
                    "version_id": version_id,
                    "report_id": report_id,
                    "version_number": number,
                    "supersedes_version_id": head.version.version_id,
                    "supersedes_version_number": expected,
                    "content_id": content_id,
                    "change_kind": change_kind.value,
                    "title": result.title,
                    "report_type": result.report_type,
                    "topics": list(result.topics),
                    "tags": list(result.tags),
                    "summary": result.summary,
                    "report_date": result.report_date,
                    "coverage_start": result.coverage_start,
                    "coverage_end": result.coverage_end,
                    "metadata": dict(result.metadata),
                    "change_reason": request.change_reason,
                    "manifest_sha256": manifest.sha256,
                    "recorded_at": recorded_at,
                    "correlation_id": correlation_id,
                    "audit_id": audit_id,
                    # WP04 C7: recomputed from the version's content. A
                    # metadata-only update keeps the head's content (D5), so
                    # its search text is the head's exactly.
                    "search_text": extract_search_text(result.content),
                },
                report_versions,
                context,
            )
        )
    )
    connection.execute(
        report_version_manifests.insert().values(
            **_bound(
                {
                    "version_id": version_id,
                    "report_id": report_id,
                    "version_number": number,
                    "manifest_schema": MANIFEST_SCHEMA,
                    "manifest": dict(manifest.document),
                    "manifest_sha256": manifest.sha256,
                    "recorded_at": recorded_at,
                },
                report_version_manifests,
                context,
            )
        )
    )
    for ordinal, association in enumerate(associations):
        if patched is None:
            # D4: carried forward verbatim, its observation included.
            observed_at = carried[ordinal]._mapping["observed_at"]
        else:
            verified = association.verification is AssociationVerification.VERIFIED
            observed_at = recorded_at if verified else None
        connection.execute(
            report_associations.insert().values(
                **_bound(
                    {
                        "association_id": issue_identifier(IdKind.REPORT_ASSOCIATION),
                        "report_id": report_id,
                        "version_id": version_id,
                        "version_number": number,
                        "ordinal": ordinal,
                        "target_kind": association.target_kind.value,
                        "target_ref": association.target_ref,
                        "target_version_ref": association.target_version_ref,
                        "relation": association.relation,
                        "verification": association.verification.value,
                        "observed_at": observed_at,
                        "recorded_at": recorded_at,
                    },
                    report_associations,
                    context,
                )
            )
        )
    moved = connection.execute(
        report_roots.update()
        .where(
            _mine(report_roots, context),
            report_roots.c.report_id == report_id,
            report_roots.c.head_version_number == expected,
        )
        .values(head_version_id=version_id, head_version_number=number)
    ).rowcount
    if moved != 1:
        # The root is locked, so this is unreachable short of a broken lock.
        raise ReportStaleVersionError()
    _insert_receipt(
        connection,
        {
            **common,
            "outcome": ReceiptOutcome.APPLIED.value,
            "version_id": version_id,
            "resulting_version_number": number,
        },
        context,
    )
    return UpdateResult(
        receipt_id=receipt_id,
        report_id=report_id,
        outcome=ReceiptOutcome.APPLIED,
        expected_version=expected,
        version_id=version_id,
        version_number=number,
        change_kind=change_kind,
        content_id=content_id,
        decoded_sha256=result.content.decoded_sha256,
        manifest_sha256=manifest.sha256,
        idempotency_key=idempotency_key,
        intent_digest=intent_digest,
        issued_at=recorded_at,
        correlation_id=correlation_id,
        audit_id=audit_id,
        replayed=False,
    )


# ---- lifecycle ---------------------------------------------------------------------


def _find_transition(
    connection: Connection,
    operation: LifecycleOperation,
    idempotency_key: str,
    context: PrincipalContext,
) -> LifecycleResult | None:
    row = connection.execute(
        select(
            report_receipts.c.receipt_id,
            report_receipts.c.report_id,
            report_receipts.c.outcome,
            report_receipts.c.event_id,
            report_receipts.c.expected_lifecycle_revision,
            report_receipts.c.resulting_lifecycle_revision,
            report_receipts.c.idempotency_key,
            report_receipts.c.intent_digest,
            report_receipts.c.issued_at,
            report_receipts.c.correlation_id,
            report_receipts.c.audit_id,
            report_lifecycle_events.c.prior_state,
            report_lifecycle_events.c.resulting_state,
        )
        .select_from(
            report_receipts.outerjoin(
                report_lifecycle_events,
                (report_lifecycle_events.c.event_id == report_receipts.c.event_id)
                & matching_partition_criterion(report_lifecycle_events, report_receipts),
            )
        )
        .where(
            _mine(report_receipts, context),
            report_receipts.c.operation == operation.value,
            report_receipts.c.idempotency_key == idempotency_key,
        )
    ).one_or_none()
    if row is None:
        return None
    m = row._mapping
    outcome = ReceiptOutcome(m["outcome"])
    if outcome is ReceiptOutcome.APPLIED:
        prior, resulting = LifecycleState(m["prior_state"]), LifecycleState(m["resulting_state"])
    else:
        # The only lifecycle no-op is archive on `archived` (schema rule).
        prior = resulting = LifecycleState.ARCHIVED
    return LifecycleResult(
        receipt_id=str(m["receipt_id"]),
        report_id=str(m["report_id"]),
        operation=operation,
        outcome=outcome,
        prior_state=prior,
        resulting_state=resulting,
        expected_lifecycle_revision=int(m["expected_lifecycle_revision"]),
        lifecycle_revision=int(m["resulting_lifecycle_revision"]),
        event_id=None if m["event_id"] is None else str(m["event_id"]),
        idempotency_key=str(m["idempotency_key"]),
        intent_digest=str(m["intent_digest"]),
        issued_at=m["issued_at"],
        correlation_id=str(m["correlation_id"]),
        audit_id=str(m["audit_id"]),
        replayed=True,
    )


def _settle_transition(stored: LifecycleResult, intent_digest: str) -> LifecycleResult:
    if stored.intent_digest != intent_digest:
        raise ReportIdempotencyConflictError()
    return stored


def _current_event(
    connection: Connection, root: ReportRootRecord, context: PrincipalContext
) -> Row[Any] | None:
    if root.lifecycle_revision == 0:
        return None
    return connection.execute(
        select(report_lifecycle_events).where(
            _mine(report_lifecycle_events, context),
            report_lifecycle_events.c.report_id == root.report_id,
            report_lifecycle_events.c.lifecycle_revision == root.lifecycle_revision,
        )
    ).one()


def _write_transition(
    connection: Connection,
    request: LifecycleRequest,
    root: ReportRootRecord,
    current: Row[Any] | None,
    decision: LifecycleDecision,
    *,
    context: PrincipalContext,
    idempotency_key: str,
    intent_digest: str,
    recorded_at: datetime,
    correlation_id: str,
    audit_id: str,
) -> LifecycleResult:
    receipt_id = issue_identifier(IdKind.REPORT_RECEIPT)
    revision = root.lifecycle_revision
    common: dict[str, object] = {
        "receipt_id": receipt_id,
        "operation": request.operation.value,
        "idempotency_key": idempotency_key,
        "intent_digest": intent_digest,
        "report_id": root.report_id,
        "outcome": decision.outcome.value,
        "expected_lifecycle_revision": revision,
        "issued_at": recorded_at,
        "correlation_id": correlation_id,
        "audit_id": audit_id,
    }
    event_id: str | None
    if decision.outcome is ReceiptOutcome.NO_OP:
        # D7: the receipt names the current event only when it is an archive
        # (the event reference binds the operation); otherwise none.
        event_id = (
            str(current._mapping["event_id"])
            if current is not None
            and current._mapping["operation"] == LifecycleOperation.ARCHIVE.value
            else None
        )
        resulting_revision = revision
        _insert_receipt(
            connection,
            {**common, "event_id": event_id, "resulting_lifecycle_revision": revision},
            context,
        )
    else:
        event_id = issue_identifier(IdKind.REPORT_LIFECYCLE_EVENT)
        resulting_revision = revision + 1
        predecessor = None if current is None else current._mapping
        connection.execute(
            report_lifecycle_events.insert().values(
                **_bound(
                    {
                        "event_id": event_id,
                        "report_id": root.report_id,
                        "lifecycle_revision": resulting_revision,
                        "operation": request.operation.value,
                        "prior_state": decision.prior_state.value,
                        "resulting_state": decision.resulting_state.value,
                        "predecessor_event_id": None
                        if predecessor is None
                        else predecessor["event_id"],
                        "predecessor_revision": None
                        if predecessor is None
                        else predecessor["lifecycle_revision"],
                        "predecessor_prior_state": None
                        if predecessor is None
                        else predecessor["prior_state"],
                        "reason": request.reason,
                        "intent_digest": intent_digest,
                        "transitioned_at": recorded_at,
                        "correlation_id": correlation_id,
                        "audit_id": audit_id,
                    },
                    report_lifecycle_events,
                    context,
                )
            )
        )
        moved = connection.execute(
            report_roots.update()
            .where(
                _mine(report_roots, context),
                report_roots.c.report_id == root.report_id,
                report_roots.c.lifecycle_revision == revision,
            )
            .values(
                lifecycle_state=decision.resulting_state.value,
                lifecycle_revision=resulting_revision,
                lifecycle_event_id=event_id,
            )
        ).rowcount
        if moved != 1:
            raise ReportStaleLifecycleRevisionError()
        _insert_receipt(
            connection,
            {**common, "event_id": event_id, "resulting_lifecycle_revision": resulting_revision},
            context,
        )
    return LifecycleResult(
        receipt_id=receipt_id,
        report_id=root.report_id,
        operation=request.operation,
        outcome=decision.outcome,
        prior_state=decision.prior_state,
        resulting_state=decision.resulting_state,
        expected_lifecycle_revision=revision,
        lifecycle_revision=resulting_revision,
        event_id=event_id,
        idempotency_key=idempotency_key,
        intent_digest=intent_digest,
        issued_at=recorded_at,
        correlation_id=correlation_id,
        audit_id=audit_id,
        replayed=False,
    )


# ---- history -----------------------------------------------------------------------


def _page_size(value: object, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ReportValidationError("page_size", "bounds")
    return value


def _summary(stored: StoredReportVersion, *, include_manifest: bool) -> ReportVersionSummary:
    version, content = stored.version, stored.content
    return ReportVersionSummary(
        version_id=version.version_id,
        version_number=version.version_number,
        supersedes_version_id=version.supersedes_version_id,
        change_kind=version.change_kind,
        change_reason=version.change_reason,
        title=version.title,
        recorded_at=version.recorded_at,
        content_id=stored.content_id,
        format=content.format,
        encoding=content.encoding,
        storage_kind=stored.storage_kind,
        decoded_sha256=content.decoded_sha256,
        decoded_byte_count=content.decoded_byte_count,
        canonical_sha256=content.canonical_sha256,
        original_sha256=content.original_sha256,
        manifest_sha256=version.manifest_sha256,
        manifest=dict(stored.manifest) if include_manifest else None,
    )


def _version_history(
    connection: Connection,
    report_id: str,
    *,
    context: PrincipalContext,
    after_version_id: str | None,
    page_size: int,
    include_manifests: bool,
) -> ReportHistoryPage[ReportVersionSummary] | None:
    size = _page_size(
        page_size, MAX_HISTORY_PAGE_WITH_MANIFESTS if include_manifests else MAX_HISTORY_PAGE
    )
    root = _find_root(connection, report_id, context)
    if root is None:
        return None
    after = 0
    if after_version_id is not None:
        cursor = (
            connection.execute(
                select(report_versions.c.version_number).where(
                    _mine(report_versions, context),
                    report_versions.c.report_id == report_id,
                    report_versions.c.version_id == after_version_id,
                )
            ).scalar_one_or_none()
            if type(after_version_id) is str and _valid(after_version_id, IdKind.REPORT_VERSION)
            else None
        )
        if cursor is None:
            raise ReportValidationError("cursor", "unknown")
        after = int(cursor)
    rows = connection.execute(
        select(report_versions)
        .where(
            _mine(report_versions, context),
            report_versions.c.report_id == report_id,
            report_versions.c.version_number > after,
        )
        .order_by(report_versions.c.version_number)
        .limit(size + 1)
    ).all()
    items = tuple(
        _summary(
            _stored_version(connection, root, row, context), include_manifest=include_manifests
        )
        for row in rows[:size]
    )
    return ReportHistoryPage(
        root=root,
        entries=HistoryEntries.VERSIONS,
        items=items,
        next_cursor=items[-1].version_id if len(rows) > size else None,
    )


def _lifecycle_history(
    connection: Connection,
    report_id: str,
    *,
    context: PrincipalContext,
    after_event_id: str | None,
    page_size: int,
) -> ReportHistoryPage[ReportLifecycleEventRecord] | None:
    size = _page_size(page_size, MAX_HISTORY_PAGE)
    root = _find_root(connection, report_id, context)
    if root is None:
        return None
    after = 0
    if after_event_id is not None:
        cursor = (
            connection.execute(
                select(report_lifecycle_events.c.lifecycle_revision).where(
                    _mine(report_lifecycle_events, context),
                    report_lifecycle_events.c.report_id == report_id,
                    report_lifecycle_events.c.event_id == after_event_id,
                )
            ).scalar_one_or_none()
            if type(after_event_id) is str and _valid(after_event_id, IdKind.REPORT_LIFECYCLE_EVENT)
            else None
        )
        if cursor is None:
            raise ReportValidationError("cursor", "unknown")
        after = int(cursor)
    rows = connection.execute(
        select(report_lifecycle_events)
        .where(
            _mine(report_lifecycle_events, context),
            report_lifecycle_events.c.report_id == report_id,
            report_lifecycle_events.c.lifecycle_revision > after,
        )
        .order_by(report_lifecycle_events.c.lifecycle_revision)
        .limit(size + 1)
    ).all()
    items = tuple(
        ReportLifecycleEventRecord(
            event_id=str(row._mapping["event_id"]),
            lifecycle_revision=int(row._mapping["lifecycle_revision"]),
            operation=LifecycleOperation(row._mapping["operation"]),
            prior_state=LifecycleState(row._mapping["prior_state"]),
            resulting_state=LifecycleState(row._mapping["resulting_state"]),
            reason=row._mapping["reason"],
            transitioned_at=row._mapping["transitioned_at"],
        )
        for row in rows[:size]
    )
    return ReportHistoryPage(
        root=root,
        entries=HistoryEntries.LIFECYCLE,
        items=items,
        next_cursor=items[-1].event_id if len(rows) > size else None,
    )


class SqlGeneralReportRepository(GeneralReportRepository):
    """The general report port over one connection the caller owns.

    Constructed from the unit of work's open connection, so one publish
    commits or rolls back with the request. Each method derives its
    `PrincipalContext` from the authenticated `principal_id` through
    `capture_context`.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection: Final = connection

    def publish(
        self,
        request: PublicationRequest,
        *,
        principal_id: str,
        idempotency_key: str,
        recorded_at: datetime,
        correlation_id: str,
        audit_id: str,
    ) -> PublicationResult:
        context = capture_context(principal_id)
        recorded = self._admit(idempotency_key, correlation_id, audit_id, recorded_at)
        intent_digest = request.intent_digest
        stored = _find_publish(self._connection, idempotency_key, context)
        if stored is not None:
            return _settle(stored, intent_digest)
        associations = _verified(self._connection, request.associations, context)
        try:
            with self._connection.begin_nested():
                return _write_publication(
                    self._connection,
                    request,
                    associations,
                    context=context,
                    idempotency_key=idempotency_key,
                    intent_digest=intent_digest,
                    recorded_at=recorded,
                    correlation_id=correlation_id,
                    audit_id=audit_id,
                )
        except IntegrityError as error:
            if _constraint_name(error) != _KEY_CONSTRAINT:
                raise
        # A concurrent writer committed this key first; its rows are visible now.
        winner = conflicting_row(
            _find_publish(self._connection, idempotency_key, context), "knowledge.report_receipts"
        )
        return _settle(winner, intent_digest)

    def find_publish_receipt(
        self, idempotency_key: str, *, principal_id: str
    ) -> PublicationResult | None:
        return _find_publish(self._connection, idempotency_key, capture_context(principal_id))

    def read_version(
        self,
        report_id: str,
        *,
        principal_id: str,
        version_id: str | None = None,
        version_number: int | None = None,
    ) -> StoredReportVersion | None:
        return _read_version(
            self._connection,
            report_id,
            version_id=version_id,
            version_number=version_number,
            context=capture_context(principal_id),
        )

    def resolve_association_targets(
        self,
        targets: Sequence[tuple[AssociationTargetKind, str]],
        *,
        principal_id: str,
    ) -> frozenset[tuple[AssociationTargetKind, str]]:
        return _resolve(self._connection, targets, capture_context(principal_id))

    def update(
        self,
        request: UpdateRequest,
        *,
        principal_id: str,
        idempotency_key: str,
        recorded_at: datetime,
        correlation_id: str,
        audit_id: str,
    ) -> UpdateResult:
        context = capture_context(principal_id)
        recorded = self._admit(idempotency_key, correlation_id, audit_id, recorded_at)
        intent_digest = request.intent_digest
        connection = self._connection
        # D6 order: lock, key, state, CAS, writes.
        root = _find_root(connection, request.report_id, context, lock=True)
        if root is None:
            raise ReportNotFoundError()
        stored = _find_update(connection, idempotency_key, context)
        if stored is not None:
            return _settle_update(stored, intent_digest)
        if root.lifecycle_state is not LifecycleState.ACTIVE:
            raise ReportWithdrawnError()
        if root.head_version_number != request.expected_version:
            raise ReportStaleVersionError()
        head = _read_version(
            connection,
            root.report_id,
            version_id=root.head_version_id,
            version_number=None,
            context=context,
            root=root,
        )
        if head is None:
            raise ReportIntegrityError()
        patch = request.patch
        patched = (
            None
            if patch.associations is None
            else _verified(connection, patch.associations, context)
        )
        version = head.version
        result, change_kind = apply_patch(
            snapshot_of_version(
                title=version.title,
                content=head.content,
                report_type=version.report_type,
                topics=version.topics,
                tags=version.tags,
                summary=version.summary,
                report_date=version.report_date,
                coverage_start=version.coverage_start,
                coverage_end=version.coverage_end,
                metadata=version.metadata,
                associations=head.associations,
            ),
            patch,
            request.clear_fields,
        )
        try:
            with connection.begin_nested():
                return _write_update(
                    connection,
                    request,
                    head,
                    result,
                    change_kind,
                    patched,
                    context=context,
                    idempotency_key=idempotency_key,
                    intent_digest=intent_digest,
                    recorded_at=recorded,
                    correlation_id=correlation_id,
                    audit_id=audit_id,
                )
        except IntegrityError as error:
            if _constraint_name(error) != _KEY_CONSTRAINT:
                raise
        # The same key was committed for another report while this one ran.
        winner = conflicting_row(
            _find_update(connection, idempotency_key, context), "knowledge.report_receipts"
        )
        return _settle_update(winner, intent_digest)

    def transition(
        self,
        request: LifecycleRequest,
        *,
        principal_id: str,
        idempotency_key: str,
        recorded_at: datetime,
        correlation_id: str,
        audit_id: str,
    ) -> LifecycleResult:
        context = capture_context(principal_id)
        recorded = self._admit(idempotency_key, correlation_id, audit_id, recorded_at)
        intent_digest = request.intent_digest
        connection = self._connection
        # D7 order: lock, key, CAS, decide, writes.
        root = _find_root(connection, request.report_id, context, lock=True)
        if root is None:
            raise ReportNotFoundError()
        stored = _find_transition(connection, request.operation, idempotency_key, context)
        if stored is not None:
            return _settle_transition(stored, intent_digest)
        if root.lifecycle_revision != request.expected_lifecycle_revision:
            raise ReportStaleLifecycleRevisionError()
        current = _current_event(connection, root, context)
        trashed_from = (
            LifecycleState(current._mapping["prior_state"])
            if root.lifecycle_state is LifecycleState.TRASHED and current is not None
            else None
        )
        decision = decide_lifecycle_transition(
            root.lifecycle_state, request.operation, trashed_from=trashed_from
        )
        try:
            with connection.begin_nested():
                return _write_transition(
                    connection,
                    request,
                    root,
                    current,
                    decision,
                    context=context,
                    idempotency_key=idempotency_key,
                    intent_digest=intent_digest,
                    recorded_at=recorded,
                    correlation_id=correlation_id,
                    audit_id=audit_id,
                )
        except IntegrityError as error:
            if _constraint_name(error) != _KEY_CONSTRAINT:
                raise
        winner = conflicting_row(
            _find_transition(connection, request.operation, idempotency_key, context),
            "knowledge.report_receipts",
        )
        return _settle_transition(winner, intent_digest)

    def version_history(
        self,
        report_id: str,
        *,
        principal_id: str,
        after_version_id: str | None = None,
        page_size: int = DEFAULT_HISTORY_PAGE,
        include_manifests: bool = False,
    ) -> ReportHistoryPage[ReportVersionSummary] | None:
        return _version_history(
            self._connection,
            report_id,
            context=capture_context(principal_id),
            after_version_id=after_version_id,
            page_size=page_size,
            include_manifests=include_manifests,
        )

    def lifecycle_history(
        self,
        report_id: str,
        *,
        principal_id: str,
        after_event_id: str | None = None,
        page_size: int = DEFAULT_HISTORY_PAGE,
    ) -> ReportHistoryPage[ReportLifecycleEventRecord] | None:
        return _lifecycle_history(
            self._connection,
            report_id,
            context=capture_context(principal_id),
            after_event_id=after_event_id,
            page_size=page_size,
        )

    @staticmethod
    def _admit(
        idempotency_key: str, correlation_id: str, audit_id: str, recorded_at: datetime
    ) -> datetime:
        if not 1 <= len(idempotency_key) <= _MAX_KEY_CHARACTERS:
            raise ReportValidationError("idempotency_key", "bounds")
        validate_identifier(correlation_id, IdKind.CORRELATION)
        validate_identifier(audit_id, IdKind.AUDIT)
        return _utc(recorded_at, "recorded_at")
