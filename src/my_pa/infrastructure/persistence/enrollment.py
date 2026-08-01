"""Persisting an accepted enrollment, idempotently.

One function, because there is one operation: accept this request, or tell me
what its key is already bound to.

The idempotency rule of `docs/specs` section 8.6 needs two things that have to
agree. The unique constraint permits exactly one row per (principal, purpose,
source, policy version, key), which is what makes the question "is this key
already used?" answerable without a race — two concurrent callers cannot both
read "absent" and both insert, because the second insert is refused by the
database rather than by a check that already ran. The stored
`request_fingerprint` is what makes the answer *useful*: with it, a reused key
carrying the same normalized request is a retry and returns the existing
enrollment, and a reused key carrying a materially different one is a conflict.
Without the fingerprint the constraint could only say "taken"; without the
constraint the fingerprint comparison would be advisory.

The insert is attempted first and the select is the fallback, in that order.
Checking first and inserting second would reintroduce exactly the window the
constraint exists to close.
"""

from __future__ import annotations

from datetime import datetime
from typing import NamedTuple

from sqlalchemy import Connection, Row, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.enrollment import (
    Enrollment,
    EnrollmentConflictError,
    EnrollmentRequest,
    EnrollmentScope,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence import conflicting_row
from my_pa.infrastructure.persistence.tables import enrollments

__all__ = ["AcceptedEnrollment", "accept_enrollment"]

_COLUMNS = (
    enrollments.c.enrollment_id,
    enrollments.c.source_id,
    enrollments.c.principal_id,
    enrollments.c.purpose,
    enrollments.c.root_object_id,
    enrollments.c.object_ids,
    enrollments.c.depth,
    enrollments.c.media_types,
    enrollments.c.policy_version,
    enrollments.c.request_fingerprint,
    enrollments.c.max_items,
    enrollments.c.max_bytes,
    enrollments.c.accepted_at,
)


class AcceptedEnrollment(NamedTuple):
    """The accepted enrollment and whether this call is what created it.

    `created` false means the key was already bound to this exact request: the
    correct response is then the same one the first call got, not an error.
    A caller that does not care may ignore it; one that audits acceptance
    separately from retry needs to be able to tell them apart.
    """

    enrollment: Enrollment
    created: bool


def _to_enrollment(row: Row[tuple[object, ...]]) -> Enrollment:
    mapping = row._mapping
    accepted_at: datetime = mapping["accepted_at"]
    return Enrollment(
        enrollment_id=str(mapping["enrollment_id"]),
        source_id=str(mapping["source_id"]),
        principal_id=str(mapping["principal_id"]),
        purpose=Purpose(mapping["purpose"]),
        scope=EnrollmentScope(
            object_ids=tuple(mapping["object_ids"]),
            root_object_id=mapping["root_object_id"],
            depth=int(mapping["depth"]),
        ),
        media_types=tuple(mapping["media_types"]),
        policy_version=str(mapping["policy_version"]),
        request_fingerprint=str(mapping["request_fingerprint"]),
        max_items=int(mapping["max_items"]),
        max_bytes=int(mapping["max_bytes"]),
        accepted_at=accepted_at,
    )


def accept_enrollment(connection: Connection, request: EnrollmentRequest) -> AcceptedEnrollment:
    """Accept `request`, or return what its idempotency key is already bound to.

    Raises `EnrollmentConflictError` when the key is bound to a materially
    different normalized request — the `conflict` of section 8.6. Raises
    whatever the driver raises when `source_id` names no configured source: the
    foreign key is the check, and inventing a friendlier error here would mean
    reporting on a source the caller may not be entitled to know about.
    """
    fingerprint = request.fingerprint
    statement = (
        pg_insert(enrollments)
        .values(
            enrollment_id=issue_identifier(IdKind.ENROLLMENT),
            source_id=request.source_id,
            principal_id=request.principal_id,
            purpose=request.purpose.value,
            policy_version=request.policy_version,
            idempotency_key=request.idempotency_key,
            request_fingerprint=fingerprint,
            root_object_id=request.scope.root_object_id,
            object_ids=list(request.scope.object_ids),
            depth=request.scope.depth,
            media_types=list(request.media_types),
            max_items=request.max_items,
            max_bytes=request.max_bytes,
        )
        .on_conflict_do_nothing(constraint="enrollments_idempotency_key_is_scoped")
        .returning(*_COLUMNS)
    )
    inserted = connection.execute(statement).one_or_none()
    if inserted is not None:
        return AcceptedEnrollment(_to_enrollment(inserted), True)

    # The insert conflicted, so the key is in use and the row that holds it was
    # committed by another transaction. Reading it here depends on READ
    # COMMITTED taking a fresh snapshot per statement; the package docstring
    # records what a higher isolation level does instead, which was measured
    # rather than assumed. `conflicting_row` is what stops the remaining case —
    # the row deleted between the two statements — from surfacing as a
    # `NoResultFound` that reads like a missing enrollment.
    existing = connection.execute(
        select(*_COLUMNS).where(
            enrollments.c.principal_id == request.principal_id,
            enrollments.c.purpose == request.purpose.value,
            enrollments.c.source_id == request.source_id,
            enrollments.c.policy_version == request.policy_version,
            enrollments.c.idempotency_key == request.idempotency_key,
        )
    ).one_or_none()
    enrollment = _to_enrollment(conflicting_row(existing, "knowledge.enrollments"))
    if enrollment.request_fingerprint != fingerprint:
        raise EnrollmentConflictError(enrollment.enrollment_id)
    return AcceptedEnrollment(enrollment, False)
