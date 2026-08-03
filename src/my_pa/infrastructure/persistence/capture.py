"""Admitting one capture, and reading stored versions back.

Three operations. Admit this submission, or tell me the receipt its idempotency
key is already bound to; read one version; list what is there.

**There is no update and no delete in this module, and there is no way to write
one that works.** `capture_versions` carries a `BEFORE UPDATE OR DELETE` trigger
that raises, so a statement added here would be refused by the server rather
than by this module's restraint. That separation is deliberate: `QC-AC-010` asks
for immutability under concurrent write, and a rule enforced only by the writer
is a rule the next writer does not inherit.

**The order of the four inserts is the idempotency mechanism, not a
convenience.** `capture_submissions.idempotency_key` is `NOT NULL UNIQUE` and
that row is written **first**, under `ON CONFLICT DO NOTHING`. If it inserts,
this request is the one that admits the capture and everything else follows. If
it does not, the key is taken, nothing has been written, and the stored
`payload_sha256` decides which answer the caller gets: the same digest is the
`QC-AC-031` replay and returns the stored receipt, a different digest is the
`QC-AC-032` conflict and returns nothing at all.

Doing it the other way round — capture, version, receipt, and the submission
last — would mean discovering the key was taken only after three rows had been
written, and undoing them would need a savepoint. The two foreign keys on that
first row are therefore `DEFERRABLE INITIALLY DEFERRED`: they are checked at
commit, by which time the rows they name exist. Checking first and inserting
second is the window the unique constraint exists to close, and is what
`persistence.enrollment` refuses for the same reason.

**Nothing here reads or writes a source.** ADR-003 clause 5 makes capture a
product-owned record rather than a source read, and this module imports no
provider, no registry, and no source table.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final, NamedTuple

from sqlalchemy import Connection, Row, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from my_pa.contracts.ports import (
    CaptureAdmission,
    CaptureAdmissionRequest,
    CaptureSummary,
    UnknownScopeError,
)
from my_pa.domain.capture.errors import CaptureConflictError
from my_pa.domain.capture.submission import (
    AdmissionResult,
    CaptureMethod,
    CaptureReceipt,
    CaptureTransport,
    TrustState,
)
from my_pa.domain.capture.version import CaptureContent, CaptureVersion, ProcessingPolicy
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence import conflicting_row
from my_pa.infrastructure.persistence.jobs import CAPTURE_JOBS, enqueue_job
from my_pa.infrastructure.persistence.tables import (
    capture_receipts,
    capture_submissions,
    capture_versions,
    captures,
)

__all__ = [
    "admit_capture",
    "capture_page",
    "capture_version",
]

#: The columns a stored version is rebuilt from. Written out rather than
#: `select(capture_versions)`, so a column added to the table has to be
#: considered here rather than silently arriving as an unread mapping key.
_VERSION_COLUMNS: Final = (
    capture_versions.c.version_id,
    capture_versions.c.capture_id,
    capture_versions.c.version_number,
    capture_versions.c.supersedes_version_id,
    capture_versions.c.content,
    capture_versions.c.owner_principal_id,
    capture_versions.c.classification,
    capture_versions.c.processing_policy,
    capture_versions.c.idempotency_key,
    capture_versions.c.correlation_id,
    capture_versions.c.audit_id,
    capture_versions.c.client_created_at,
    capture_versions.c.server_received_at,
    capture_versions.c.occurred_at,
    capture_versions.c.accepted_at,
    capture_versions.c.recorded_at,
)


class _Head(NamedTuple):
    """Where a capture's chain has got to: its latest version and that number."""

    version_id: str
    version_number: int


def _to_version(row: Row[tuple[object, ...]]) -> CaptureVersion:
    mapping = row._mapping
    return CaptureVersion(
        version_id=str(mapping["version_id"]),
        capture_id=str(mapping["capture_id"]),
        version_number=int(mapping["version_number"]),
        supersedes_version_id=mapping["supersedes_version_id"],
        content=CaptureContent(str(mapping["content"])),
        owner_principal_id=str(mapping["owner_principal_id"]),
        classification=Classification(mapping["classification"]),
        processing_policy=ProcessingPolicy(mapping["processing_policy"]),
        idempotency_key=str(mapping["idempotency_key"]),
        correlation_id=str(mapping["correlation_id"]),
        audit_id=str(mapping["audit_id"]),
        client_created_at=mapping["client_created_at"],
        server_received_at=mapping["server_received_at"],
        occurred_at=mapping["occurred_at"],
        accepted_at=mapping["accepted_at"],
        recorded_at=mapping["recorded_at"],
    )


def _head(connection: Connection, capture_id: str) -> _Head | None:
    """The capture's current version, read inside the admitting transaction.

    A concurrent revise that read the same head cannot also store it: the two
    would insert the same `(capture_id, version_number)` and the same
    `supersedes_version_id`, and both constraints are unique. The loser is
    refused by the server rather than by a check that already ran, which is the
    same discipline `persistence.enrollment` states for idempotency keys.
    """
    row: Row[tuple[str, int]] | None = connection.execute(
        select(capture_versions.c.version_id, capture_versions.c.version_number)
        .where(capture_versions.c.capture_id == capture_id)
        .order_by(capture_versions.c.version_number.desc())
        .limit(1)
    ).one_or_none()
    return None if row is None else _Head(str(row[0]), int(row[1]))


def _receipt(connection: Connection, receipt_id: str) -> CaptureReceipt:
    """Rebuild one issued receipt from the two rows that hold its facts."""
    row = connection.execute(
        select(
            capture_receipts.c.receipt_id,
            capture_receipts.c.idempotency_key,
            capture_receipts.c.issued_at,
            capture_versions.c.capture_id,
            capture_versions.c.version_id,
            capture_versions.c.version_number,
            capture_versions.c.content_sha256,
        )
        .join(capture_versions, capture_versions.c.version_id == capture_receipts.c.version_id)
        .where(capture_receipts.c.receipt_id == receipt_id)
    ).one()
    mapping = row._mapping
    return CaptureReceipt(
        receipt_id=str(mapping["receipt_id"]),
        capture_id=str(mapping["capture_id"]),
        version_id=str(mapping["version_id"]),
        version_number=int(mapping["version_number"]),
        idempotency_key=str(mapping["idempotency_key"]),
        content_sha256=str(mapping["content_sha256"]),
        issued_at=mapping["issued_at"],
    )


def admit_capture(connection: Connection, request: CaptureAdmissionRequest) -> CaptureAdmission:
    """Admit one submission, or return the receipt its key is already bound to.

    Raises `CaptureConflictError` when the key is bound to different content, and
    `UnknownScopeError` when `request.capture_id` names no capture. Both roll the
    caller's transaction back, so a refused request stores nothing — which is
    `QC-AC-032`'s "fails closed" as a property of the transaction rather than of
    a cleanup path.
    """
    digest = request.content.digest
    submission_id = issue_identifier(IdKind.SUBMISSION)
    version_id = issue_identifier(IdKind.CAPTURE_VERSION)
    receipt_id = issue_identifier(IdKind.RECEIPT)

    admitted = connection.execute(
        pg_insert(capture_submissions)
        .values(
            submission_id=submission_id,
            idempotency_key=request.idempotency_key,
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            principal_id=request.principal_id,
            transport=CaptureTransport.LOCAL.value,
            capture_method=CaptureMethod.TYPED_TEXT.value,
            trust_state=TrustState.LOCAL_PRINCIPAL.value,
            payload_sha256=digest,
            client_created_at=request.client_created_at,
            server_received_at=request.server_received_at,
            admission_result=AdmissionResult.ACCEPTED.value,
            version_id=version_id,
            receipt_id=receipt_id,
        )
        .on_conflict_do_nothing(constraint="a_capture_key_admits_one_submission")
        .returning(capture_submissions.c.submission_id)
    ).one_or_none()

    if admitted is None:
        return _replay(connection, request.idempotency_key, digest)

    _chain(connection, request, version_id=version_id, digest=digest)
    connection.execute(
        capture_receipts.insert().values(
            receipt_id=receipt_id,
            version_id=version_id,
            idempotency_key=request.idempotency_key,
        )
    )
    # The outbox. Written here rather than by whatever eventually consumes it,
    # because durable-first means the work exists from the moment the capture
    # does: a crash between accepting a capture and processing it must lose the
    # processing, not the record that it is owed. Nothing claims this row until
    # WP-7.
    enqueue_job(connection, version_id, plane=CAPTURE_JOBS)
    return CaptureAdmission(receipt=_receipt(connection, receipt_id), created=True)


def _replay(connection: Connection, idempotency_key: str, digest: str) -> CaptureAdmission:
    """Answer a request whose idempotency key is already in use.

    The stored payload digest is what decides, and it is compared rather than
    the content: this module never needs a second copy of the text to know
    whether two requests carried the same one. Which field differs is
    deliberately not reported — that would describe the stored request to
    whoever guessed the key.
    """
    row = connection.execute(
        select(capture_submissions.c.payload_sha256, capture_submissions.c.receipt_id).where(
            capture_submissions.c.idempotency_key == idempotency_key
        )
    ).one_or_none()
    stored = conflicting_row(row, "knowledge.capture_submissions")
    if str(stored[0]) != digest:
        raise CaptureConflictError("the idempotency key is bound to different content")
    return CaptureAdmission(receipt=_receipt(connection, str(stored[1])), created=False)


def _chain(
    connection: Connection,
    request: CaptureAdmissionRequest,
    *,
    version_id: str,
    digest: str,
) -> str:
    """Insert the version, starting a chain or appending to one. Returns the capture.

    A create issues a new `cap_…` and writes version one, which supersedes
    nothing. A revise reads the capture's head and writes the next number
    superseding it — and writes no `UPDATE` anywhere, which is why `captures`
    carries no current-version pointer to keep in step.
    """
    if request.capture_id is None:
        capture_id = issue_identifier(IdKind.CAPTURE)
        connection.execute(
            captures.insert().values(
                capture_id=capture_id,
                owner_principal_id=request.principal_id,
            )
        )
        version_number, supersedes = 1, None
    else:
        capture_id = validate_identifier(request.capture_id, IdKind.CAPTURE)
        head = _head(connection, capture_id)
        if head is None:
            # No such capture, or one with no version, which cannot exist: a
            # capture is created with its first version in one transaction. The
            # answer names no identifier, so a caller cannot use the refusal to
            # learn whether a capture it may not see exists.
            raise UnknownScopeError("the request names no stored capture")
        version_number, supersedes = head.version_number + 1, head.version_id

    connection.execute(
        capture_versions.insert().values(
            version_id=version_id,
            capture_id=capture_id,
            version_number=version_number,
            supersedes_version_id=supersedes,
            content=request.content.text,
            content_sha256=digest,
            owner_principal_id=request.principal_id,
            classification=request.classification.value,
            processing_policy=request.processing_policy.value,
            idempotency_key=request.idempotency_key,
            correlation_id=request.correlation_id,
            audit_id=request.audit_id,
            client_created_at=request.client_created_at,
            server_received_at=request.server_received_at,
            occurred_at=request.occurred_at,
            accepted_at=request.accepted_at,
            # The fifth timestamp, and the only one this layer supplies. It is
            # the server's own clock inside the statement, so it is a different
            # reading from either of the two the request carried and cannot be
            # made equal to one by a caller passing the same value twice.
            recorded_at=func.now(),
        )
    )
    return capture_id


def capture_version(
    connection: Connection, capture_id: str, *, version_id: str | None = None
) -> CaptureVersion | None:
    """Return one stored version of `capture_id`, or `None`.

    `version_id` omitted returns the current version, which is the greatest
    version number the capture holds — read from the rows rather than from a
    pointer column that could disagree with them. Named, it returns exactly that
    version, including a superseded one, which is `QC-AC-010`'s "independently
    retrievable".

    The capture is part of the lookup rather than derived from the version, so a
    version identifier belonging to a different capture answers `None` — the same
    answer as one that names nothing.
    """
    validate_identifier(capture_id, IdKind.CAPTURE)
    statement = select(*_VERSION_COLUMNS).where(capture_versions.c.capture_id == capture_id)
    if version_id is None:
        statement = statement.order_by(capture_versions.c.version_number.desc()).limit(1)
    else:
        validate_identifier(version_id, IdKind.CAPTURE_VERSION)
        statement = statement.where(capture_versions.c.version_id == version_id)
    row = connection.execute(statement).one_or_none()
    return None if row is None else _to_version(row)


def capture_page(connection: Connection, *, limit: int) -> tuple[CaptureSummary, ...]:
    """One bounded page of captures, newest first.

    No content and no per-version detail beyond where the chain has got to. The
    counts and the latest version are read in one statement, so a capture cannot
    be reported with a version count from one snapshot and a head from another.
    """
    if limit < 1:
        raise ValueError("a page holds at least one capture")
    latest_number = func.max(capture_versions.c.version_number)
    rows = connection.execute(
        select(
            captures.c.capture_id,
            captures.c.owner_principal_id,
            captures.c.created_at,
            func.count().label("version_count"),
            latest_number.label("latest_version_number"),
        )
        .join(capture_versions, capture_versions.c.capture_id == captures.c.capture_id)
        .group_by(captures.c.capture_id, captures.c.owner_principal_id, captures.c.created_at)
        .order_by(captures.c.created_at.desc(), captures.c.capture_id)
        .limit(limit)
    ).all()
    return tuple(_summary(connection, row) for row in rows)


def _summary(connection: Connection, row: Row[tuple[object, ...]]) -> CaptureSummary:
    """One listing entry, with its head read under the same transaction."""
    mapping = row._mapping
    capture_id = str(mapping["capture_id"])
    head: Row[tuple[str, datetime]] = connection.execute(
        select(capture_versions.c.version_id, capture_versions.c.recorded_at).where(
            capture_versions.c.capture_id == capture_id,
            capture_versions.c.version_number == mapping["latest_version_number"],
        )
    ).one()
    return CaptureSummary(
        capture_id=capture_id,
        owner_principal_id=str(mapping["owner_principal_id"]),
        created_at=mapping["created_at"],
        version_count=int(mapping["version_count"]),
        latest_version_id=str(head[0]),
        latest_version_number=int(mapping["latest_version_number"]),
        latest_recorded_at=head[1],
    )
