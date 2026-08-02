"""Persisting an accepted enrollment and the object set it authorizes.

Two operations. Accept this request, or tell me what its key is already bound
to; and record which objects the enumeration found, once, at acceptance.

**Why the enumerated set is a second fact and not the first one reshaped.**
`enrollments.object_ids` is what the caller *asked for* — it is part of
`EnrollmentRequest.normalized()` and therefore of `request_fingerprint`, which
is what makes an idempotency-key retry distinguishable from a conflict. What the
enumeration *found* is a different fact, and for a root selector it is not even
the same shape. It also cannot be given a foreign key where it is: `object_ids`
is an `ARRAY(Text)` and PostgreSQL has no element-level reference, so an
identifier that named no row was storable and authorized nothing, silently.
`knowledge.enrollment_objects` is the second fact, with a foreign key on each
column.

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

from collections.abc import Iterable
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import Connection, Row, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from my_pa.contracts.ports import UnknownScopeError
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.enrollment import (
    Enrollment,
    EnrollmentConflictError,
    EnrollmentRequest,
    EnrollmentScope,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence import conflicting_row
from my_pa.infrastructure.persistence.tables import (
    enrollment_objects,
    enrollments,
    source_objects,
)

__all__ = [
    "AcceptedEnrollment",
    "accept_enrollment",
    "enrolled_object_count",
    "enrollments_for_principal",
    "record_scope",
]

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


def enrollments_for_principal(connection: Connection, principal_id: str) -> tuple[Enrollment, ...]:
    """Every grant `principal_id` holds, oldest first.

    This is what an authorization decision is evaluated against, so it is a
    stored fact read at decision time rather than something a caller supplies
    beside its request. The order is by acceptance and then identifier, so "the
    enrollment over this source" means the same row on two calls.

    Returns the empty tuple for a principal with no grants, which is the honest
    answer and the one that authorizes nothing: `domain.policy.decision` treats
    an empty authorized set as covering no requested scope at all.
    """
    validate_identifier(principal_id, IdKind.PRINCIPAL)
    rows = connection.execute(
        select(*_COLUMNS)
        .where(enrollments.c.principal_id == principal_id)
        .order_by(enrollments.c.accepted_at, enrollments.c.enrollment_id)
    ).all()
    return tuple(_to_enrollment(row) for row in rows)


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


def enrolled_object_count(connection: Connection, enrollment_id: str) -> int:
    """How many objects `enrollment_id` holds in its enumerated set.

    This is the eligible total — the denominator a coverage statement is honest
    about — read from stored rows rather than supplied by whatever assembled the
    disclosure. Zero is a real answer here and never a benign one: an accepted
    enrollment holds at least one object, because `record_scope` refuses to
    record an empty set, so a zero means the enrollment was never enumerated.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    return int(
        connection.execute(
            select(func.count())
            .select_from(enrollment_objects)
            .where(enrollment_objects.c.enrollment_id == enrollment_id)
        ).scalar_one()
    )


def record_scope(
    connection: Connection, enrollment_id: str, source_object_ids: Iterable[str]
) -> int:
    """Record the objects `enrollment_id` authorizes, and return how many it holds.

    Called once, inside the transaction that accepted the enrollment and only
    where that acceptance created it, so a retried request re-enumerates
    nothing.

    **Idempotent by constraint, not by convention.** The insert conflicts on
    `an_enrollment_holds_an_object_once` — the composite primary key — and does
    nothing, so running the same enumeration twice adds no row and the count is
    the same both times. Two concurrent callers cannot both read "absent" and
    both insert, which a check-then-insert here would permit.

    **An empty set is refused.** An enrollment nothing measured would have a
    zero denominator and a queued job, and would report coverage over a scope no
    row describes. Raising rolls the whole enroll transaction back, including
    `accept_enrollment`, so the unmeasurable enrollment does not exist rather
    than existing unmeasured. `ValueError` is what the other writers in this
    package raise to refuse an argument — `extraction.record_limitation` refuses
    a count below one the same way — and it is what `persistence.unit_of_work`
    already classifies at the port boundary; this module may not import
    `application`, so it cannot raise the public error itself.

    **Membership is checked before the insert, and the foreign key is not the
    check.** `enrollment_objects.source_object_id` references
    `source_objects.source_object_id`, which proves the object was observed by
    *something*; it does not prove it was observed under this enrollment's
    source. Without the pre-check, enumerating one source and naming an object
    of another would insert successfully and silently widen the grant. The
    answer is `UnknownScopeError` — `not_found` in section 10's terms — and it
    names no identifier, so a caller cannot use the refusal to learn whether an
    object it may not see exists.

    **This is also where a root that does not exist is refused.** There is no
    foreign key on `enrollments.root_object_id` and there deliberately will not
    be one: `enrollments` is created by revision `7e5a1fb93d62` from the shared
    `MetaData`, so declaring that reference would retroactively change the DDL an
    already-merged revision emits. The guarantee is held here instead. A root
    naming no observed object enumerates to nothing, and the empty set is refused
    above; a root that names an object of another source is refused by the
    pre-check. Either refusal rolls back the transaction that accepted the
    enrollment, so the enrollment does not exist rather than existing
    unenumerable.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    wanted = {validate_identifier(value, IdKind.SOURCE_OBJECT) for value in source_object_ids}
    if not wanted:
        raise ValueError("an enrollment authorizes at least one object")

    # One statement for both halves of the pre-check. An enrollment that does
    # not exist has no source, so the join yields nothing and the count is zero,
    # which is the same refusal an object of the wrong source produces — and the
    # same refusal section 10 requires "no such enrollment" to be
    # indistinguishable from.
    belonging = connection.execute(
        select(func.count())
        .select_from(source_objects)
        .join(enrollments, enrollments.c.source_id == source_objects.c.source_id)
        .where(
            enrollments.c.enrollment_id == enrollment_id,
            source_objects.c.source_object_id.in_(wanted),
        )
    ).scalar_one()
    if int(belonging) != len(wanted):
        raise UnknownScopeError("the scope names an object this enrollment's source never observed")

    rows = [
        {"enrollment_id": enrollment_id, "source_object_id": object_id}
        for object_id in sorted(wanted)
    ]
    connection.execute(
        pg_insert(enrollment_objects)
        .values(rows)
        .on_conflict_do_nothing(constraint="an_enrollment_holds_an_object_once")
    )
    return enrolled_object_count(connection, enrollment_id)
