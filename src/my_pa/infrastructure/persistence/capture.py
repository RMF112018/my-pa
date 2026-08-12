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

**Every operation takes a `PrincipalContext` and is bound to it** (WP-03,
`PKL-MYPA-D-WP03-001`). `D-72` recorded owner columns and enforced nothing on
them; the ratified campaign is the operator decision that supersedes it.
Admission verifies the request's `principal_id` against the context and
refuses a mismatch as `CallerSuppliedPrincipalError` — a write path must never
accept identity from payload (MU-AC-02), including from its own composition
bugs. Reads pass through `principal_scoped`, so a capture another Principal
owns answers exactly what a capture that does not exist answers: `None` from a
read, `UnknownScopeError` from a revise — the refusal names no identifier, so
it cannot be used to learn whether the capture exists. The idempotency key's
collision domain narrows to the Principal's own submissions
(`a_capture_key_admits_one_submission_per_principal`, revision
`e7f3a9c2d514`); replay lookup carries the same two-column predicate, so one
Principal's replay can never return another's receipt.
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
from my_pa.domain.capture.context import ContextLinkAuthority, ContextLinkRole, ContextLinkTarget
from my_pa.domain.capture.errors import CaptureConflictError
from my_pa.domain.capture.submission import (
    AdmissionResult,
    CaptureKind,
    CaptureMethod,
    CaptureReceipt,
    trust_state_for,
)
from my_pa.domain.capture.version import CaptureContent, CaptureVersion, ProcessingPolicy
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.conversation.event import ConversationChannel, ConversationState
from my_pa.domain.identity.user_account import CallerSuppliedPrincipalError
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence import conflicting_row
from my_pa.infrastructure.persistence.jobs import CAPTURE_JOBS, enqueue_job
from my_pa.infrastructure.persistence.principal_scope import (
    PrincipalContext,
    principal_scoped,
    require_principal_context,
)
from my_pa.infrastructure.persistence.review import mark_changed_assertions_for_revalidation
from my_pa.infrastructure.persistence.tables import (
    capture_context_links,
    capture_conversations,
    capture_receipts,
    capture_submissions,
    capture_versions,
    captures,
    source_object_versions,
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


def _head(connection: Connection, capture_id: str, *, context: PrincipalContext) -> _Head | None:
    """The capture's current version, read inside the admitting transaction.

    A concurrent revise that read the same head cannot also store it: the two
    would insert the same `(capture_id, version_number)` and the same
    `supersedes_version_id`, and both constraints are unique. The loser is
    refused by the server rather than by a check that already ran, which is the
    same discipline `persistence.enrollment` states for idempotency keys.

    Scoped to the context's Principal, and that scoping is the revise-path
    ownership check: a capture another Principal owns has no head *for this
    caller*, so the revise refuses with the same `UnknownScopeError` a
    nonexistent capture earns — one answer for both, which is what keeps the
    refusal from being an existence oracle.
    """
    row: Row[tuple[str, int]] | None = connection.execute(
        principal_scoped(
            select(capture_versions.c.version_id, capture_versions.c.version_number).where(
                capture_versions.c.capture_id == capture_id
            ),
            capture_versions,
            context,
        )
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


def admit_capture(
    connection: Connection, request: CaptureAdmissionRequest, *, context: PrincipalContext
) -> CaptureAdmission:
    """Admit one submission, or return the receipt its key is already bound to.

    Raises `CaptureConflictError` when the key is bound to different content, and
    `UnknownScopeError` when `request.capture_id` names no capture *this
    Principal owns* — the two are one answer on purpose. Both roll the caller's
    transaction back, so a refused request stores nothing — which is
    `QC-AC-032`'s "fails closed" as a property of the transaction rather than of
    a cleanup path.

    The request still carries a `principal_id` because the port shape predates
    the context, and it is **verified rather than trusted**: a request whose
    payload names a Principal other than the authenticated one is refused as
    `CallerSuppliedPrincipalError` before anything is written (MU-AC-02).
    """
    resolved = require_principal_context(context)
    if request.principal_id != resolved.capture_principal_id:
        raise CallerSuppliedPrincipalError("principal_id")
    content_digest = request.content.digest
    payload_digest = request.payload_digest
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
            # Provenance, taken from the request rather than asserted here. The
            # transport is established by the composition root; the trust state
            # is *derived* from it by `trust_state_for` rather than passed
            # beside it, so no writer can store `remote_client` alongside
            # `local_principal`. Everything else about this INSERT — and every
            # other statement in this function — is identical for a remote and a
            # local submission, which is the whole of "one durable transaction".
            transport=request.transport.value,
            capture_method=CaptureMethod.TYPED_TEXT.value,
            trust_state=trust_state_for(request.transport).value,
            payload_sha256=payload_digest,
            client_created_at=request.client_created_at,
            server_received_at=request.server_received_at,
            admission_result=AdmissionResult.ACCEPTED.value,
            version_id=version_id,
            receipt_id=receipt_id,
        )
        .on_conflict_do_nothing(constraint="a_capture_key_admits_one_submission_per_principal")
        .returning(capture_submissions.c.submission_id)
    ).one_or_none()

    if admitted is None:
        return _replay(connection, request.idempotency_key, payload_digest, context=resolved)

    capture_id, prior = _chain(
        connection, request, version_id=version_id, digest=content_digest, context=resolved
    )
    if request.capture_id is None and request.capture_kind is CaptureKind.CONVERSATION_LOG:
        connection.execute(
            capture_conversations.insert().values(
                conversation_id=issue_identifier(IdKind.CONVERSATION),
                capture_id=capture_id,
                version_id=version_id,
                event_state=ConversationState.SKELETAL.value,
                channel=ConversationChannel.UNKNOWN.value,
                occurred_at_start=request.occurred_at,
                recorded_at=request.accepted_at,
            )
        )
    if request.capture_id is None and request.context_source_object_id is not None:
        _record_launch_context(connection, request, capture_id)
    if prior is not None:
        mark_changed_assertions_for_revalidation(
            connection,
            prior_version_id=prior.version_id,
            successor_content=request.content.text,
            at=request.accepted_at,
        )
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


def _replay(
    connection: Connection, idempotency_key: str, digest: str, *, context: PrincipalContext
) -> CaptureAdmission:
    """Answer a request whose idempotency key is already in use.

    The stored payload digest is what decides, and it is compared rather than
    the content: this module never needs a second copy of the text to know
    whether two requests carried the same one. Which field differs is
    deliberately not reported — that would describe the stored request to
    whoever guessed the key.

    The lookup carries the same two columns the unique constraint does. The
    constraint alone makes the scoped lookup return exactly the row whose
    conflict sent us here; the explicit predicate makes the scoping true in
    this statement rather than inferred from another object's definition.
    """
    row = connection.execute(
        principal_scoped(
            select(capture_submissions.c.payload_sha256, capture_submissions.c.receipt_id).where(
                capture_submissions.c.idempotency_key == idempotency_key
            ),
            capture_submissions,
            context,
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
    context: PrincipalContext,
) -> tuple[str, _Head | None]:
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
        version_number, supersedes, prior = 1, None, None
    else:
        capture_id = validate_identifier(request.capture_id, IdKind.CAPTURE)
        head = _head(connection, capture_id, context=context)
        if head is None:
            # No such capture, one with no version (which cannot exist: a
            # capture is created with its first version in one transaction), or
            # one another Principal owns — the scoped head makes those three
            # one case. The answer names no identifier, so a caller cannot use
            # the refusal to learn whether a capture it may not see exists.
            raise UnknownScopeError("the request names no stored capture")
        version_number, supersedes, prior = head.version_number + 1, head.version_id, head

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
    return capture_id, prior


def _record_launch_context(
    connection: Connection, request: CaptureAdmissionRequest, capture_id: str
) -> None:
    """Validate an exact current observed version, then record its launch link."""
    object_id = request.context_source_object_id
    version_id = request.context_source_version_id
    if object_id is None or version_id is None:  # pragma: no cover - request invariant
        raise ValueError("a launch context names both object and version")
    latest = connection.execute(
        select(source_object_versions.c.version_id)
        .where(source_object_versions.c.source_object_id == object_id)
        .order_by(
            source_object_versions.c.observed_at.desc(),
            source_object_versions.c.version_id.desc(),
        )
        .limit(1)
    ).scalar_one_or_none()
    if latest is None or str(latest) != version_id:
        raise UnknownScopeError("the launch context does not name the current observed version")
    connection.execute(
        capture_context_links.insert().values(
            capture_context_link_id=issue_identifier(IdKind.CONTEXT_LINK),
            capture_id=capture_id,
            target_type=ContextLinkTarget.SOURCE_OBJECT.value,
            target_id=object_id,
            link_role=ContextLinkRole.LAUNCH_CONTEXT.value,
            authority_state=ContextLinkAuthority.DETERMINISTIC.value,
            accepted_at=request.accepted_at,
        )
    )


def capture_version(
    connection: Connection,
    capture_id: str,
    *,
    version_id: str | None = None,
    context: PrincipalContext,
) -> CaptureVersion | None:
    """Return one stored version of `capture_id` the context's Principal owns, or `None`.

    `version_id` omitted returns the current version, which is the greatest
    version number the capture holds — read from the rows rather than from a
    pointer column that could disagree with them. Named, it returns exactly that
    version, including a superseded one, which is `QC-AC-010`'s "independently
    retrievable".

    The capture is part of the lookup rather than derived from the version, so a
    version identifier belonging to a different capture answers `None` — the same
    answer as one that names nothing, and the same answer as one another
    Principal owns (WP-03): three absences one response, so the read cannot be
    used to map another Principal's identifiers.
    """
    validate_identifier(capture_id, IdKind.CAPTURE)
    statement = principal_scoped(
        select(*_VERSION_COLUMNS).where(capture_versions.c.capture_id == capture_id),
        capture_versions,
        context,
    )
    if version_id is None:
        statement = statement.order_by(capture_versions.c.version_number.desc()).limit(1)
    else:
        validate_identifier(version_id, IdKind.CAPTURE_VERSION)
        statement = statement.where(capture_versions.c.version_id == version_id)
    row = connection.execute(statement).one_or_none()
    return None if row is None else _to_version(row)


def capture_page(
    connection: Connection, *, limit: int, context: PrincipalContext
) -> tuple[CaptureSummary, ...]:
    """One bounded page of the context Principal's captures, newest first.

    No content and no per-version detail beyond where the chain has got to. The
    counts and the latest version are read in one statement, so a capture cannot
    be reported with a version count from one snapshot and a head from another.
    The page is scoped before it is limited, so another Principal's captures do
    not occupy slots in this one's page any more than they appear in it.
    """
    if limit < 1:
        raise ValueError("a page holds at least one capture")
    latest_number = func.max(capture_versions.c.version_number)
    rows = connection.execute(
        principal_scoped(
            select(
                captures.c.capture_id,
                captures.c.owner_principal_id,
                captures.c.created_at,
                func.count().label("version_count"),
                latest_number.label("latest_version_number"),
            ).join(capture_versions, capture_versions.c.capture_id == captures.c.capture_id),
            captures,
            context,
        )
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
