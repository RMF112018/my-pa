"""The reads `knowledge.read`, `sources.status`, and the executor need; no writes.

Every function here takes a `Connection` and the caller owns the transaction, as
everywhere else in this package. They are reads only: nothing in this module can
create, change, or remove a row, which is what makes it safe for the read-side
capabilities to reach the same tables the extraction writer owns.

**A record is read inside one grant, not looked up and then checked.** The
predicate `read_extraction` applies is `extraction.extracted_text_in_scope`,
which is the same definition `coverage_for`'s `processed` count and
`persistence.search`'s match predicate are built from. So a record written under
one enrollment cannot be read through another, a record whose object the
enrollment does not authorize is invisible, a record whose media type the
enrollment's allowlist does not hold is invisible, and an object a quarantine or
an unsupported outcome outranks stays withheld even where a later version of it
was extracted successfully. None of that is re-stated here; it is one call, and
a divergence between what a search returns and what a read will serve is
therefore not expressible.

The consequence is worth stating plainly rather than leaving to be discovered: a
row that exists and is not in scope is indistinguishable from a row that does
not exist, because both produce `None`. That is the answer `docs/specs` section
10 requires — `not_found` must not be separable from a refusal — and it is why
this returns an option rather than raising something a caller could classify.

**`latest_limitations` reads the newest snapshot, not a stated one.**
`coverage_for` matches limitations to the snapshot it is given exactly, because
a limitation belongs to one enumeration pass; a caller assembling a disclosure
*now* wants the omissions the most recent pass reported, which no current
timestamp will ever equal. The two answers are both right and they are different
questions, so they are two reads. `persistence.search` asks the same question of
the same rows for the same reason, in its own module and inside its own error
translation; the duplication is two callers of one query rather than two
definitions of one rule, and merging them would mean this module's reads
inheriting the search module's redaction wrapper for no benefit.

**`outcome_for_object` applies the precedence the counts apply.** Quarantine
outranks unsupported, which outranks extracted, and for the reason `coverage_for`
gives: a later success must never hide a quarantine (`INV-PKL-007`,
`ABUSE-PKL-008`). It answers about one object, so it is a different shape from
the counts, but it must not be able to give a different answer.

**`pending_objects` is the executor's work list, and its predicate is the only
idempotency protecting a quarantine.** `extractions` has
`one_extraction_per_version_per_enrollment` and `record_outcome` inserts under
it, so re-extracting an unchanged object writes no second row. A quarantine has
no such constraint and deliberately will not get one: `quarantine_records` is
append-only because a second quarantine of the same object is a second event.
What stops a re-run duplicating one is that this function never offers an object
that already holds a row in either table for this enrollment. It is stated here
rather than implied, because it is the one idempotency in this package that is a
predicate instead of a constraint, and a test plants against exactly it.

**`corpus_coverage` is the only read here that is not scoped to one enrollment,
and it is scoped to one Principal at the statement instead.** Every statement it
builds over `enrollments` reaches the partition through
`principal_scope.partition_criterion` rather than through a comparison written at
the call site — the drift
`tests/architecture/test_principal_partition_is_reached_through_the_guard.py`
exists to refuse — and the counts that do not name `enrollments` directly are
restricted to identifiers a statement that did produced. Nothing here takes a
source, an enrollment, or a set of either from a caller; the caller states
*whose* corpus and the store decides what that contains.
`tests/database/test_corpus_coverage.py` builds two Principals over disjoint
sources and asserts that each answer counts its own rows and none of the other's,
and that guard's `test_every_corpus_coverage_statement_reaches_the_partition`
checks the statements one at a time rather than the module as a whole.

**It composes; it does not recompute.** Each member of the answer is
`coverage_for`'s own value for that enrollment — the identical read
`sources.status` and `knowledge.search` report — so there is one definition of
"processed" in this package and this is not a second one. What it adds is the
territory no per-enrollment read can see: objects inside the Principal's held
sources that no enrollment of theirs enumerates, and enumerated objects that have
reached no outcome. Both are counts with no identifier attached, on
`AggregateLimitation`'s precedent, and `domain.extraction.corpus` is where the
discipline is written down.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ColumnElement, Connection, Row, Select, func, literal, select

from my_pa.contracts.ports import KnowledgeRecord
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.provenance import Provenance, TrustLevel
from my_pa.domain.extraction.corpus import CorpusCoverage
from my_pa.domain.extraction.coverage import AggregateLimitation, LimitationReason
from my_pa.domain.extraction.text import ExtractionStatus
from my_pa.domain.source.provider import ENUMERABLE_KINDS
from my_pa.infrastructure.persistence.extraction import (
    authorized_object,
    coverage_for,
    extracted_text_in_scope,
)
from my_pa.infrastructure.persistence.principal_scope import (
    PrincipalContext,
    capture_context,
    partition_criterion,
)
from my_pa.infrastructure.persistence.tables import (
    coverage_limitations,
    enrollment_objects,
    enrollments,
    extractions,
    quarantine_records,
    source_objects,
)

__all__ = [
    "corpus_coverage",
    "latest_limitations",
    "outcome_for_object",
    "pending_objects",
    "read_extraction",
]

_RECORD_COLUMNS = (
    extractions.c.extraction_id,
    extractions.c.enrollment_id,
    extractions.c.media_type,
    extractions.c.text,
    extractions.c.is_truncated,
    source_objects.c.source_id,
    extractions.c.source_object_id,
    extractions.c.version_id,
    extractions.c.extractor,
    extractions.c.extractor_version,
    extractions.c.trust_level,
    extractions.c.observed_at,
    extractions.c.processed_at,
)


def latest_limitations(
    connection: Connection, enrollment_id: str
) -> tuple[AggregateLimitation, ...]:
    """Every aggregate limitation recorded at `enrollment_id`'s newest snapshot.

    Sorted, so the order of the tokens in a disclosure is a decision rather than
    whatever the planner returned. `LimitationReason` has one member today and
    the schema allows one row per reason per snapshot, so this returns at most
    one row; the ordering is kept because it decides the shape of a public
    envelope the day a second reason exists.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    newest = select(func.max(coverage_limitations.c.observed_at)).where(
        coverage_limitations.c.enrollment_id == enrollment_id
    )
    rows = connection.execute(
        select(coverage_limitations.c.reason, coverage_limitations.c.affected_count)
        .where(
            coverage_limitations.c.enrollment_id == enrollment_id,
            coverage_limitations.c.observed_at == newest.scalar_subquery(),
        )
        .order_by(coverage_limitations.c.reason)
    ).all()
    return tuple(
        AggregateLimitation(reason=LimitationReason(row[0]), affected_count=int(row[1]))
        for row in rows
    )


def outcome_for_object(
    connection: Connection, *, enrollment_id: str, source_object_id: str
) -> ExtractionStatus | None:
    """What happened to one object under one enrollment, or `None` for nothing yet.

    `None` is a real answer and not an absence to be smoothed over: an enrolled
    object that has reached no outcome is neither processed nor missing, and
    reporting it as either is the collapse section 12 forbids.

    Both reads carry the object dimension of the authorization boundary, so an
    outcome stored against this enrollment for an object it does not authorize
    is not reported as its state — the same restriction `coverage_for` applies
    to the counts.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    validate_identifier(source_object_id, IdKind.SOURCE_OBJECT)

    quarantined = connection.execute(
        select(literal(1))
        .where(
            quarantine_records.c.enrollment_id == enrollment_id,
            quarantine_records.c.source_object_id == source_object_id,
            authorized_object(quarantine_records.c.source_object_id, enrollment_id=enrollment_id),
        )
        .limit(1)
    ).scalar_one_or_none()
    if quarantined is not None:
        return ExtractionStatus.QUARANTINED

    statuses = set(
        connection.execute(
            select(extractions.c.status)
            .where(
                extractions.c.enrollment_id == enrollment_id,
                extractions.c.source_object_id == source_object_id,
                authorized_object(extractions.c.source_object_id, enrollment_id=enrollment_id),
            )
            .distinct()
        ).scalars()
    )
    if ExtractionStatus.UNSUPPORTED.value in statuses:
        return ExtractionStatus.UNSUPPORTED
    if ExtractionStatus.EXTRACTED.value in statuses:
        return ExtractionStatus.EXTRACTED
    return None


def awaits_an_outcome() -> tuple[ColumnElement[bool], ...]:
    """Whether a row of `enrollment_objects` has reached no outcome at all.

    **One definition, two callers, and the second is why it is a function.**
    `pending_objects` asks it of one enrollment and `corpus_coverage` asks it of
    every enrollment a Principal holds at once; writing the condition twice is
    how a work list and a coverage report come to disagree about what is
    outstanding, which is the divergence class this package exists to close.

    Both exclusions are needed and neither implies the other: an unsupported
    outcome and a successful extraction are both rows in `extractions`, and a
    quarantine is a row in neither.

    Correlated `NOT EXISTS` against the enclosing `enrollment_objects` row rather
    than `NOT IN` over a per-enrollment subquery, because a corpus-wide caller has
    no single enrollment to bind such a subquery to. The two are equivalent for
    one enrollment — every column compared is `NOT NULL`, so neither can go
    three-valued — and `correlate_except` states which side is the subquery's own
    rather than leaving it to inference.
    """
    return (
        ~select(literal(1))
        .where(
            extractions.c.enrollment_id == enrollment_objects.c.enrollment_id,
            extractions.c.source_object_id == enrollment_objects.c.source_object_id,
        )
        .correlate_except(extractions)
        .exists(),
        ~select(literal(1))
        .where(
            quarantine_records.c.enrollment_id == enrollment_objects.c.enrollment_id,
            quarantine_records.c.source_object_id == enrollment_objects.c.source_object_id,
        )
        .correlate_except(quarantine_records)
        .exists(),
    )


def pending_objects(connection: Connection, enrollment_id: str) -> tuple[str, ...]:
    """The objects `enrollment_id` holds that have reached no outcome yet.

    A row of `enrollment_objects` for this enrollment with no row in
    `extractions` and no row in `quarantine_records` for it, under the same
    enrollment. Both exclusions are needed and neither implies the other: an
    unsupported outcome and a successful extraction are both rows in
    `extractions`, and a quarantine is a row in neither. Dropping the quarantine
    half would make a re-run quarantine the same object twice, because that
    ledger is append-only by design and has no unique key to conflict against.

    Restricted to the enumerated set rather than to the enrollment identifier,
    which is what makes this a work list and not a diff: an object nothing
    enumerated is not work this enrollment authorizes, and offering it would hand
    the executor an object `authorized_object` will then refuse — the
    disagreement that `docs/specs` section 12 calls a broken store.

    Ordered by identifier, so two workers over the same enrollment plan the same
    sequence and a re-run after a crash resumes in a decidable order rather than
    in whatever order the planner returned.

    The empty tuple is a real answer and the common one: an enrollment whose work
    is finished has nothing pending. It is not "no such enrollment" — that is
    also empty, and the two are deliberately indistinguishable here for the
    reason this module's docstring gives about `read_extraction`.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    rows = connection.execute(
        select(enrollment_objects.c.source_object_id)
        .where(
            enrollment_objects.c.enrollment_id == enrollment_id,
            *awaits_an_outcome(),
        )
        .order_by(enrollment_objects.c.source_object_id)
    ).scalars()
    return tuple(str(value) for value in rows)


def _held_sources(context: PrincipalContext) -> Select[tuple[str]]:
    """The sources this Principal holds an enrollment over, as a subquery.

    The corpus is exactly this and nothing wider. `knowledge.sources` carries no
    `principal_id`: a Principal holds a source by enrolling it, so a count of
    *configured* sources it has not enrolled would be a fact about the operator's
    registry and, where more than one Principal exists, about another Principal's
    enrollments. `domain.extraction.corpus` records why that count is refused and
    what is published instead.
    """
    return select(enrollments.c.source_id).where(partition_criterion(enrollments, context))


def _enumerated_objects(context: PrincipalContext) -> Select[tuple[str]]:
    """Every object any enrollment of this Principal enumerates, as a subquery."""
    return (
        select(enrollment_objects.c.source_object_id)
        .select_from(
            enrollment_objects.join(
                enrollments, enrollments.c.enrollment_id == enrollment_objects.c.enrollment_id
            )
        )
        .where(partition_criterion(enrollments, context))
    )


def corpus_coverage(
    connection: Connection, principal_id: str, *, observed_at: datetime
) -> CorpusCoverage:
    """What one Principal holds, what was covered, and what was never in scope.

    **Principal-scoped at the query, not after it.** Every statement below either
    carries `enrollments.principal_id = :principal_id` itself or is restricted to
    identifiers a statement that did produced. Nothing takes a source or an
    enrollment from a caller, so there is no argument here that could widen the
    answer past the Principal it names.

    **The per-enrollment coverages are `coverage_for`'s, unchanged.** They are
    read one at a time, deliberately: a corpus-wide aggregate query over the
    outcome tables would be a *second* definition of processed, quarantined and
    unsupported, and the two would drift exactly as the count and the page in
    `persistence.search` once did. The cost is one round trip per enrollment,
    which is the price of the answer being a composition of the same facts every
    other surface reports.

    **The two unknown-territory counts are the part no per-enrollment read can
    see.** `objects_outside_every_enrollment` is the observed objects of the held
    sources that no enrollment of this Principal enumerates, restricted to
    `ENUMERABLE_KINDS` — a container is structure an enumeration descends into and
    never records, so counting one as uncovered would report a gap nothing could
    ever close. `objects_awaiting_an_outcome` is distinct objects, not
    (enrollment, object) pairs: two enrollments each still owing an outcome for
    one object are two units of work and one object, and the field says objects.
    That understates the outstanding work and cannot understate the *state*, since
    any positive count already forces `partially_processed`.

    Read across separate statements under READ COMMITTED, so a concurrent
    enrollment or extraction can land between them, exactly as
    `persistence.search`'s page and coverage reads can. The direction of that
    window is safe here: the counts are composed by a type that refuses to report
    a complete corpus while any of them is positive, so a race can make the answer
    more partial than the instant it names and never less.
    """
    validate_identifier(principal_id, IdKind.PRINCIPAL)
    context = capture_context(principal_id)

    held = tuple(
        str(value)
        for value in connection.execute(
            select(enrollments.c.enrollment_id)
            .where(partition_criterion(enrollments, context))
            .order_by(enrollments.c.enrollment_id)
        ).scalars()
    )
    if not held:
        # No enrollment is not "an empty corpus". `CorpusCoverage` reports
        # `not_enrolled` for it and refuses to carry a measurement beside it,
        # because every count below is a count inside the held sources and there
        # are none.
        return CorpusCoverage(observed_at=observed_at, principal_id=principal_id)

    members = tuple(
        coverage_for(connection, enrollment_id, observed_at=observed_at) for enrollment_id in held
    )

    sources_held = connection.execute(
        select(func.count(func.distinct(enrollments.c.source_id))).where(
            partition_criterion(enrollments, context)
        )
    ).scalar_one()

    in_scope_kinds = source_objects.c.kind.in_(sorted(kind.value for kind in ENUMERABLE_KINDS))
    observed = connection.execute(
        select(func.count(func.distinct(source_objects.c.source_object_id))).where(
            source_objects.c.source_id.in_(_held_sources(context)),
            in_scope_kinds,
        )
    ).scalar_one()
    outside = connection.execute(
        select(func.count(func.distinct(source_objects.c.source_object_id))).where(
            source_objects.c.source_id.in_(_held_sources(context)),
            in_scope_kinds,
            source_objects.c.source_object_id.not_in(_enumerated_objects(context)),
        )
    ).scalar_one()
    awaiting = connection.execute(
        select(func.count(func.distinct(enrollment_objects.c.source_object_id)))
        .select_from(
            enrollment_objects.join(
                enrollments, enrollments.c.enrollment_id == enrollment_objects.c.enrollment_id
            )
        )
        .where(partition_criterion(enrollments, context), *awaits_an_outcome())
    ).scalar_one()

    return CorpusCoverage(
        observed_at=observed_at,
        principal_id=principal_id,
        enrollments=members,
        held_sources=int(sources_held),
        objects_in_held_sources=int(observed),
        objects_outside_every_enrollment=int(outside),
        objects_awaiting_an_outcome=int(awaiting),
    )


def _to_record(row: Row[tuple[object, ...]]) -> KnowledgeRecord:
    mapping = row._mapping
    return KnowledgeRecord(
        knowledge_id=str(mapping["extraction_id"]),
        enrollment_id=str(mapping["enrollment_id"]),
        media_type=None if mapping["media_type"] is None else str(mapping["media_type"]),
        text=str(mapping["text"]),
        is_truncated=bool(mapping["is_truncated"]),
        provenance=Provenance(
            source_id=str(mapping["source_id"]),
            source_object_id=str(mapping["source_object_id"]),
            version_id=str(mapping["version_id"]),
            extractor=str(mapping["extractor"]),
            extractor_version=str(mapping["extractor_version"]),
            observed_at=mapping["observed_at"],
            processed_at=mapping["processed_at"],
            trust_level=TrustLevel(mapping["trust_level"]),
        ),
    )


def read_extraction(
    connection: Connection, extraction_id: str, *, enrollment_id: str
) -> KnowledgeRecord | None:
    """Return one stored record inside `enrollment_id`'s grant, or `None`.

    The source is taken from the matched object rather than from the enrollment,
    for the reason `persistence.search.match_statement` gives: those are two
    different facts and only one of them is a property of the row being
    returned.
    """
    validate_identifier(extraction_id, IdKind.KNOWLEDGE)
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    row = connection.execute(
        select(*_RECORD_COLUMNS)
        .select_from(
            extractions.join(
                source_objects,
                source_objects.c.source_object_id == extractions.c.source_object_id,
            )
        )
        .where(
            extractions.c.extraction_id == extraction_id,
            *extracted_text_in_scope(enrollment_id),
        )
    ).one_or_none()
    return None if row is None else _to_record(row)
