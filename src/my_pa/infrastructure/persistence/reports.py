"""The general report plane's statements: publish, replay, read, resolve (WP02).

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

**A read recomputes before it answers.** The decoded content digest is
recomputed from the stored body and data, and the manifest digest from the
stored manifest; a mismatch with the stored digests or byte counts, or a
manifest whose report, version, version number or title is not the version
row's, raises `ReportIntegrityError`. jsonb reproduces the canonical bytes: keys are
re-sorted by `canonical_json`, and every number the domain admits prints back
with the digits it was written with (`-0.0` is normalized to `0.0` before
hashing, because `numeric` has no negative zero).

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
)
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.reports.content import ReportContent, content_of
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.manifest import build_initial_manifest, manifest_digest
from my_pa.domain.reports.publication import (
    PublicationReceipt,
    PublicationRequest,
    PublicationResult,
    RequestedAssociation,
)
from my_pa.domain.reports.records import (
    ReportRootRecord,
    ReportVersionRecord,
    StoredReportVersion,
)
from my_pa.domain.reports.values import ReportAssociation
from my_pa.domain.reports.vocabulary import (
    MANIFEST_SCHEMA,
    AssociationTargetKind,
    AssociationVerification,
    ChangeKind,
    ContentEncoding,
    ContentFormat,
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


def _read_version(
    connection: Connection,
    report_id: str,
    *,
    version_id: str | None,
    version_number: int | None,
    context: PrincipalContext,
) -> StoredReportVersion | None:
    if version_id is not None and version_number is not None:
        raise ReportValidationError("version", "exclusive")
    if not _valid(report_id, IdKind.REPORT):
        return None
    if version_id is not None and not _valid(version_id, IdKind.REPORT_VERSION):
        return None
    root_row = connection.execute(
        select(report_roots).where(
            _mine(report_roots, context), report_roots.c.report_id == report_id
        )
    ).one_or_none()
    if root_row is None:
        return None
    root = _root(root_row)
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
    version = _version(version_row)
    content_row = connection.execute(
        select(report_content_objects).where(
            _mine(report_content_objects, context),
            report_content_objects.c.content_id == version.content_id,
        )
    ).one()
    content = _verified_content(content_row)
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
        recomputed = manifest_digest(manifest)
        described = manifest["content"]
        consistent = (
            recomputed == manifest_row[1] == version.manifest_sha256
            and described["content_id"] == version.content_id
            and described["decoded_sha256"] == content.decoded_sha256
            and described["decoded_byte_count"] == content.decoded_byte_count
            and described["original_byte_count"] == content.original_byte_count
            # The manifest names the version it describes; one that names
            # another (with its digest recomputed to match) is refused too.
            and manifest["report_id"] == version.report_id == root.report_id
            and manifest["version_id"] == version.version_id
            and manifest["version_number"] == version.version_number
            and manifest["title"] == version.title
        )
    except (KeyError, TypeError, ValueError):
        consistent = False
    if not consistent:
        raise ReportIntegrityError()
    association_rows = connection.execute(
        select(report_associations)
        .where(
            _mine(report_associations, context),
            report_associations.c.version_id == version.version_id,
        )
        .order_by(report_associations.c.ordinal)
    ).all()
    associations = tuple(
        ReportAssociation(
            target_kind=AssociationTargetKind(row._mapping["target_kind"]),
            target_ref=str(row._mapping["target_ref"]),
            relation=str(row._mapping["relation"]),
            verification=AssociationVerification(row._mapping["verification"]),
            target_version_ref=row._mapping["target_version_ref"],
        )
        for row in association_rows
    )
    return StoredReportVersion(
        root=root,
        version=version,
        content_id=version.content_id,
        storage_kind=StorageKind(content_row._mapping["storage_kind"]),
        content=content,
        manifest=manifest,
        associations=associations,
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
        if not 1 <= len(idempotency_key) <= _MAX_KEY_CHARACTERS:
            raise ReportValidationError("idempotency_key", "bounds")
        validate_identifier(correlation_id, IdKind.CORRELATION)
        validate_identifier(audit_id, IdKind.AUDIT)
        recorded = _utc(recorded_at, "recorded_at")
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
