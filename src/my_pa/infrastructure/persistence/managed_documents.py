"""The managed-document plane's statements: admit, read, and transition.

**There is no update and no delete in this module, and there is no way to write
one that works.** `managed_document_versions` and
`managed_document_lifecycle_events` both carry a `BEFORE UPDATE OR DELETE`
trigger that raises, so a statement added here would be refused by the server
rather than by this module's restraint. That separation is the one the capture
plane already makes for `capture_versions`: immutability enforced only by the
writer is a rule the next writer does not inherit.

**The order of the four inserts is the idempotency mechanism, not a
convenience.** `managed_document_submissions` is unique on
`(principal_id, idempotency_key)` and that row is written **first**, under
`ON CONFLICT DO NOTHING`. If it inserts, this request is the one that admits the
version and everything else follows. If it does not, the key is taken and the
stored `payload_sha256` decides which answer the caller gets: the same digest
returns the stored receipt, a different digest is a conflict and returns nothing.
Both foreign keys on that first row are `DEFERRABLE INITIALLY DEFERRED`, so they
are checked at commit, by which time the rows they name exist.

**Bytes are not here, and the ordering across the two stores is stated rather
than implied.** The caller writes and fsyncs the version's bytes *before* calling
`admit_managed_write`, and commits *after* it returns. The filesystem and the
database are not one transaction, and this module claims no atomicity across
them. What the ordering buys is that the surviving failure mode is the safe one:
a crash between the byte write and the commit leaves bytes with no row, which
`all_managed_version_identifiers` and the store's own walk find and an operator
reclaims. The reverse — a row naming absent bytes — is what no reconciliation can
repair, and this ordering never produces it.

**Every operation takes a `PrincipalContext` and is bound to it.** Writes stamp
the partition through `principal_bound_values`, so a request cannot supply one;
reads pass through `principal_scoped`, so a document another Principal owns
answers exactly what a document that does not exist answers — `None` from a read,
`UnknownScopeError` from a revise or a transition. The idempotency key's
collision domain is the Principal's own submissions, and the replay lookup
carries the same partition, so one Principal's replay can never return another's
receipt.

`all_managed_version_identifiers` is the one statement here that carries no
partition, and the reason is the direction of the question it answers: an orphan
sweep is about bytes that belong to *no* row, so a partitioned answer would
report every other Principal's objects as orphans. It returns opaque identifiers
and nothing else.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import Connection, Row, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from my_pa.contracts.ports import (
    ManagedAdmission,
    ManagedDocumentRepository,
    ManagedWriteRequest,
    UnknownScopeError,
)
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.documents.managed import (
    DocumentState,
    LifecycleTransition,
    ManagedDocument,
    ManagedDocumentConflictError,
    ManagedDocumentReceipt,
    ManagedDocumentVersion,
    StaleExpectedVersionError,
)
from my_pa.domain.identity.user_account import CallerSuppliedPrincipalError
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence import conflicting_row
from my_pa.infrastructure.persistence.principal_scope import (
    PrincipalContext,
    capture_context,
    principal_bound_values,
    principal_scoped,
    require_principal_context,
)
from my_pa.infrastructure.persistence.tables import (
    managed_document_lifecycle_events,
    managed_document_receipts,
    managed_document_submissions,
    managed_document_versions,
    managed_documents,
)

__all__ = [
    "SqlManagedDocumentRepository",
    "admit_managed_write",
    "all_managed_version_identifiers",
    "append_managed_transition",
    "insert_restored_version",
    "managed_document_page",
    "managed_document_state",
    "managed_replay_for",
    "managed_version",
    "managed_versions",
]

#: The columns a stored version is rebuilt from. Written out rather than
#: `select(managed_document_versions)`, so a column added to the table has to be
#: considered here rather than silently arriving as an unread mapping key.
_VERSION_COLUMNS: Final = (
    managed_document_versions.c.version_id,
    managed_document_versions.c.document_id,
    managed_document_versions.c.version_number,
    managed_document_versions.c.supersedes_version_id,
    managed_document_versions.c.owner_principal_id,
    managed_document_versions.c.title,
    managed_document_versions.c.media_type,
    managed_document_versions.c.content_sha256,
    managed_document_versions.c.byte_size,
    managed_document_versions.c.idempotency_key,
    managed_document_versions.c.correlation_id,
    managed_document_versions.c.recorded_at,
)


def _to_version(row: Row[tuple[object, ...]]) -> ManagedDocumentVersion:
    mapping = row._mapping
    supersedes = mapping["supersedes_version_id"]
    return ManagedDocumentVersion(
        version_id=str(mapping["version_id"]),
        document_id=str(mapping["document_id"]),
        version_number=int(mapping["version_number"]),
        supersedes_version_id=None if supersedes is None else str(supersedes),
        owner_principal_id=str(mapping["owner_principal_id"]),
        title=str(mapping["title"]),
        media_type=str(mapping["media_type"]),
        content_sha256=str(mapping["content_sha256"]),
        byte_size=int(mapping["byte_size"]),
        idempotency_key=str(mapping["idempotency_key"]),
        correlation_id=str(mapping["correlation_id"]),
        recorded_at=mapping["recorded_at"],
    )


def _receipt(
    connection: Connection, receipt_id: str, *, context: PrincipalContext, created: bool
) -> ManagedDocumentReceipt:
    """Rebuild one issued receipt from the two rows that hold its facts."""
    row = connection.execute(
        principal_scoped(
            select(
                managed_document_receipts.c.receipt_id,
                managed_document_receipts.c.idempotency_key,
                managed_document_receipts.c.issued_at,
                managed_document_versions.c.document_id,
                managed_document_versions.c.version_id,
                managed_document_versions.c.version_number,
                managed_document_versions.c.content_sha256,
                managed_document_versions.c.byte_size,
            ).join(
                managed_document_versions,
                managed_document_versions.c.version_id == managed_document_receipts.c.version_id,
            ),
            managed_document_receipts,
            context,
        ).where(managed_document_receipts.c.receipt_id == receipt_id)
    ).one()
    mapping = row._mapping
    return ManagedDocumentReceipt(
        receipt_id=str(mapping["receipt_id"]),
        document_id=str(mapping["document_id"]),
        version_id=str(mapping["version_id"]),
        version_number=int(mapping["version_number"]),
        idempotency_key=str(mapping["idempotency_key"]),
        content_sha256=str(mapping["content_sha256"]),
        byte_size=int(mapping["byte_size"]),
        issued_at=mapping["issued_at"],
        created=created,
    )


def _head(
    connection: Connection, document_id: str, *, context: PrincipalContext
) -> ManagedDocumentVersion | None:
    """The document's current version, read inside the admitting transaction.

    Scoped to the context's Principal, and that scoping is the ownership check on
    the revise path: a document another Principal owns has no head *for this
    caller*, so the revise refuses with the same answer a nonexistent document
    earns — which is what keeps the refusal from being an existence oracle.
    """
    row = connection.execute(
        principal_scoped(
            select(*_VERSION_COLUMNS).where(managed_document_versions.c.document_id == document_id),
            managed_document_versions,
            context,
        )
        .order_by(managed_document_versions.c.version_number.desc())
        .limit(1)
    ).one_or_none()
    return None if row is None else _to_version(row)


def admit_managed_write(
    connection: Connection, request: ManagedWriteRequest, *, context: PrincipalContext
) -> ManagedAdmission:
    """Admit one managed write, or return the receipt its key is already bound to.

    The request still carries a `principal_id` because the port shape mirrors the
    capture plane's, and it is **verified rather than trusted**: a request whose
    payload names a Principal other than the authenticated one is refused as
    `CallerSuppliedPrincipalError` before anything is written.
    """
    resolved = require_principal_context(context)
    if request.principal_id != resolved.capture_principal_id:
        raise CallerSuppliedPrincipalError("principal_id")

    submission_id = issue_identifier(IdKind.MANAGED_SUBMISSION)
    receipt_id = issue_identifier(IdKind.MANAGED_RECEIPT)
    admitted = connection.execute(
        pg_insert(managed_document_submissions)
        .values(
            **principal_bound_values(
                {
                    "submission_id": submission_id,
                    "idempotency_key": request.idempotency_key,
                    "correlation_id": request.correlation_id,
                    "payload_sha256": request.payload_digest,
                    "server_received_at": request.server_received_at,
                    "version_id": request.version_id,
                    "receipt_id": receipt_id,
                },
                managed_document_submissions,
                resolved,
            )
        )
        .on_conflict_do_nothing(constraint="a_managed_key_admits_one_submission_per_principal")
        .returning(managed_document_submissions.c.submission_id)
    ).one_or_none()

    if admitted is None:
        return _replay(connection, request, context=resolved)

    _chain(connection, request, context=resolved)
    connection.execute(
        managed_document_receipts.insert().values(
            **principal_bound_values(
                {
                    "receipt_id": receipt_id,
                    "version_id": request.version_id,
                    "idempotency_key": request.idempotency_key,
                },
                managed_document_receipts,
                resolved,
            )
        )
    )
    return ManagedAdmission(
        receipt=_receipt(connection, receipt_id, context=resolved, created=True), created=True
    )


def _replay(
    connection: Connection, request: ManagedWriteRequest, *, context: PrincipalContext
) -> ManagedAdmission:
    """Answer a request whose idempotency key is already in use.

    The stored payload digest is what decides, and it is compared rather than the
    content: this module never needs a second copy of the bytes to know whether
    two requests carried the same ones. Which field differs is deliberately not
    reported — that would describe the stored request to whoever guessed the key.
    """
    row = connection.execute(
        principal_scoped(
            select(
                managed_document_submissions.c.payload_sha256,
                managed_document_submissions.c.receipt_id,
            ).where(managed_document_submissions.c.idempotency_key == request.idempotency_key),
            managed_document_submissions,
            context,
        )
    ).one_or_none()
    stored = conflicting_row(row, "knowledge.managed_document_submissions")
    if str(stored[0]) != request.payload_digest:
        raise ManagedDocumentConflictError("the idempotency key is bound to a different request")
    return ManagedAdmission(
        receipt=_receipt(connection, str(stored[1]), context=context, created=False), created=False
    )


def _chain(
    connection: Connection, request: ManagedWriteRequest, *, context: PrincipalContext
) -> str:
    """Insert the version, starting a chain or appending to one. Returns the document.

    A create issues a new `mdoc_…` and writes version one, which supersedes
    nothing. A revise reads the document's head, compares it against the version
    the caller expected, and writes the next number superseding it — and writes no
    `UPDATE` anywhere, which is why `managed_documents` carries no head pointer to
    keep in step.

    **The expected-version check and the unique constraint are both required and
    neither is redundant.** The comparison gives a stale writer a clear, safe
    refusal; the `UNIQUE (document_id, version_number)` and `UNIQUE
    (supersedes_version_id)` constraints are what make two concurrent writers that
    read the same head produce one winner, because the second insert is refused by
    the server rather than by a check that already ran.
    """
    if request.document_id is None:
        document_id = issue_identifier(IdKind.MANAGED_DOCUMENT)
        connection.execute(
            managed_documents.insert().values(
                **principal_bound_values({"document_id": document_id}, managed_documents, context)
            )
        )
        version_number, supersedes = 1, None
    else:
        document_id = validate_identifier(request.document_id, IdKind.MANAGED_DOCUMENT)
        head = _head(connection, document_id, context=context)
        if head is None:
            # No such document, or one another Principal owns — one answer for
            # both, naming no identifier, so a caller cannot use the refusal to
            # learn whether a document it may not see exists.
            raise UnknownScopeError("the request names no stored managed document")
        if head.version_number != request.expected_version_number:
            raise StaleExpectedVersionError("the expected version is not this document's head")
        version_number, supersedes = head.version_number + 1, head.version_id

    connection.execute(
        managed_document_versions.insert().values(
            **principal_bound_values(
                {
                    "version_id": request.version_id,
                    "document_id": document_id,
                    "version_number": version_number,
                    "supersedes_version_id": supersedes,
                    "title": request.title,
                    "media_type": request.media_type,
                    "content_sha256": request.content_sha256,
                    "byte_size": request.byte_size,
                    "idempotency_key": request.idempotency_key,
                    "correlation_id": request.correlation_id,
                    # The server's own clock inside the statement, so it is a
                    # different reading from the one the request carried and
                    # cannot be made equal to it by a caller passing it twice.
                    "recorded_at": func.now(),
                },
                managed_document_versions,
                context,
            )
        )
    )
    return document_id


def managed_replay_for(
    connection: Connection,
    idempotency_key: str,
    payload_digest: str,
    *,
    context: PrincipalContext,
) -> ManagedDocumentReceipt | None:
    """The receipt this Principal's key is bound to, or `None`, or a conflict.

    The digest is compared here and not only in `admit`, and the reason is a
    defect this package's own tests caught: a pre-read on the key alone answered
    a *conflicting* request with the original receipt, so a second write carrying
    the same key and different bytes was reported as durable while nothing had
    been stored. Comparing the digest makes the pre-read agree with the
    constraint it is standing in front of rather than shadow it.
    """
    row = connection.execute(
        principal_scoped(
            select(
                managed_document_submissions.c.payload_sha256,
                managed_document_submissions.c.receipt_id,
            ).where(managed_document_submissions.c.idempotency_key == idempotency_key),
            managed_document_submissions,
            context,
        )
    ).one_or_none()
    if row is None:
        return None
    if str(row[0]) != payload_digest:
        raise ManagedDocumentConflictError("the idempotency key is bound to a different request")
    return _receipt(connection, str(row[1]), context=context, created=False)


def managed_version(
    connection: Connection,
    document_id: str,
    *,
    version_id: str | None = None,
    context: PrincipalContext,
) -> ManagedDocumentVersion | None:
    """One stored version of `document_id` the context's Principal owns, or `None`.

    The document is part of the lookup rather than derived from the version, so a
    version identifier belonging to a different document answers `None` — the same
    answer as one that names nothing, and the same answer as one another Principal
    owns: three absences, one response.
    """
    validate_identifier(document_id, IdKind.MANAGED_DOCUMENT)
    statement = principal_scoped(
        select(*_VERSION_COLUMNS).where(managed_document_versions.c.document_id == document_id),
        managed_document_versions,
        context,
    )
    if version_id is None:
        statement = statement.order_by(managed_document_versions.c.version_number.desc()).limit(1)
    else:
        validate_identifier(version_id, IdKind.MANAGED_DOCUMENT_VERSION)
        statement = statement.where(managed_document_versions.c.version_id == version_id)
    row = connection.execute(statement).one_or_none()
    return None if row is None else _to_version(row)


def managed_versions(
    connection: Connection, document_id: str, *, context: PrincipalContext
) -> tuple[ManagedDocumentVersion, ...]:
    """Every stored version of one document this Principal owns, oldest first."""
    validate_identifier(document_id, IdKind.MANAGED_DOCUMENT)
    rows = connection.execute(
        principal_scoped(
            select(*_VERSION_COLUMNS).where(managed_document_versions.c.document_id == document_id),
            managed_document_versions,
            context,
        ).order_by(managed_document_versions.c.version_number)
    ).all()
    return tuple(_to_version(row) for row in rows)


def managed_document_state(
    connection: Connection, document_id: str, *, context: PrincipalContext
) -> DocumentState | None:
    """Whether a document this Principal owns is active or archived, or `None`.

    The state is the state the latest transition implies, read from the
    append-only lifecycle rows. A document with no transitions is active, which is
    why there is no row written when one is created: the absence of a transition
    is the initial state rather than a row asserting it.
    """
    validate_identifier(document_id, IdKind.MANAGED_DOCUMENT)
    owned = connection.execute(
        principal_scoped(
            select(managed_documents.c.document_id).where(
                managed_documents.c.document_id == document_id
            ),
            managed_documents,
            context,
        )
    ).one_or_none()
    if owned is None:
        return None
    latest = connection.execute(
        principal_scoped(
            select(managed_document_lifecycle_events.c.transition).where(
                managed_document_lifecycle_events.c.document_id == document_id
            ),
            managed_document_lifecycle_events,
            context,
        )
        .order_by(managed_document_lifecycle_events.c.sequence_number.desc())
        .limit(1)
    ).one_or_none()
    if latest is None:
        return DocumentState.ACTIVE
    return LifecycleTransition(str(latest[0])).resulting_state()


def append_managed_transition(
    connection: Connection,
    document_id: str,
    *,
    transition: LifecycleTransition,
    correlation_id: str,
    context: PrincipalContext,
) -> bool:
    """Append one lifecycle row, and report whether it changed anything.

    Archiving an already-archived document appends nothing and answers `False`,
    which is the idempotent reading: the caller asked for a state and the document
    is in it. The unique `(document_id, sequence_number)` constraint is what makes
    two concurrent archives one winner rather than two rows.
    """
    current = managed_document_state(connection, document_id, context=context)
    if current is None:
        raise UnknownScopeError("the request names no stored managed document")
    if current is transition.resulting_state():
        return False
    highest = connection.execute(
        principal_scoped(
            select(func.max(managed_document_lifecycle_events.c.sequence_number)).where(
                managed_document_lifecycle_events.c.document_id == document_id
            ),
            managed_document_lifecycle_events,
            context,
        )
    ).scalar_one_or_none()
    connection.execute(
        managed_document_lifecycle_events.insert().values(
            **principal_bound_values(
                {
                    "event_id": issue_identifier(IdKind.MANAGED_LIFECYCLE),
                    "document_id": document_id,
                    "transition": transition.value,
                    "sequence_number": 1 if highest is None else int(highest) + 1,
                    "correlation_id": correlation_id,
                    "recorded_at": func.now(),
                },
                managed_document_lifecycle_events,
                context,
            )
        )
    )
    return True


def managed_document_page(
    connection: Connection,
    *,
    limit: int,
    context: PrincipalContext,
    include_archived: bool = False,
) -> tuple[ManagedDocument, ...]:
    """One bounded page of the context Principal's documents, newest first.

    The page is scoped before it is limited, so another Principal's documents do
    not occupy slots in this one's page any more than they appear in it.
    """
    if limit < 1:
        raise ValueError("a page holds at least one managed document")
    latest_number = func.max(managed_document_versions.c.version_number)
    rows = connection.execute(
        principal_scoped(
            select(
                managed_documents.c.document_id,
                managed_documents.c.owner_principal_id,
                managed_documents.c.created_at,
                func.count().label("version_count"),
                latest_number.label("latest_version_number"),
            ).join(
                managed_document_versions,
                managed_document_versions.c.document_id == managed_documents.c.document_id,
            ),
            managed_documents,
            context,
        )
        .group_by(
            managed_documents.c.document_id,
            managed_documents.c.owner_principal_id,
            managed_documents.c.created_at,
        )
        .order_by(managed_documents.c.created_at.desc(), managed_documents.c.document_id)
        .limit(limit)
    ).all()

    found: list[ManagedDocument] = []
    for row in rows:
        mapping = row._mapping
        document_id = str(mapping["document_id"])
        state = managed_document_state(connection, document_id, context=context)
        if state is None:  # pragma: no cover - the row was just read in this partition
            continue
        if state is DocumentState.ARCHIVED and not include_archived:
            continue
        head = managed_version(connection, document_id, context=context)
        if head is None:  # pragma: no cover - a document has at least one version
            continue
        found.append(
            ManagedDocument(
                document_id=document_id,
                owner_principal_id=str(mapping["owner_principal_id"]),
                state=state,
                title=head.title,
                media_type=head.media_type,
                version_count=int(mapping["version_count"]),
                latest_version_id=head.version_id,
                latest_version_number=int(mapping["latest_version_number"]),
                created_at=mapping["created_at"],
                latest_recorded_at=head.recorded_at,
            )
        )
    return tuple(found)


def insert_restored_version(
    connection: Connection, version: ManagedDocumentVersion, *, context: PrincipalContext
) -> None:
    """Insert one version exactly as a backup recorded it.

    The only writer that supplies its own version number, predecessor and
    timestamp: a restore has to reproduce the chain rather than start a new one.
    The document row is created if it is absent, under the same partition stamp,
    so a restore into an empty database rebuilds both.

    `principal_bound_values` refuses values that already name the partition
    column, so the version's stored `owner_principal_id` is deliberately *not*
    passed through: the partition comes from the context, and a backup that named
    another Principal's owner cannot move a document between partitions by being
    restored.
    """
    connection.execute(
        pg_insert(managed_documents)
        .values(
            **principal_bound_values(
                {"document_id": version.document_id, "created_at": version.recorded_at},
                managed_documents,
                context,
            )
        )
        .on_conflict_do_nothing(index_elements=[managed_documents.c.document_id])
    )
    connection.execute(
        managed_document_versions.insert().values(
            **principal_bound_values(
                {
                    "version_id": version.version_id,
                    "document_id": version.document_id,
                    "version_number": version.version_number,
                    "supersedes_version_id": version.supersedes_version_id,
                    "title": version.title,
                    "media_type": version.media_type,
                    "content_sha256": version.content_sha256,
                    "byte_size": version.byte_size,
                    "idempotency_key": version.idempotency_key,
                    "correlation_id": version.correlation_id,
                    "recorded_at": version.recorded_at,
                },
                managed_document_versions,
                context,
            )
        )
    )


def all_managed_version_identifiers(connection: Connection) -> frozenset[str]:
    """Every managed version identifier the database holds, across Principals.

    The one statement in this module that carries no partition, and it is
    unpartitioned because of the direction of the question: the reconciliation it
    serves is about bytes in the store that belong to **no** row, and a
    partitioned answer would report every other Principal's objects as orphans —
    which is how a reclamation deletes live data.

    It returns opaque identifiers and nothing else: no title, no digest, no owner,
    no content, and no way to reach any of them. Operator use only.
    """
    return frozenset(
        str(row[0])
        for row in connection.execute(select(managed_document_versions.c.version_id)).all()
    )


class SqlManagedDocumentRepository(ManagedDocumentRepository):
    """The managed-document port over one connection the caller owns.

    The same shape `SqlContinuityRepository` takes: constructed from a
    `Connection` inside the caller's transaction, so the whole of one managed
    write — the submission, the document, the version and the receipt — commits or
    rolls back together. The byte write is *not* in that transaction and cannot
    be; the module docstring states which failure it leaves and how it is
    reconciled.

    Each method derives its `PrincipalContext` from the `principal_id` it is
    given, through `capture_context`, so there is one translation of an already
    authenticated identity and no path by which a caller supplies a partition.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection: Final = connection

    def admit(self, request: ManagedWriteRequest) -> ManagedAdmission:
        return admit_managed_write(
            self._connection, request, context=capture_context(request.principal_id)
        )

    def replay_for(
        self, idempotency_key: str, payload_digest: str, *, principal_id: str
    ) -> ManagedDocumentReceipt | None:
        return managed_replay_for(
            self._connection,
            idempotency_key,
            payload_digest,
            context=capture_context(principal_id),
        )

    def version(
        self, document_id: str, *, version_id: str | None = None, principal_id: str
    ) -> ManagedDocumentVersion | None:
        return managed_version(
            self._connection,
            document_id,
            version_id=version_id,
            context=capture_context(principal_id),
        )

    def versions(
        self, document_id: str, *, principal_id: str
    ) -> tuple[ManagedDocumentVersion, ...]:
        return managed_versions(
            self._connection, document_id, context=capture_context(principal_id)
        )

    def documents(
        self, *, limit: int, principal_id: str, include_archived: bool = False
    ) -> tuple[ManagedDocument, ...]:
        return managed_document_page(
            self._connection,
            limit=limit,
            context=capture_context(principal_id),
            include_archived=include_archived,
        )

    def state(self, document_id: str, *, principal_id: str) -> DocumentState | None:
        return managed_document_state(
            self._connection, document_id, context=capture_context(principal_id)
        )

    def transition(
        self,
        document_id: str,
        *,
        transition: LifecycleTransition,
        principal_id: str,
        correlation_id: str,
    ) -> bool:
        return append_managed_transition(
            self._connection,
            document_id,
            transition=transition,
            correlation_id=correlation_id,
            context=capture_context(principal_id),
        )

    def restore_version(self, version: ManagedDocumentVersion, *, principal_id: str) -> None:
        insert_restored_version(self._connection, version, context=capture_context(principal_id))

    def known_version_identifiers(self) -> frozenset[str]:
        return all_managed_version_identifiers(self._connection)
