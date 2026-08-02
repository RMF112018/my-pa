"""Persisting extraction outcomes, quarantines, and aggregate limitations.

Every function takes a `Connection` and the caller owns the transaction, as
everywhere else in this package: these are the statements, not the unit of work,
so an enrollment's whole pass commits together rather than once per object.

**No outcome can be dropped on the way in.** `record_outcome` accepts any
`ExtractionOutcome` and routes it — extracted and unsupported become a row in
`extractions`, quarantined becomes a row in `quarantine_records`. A caller
therefore cannot persist a batch of outcomes and silently lose the quarantines by
filtering for the ones that have text, which is the shape the section 12 rule
against silent skipping is guarding against.

**The payload never reaches the quarantine path.** `quarantine_object` takes
identifiers, a reason, and nothing else; it has no parameter that content could
be passed in, and the table it writes has no column content could be stored in.
The two together are why "quarantine stores IDs and safe reason codes, not
payloads" is a property of the code rather than a promise about how it is called.

**An enrollment's authorized object set is enforced, on both sides.** Filtering
by `enrollment_id` alone is not an authorization boundary: nothing in the schema
ties an outcome's `source_object_id` to the objects its enrollment named, so a
row written for any object at all would be counted and returned as if it were in
scope. `authorized_object` is the one definition of what an enrollment
authorizes — an object of the enrollment's own source, and, where the enrollment
named its objects, one of those — and it is applied by every count in
`coverage_for` and by the search predicate that reads the same rows. The write
path refuses the same objects through `UnauthorizedObjectError`, so the
inconsistent state cannot be created rather than merely not being reported.

The two halves are not redundant. The read side has to hold against rows already
stored, written by hand, or written before the write side existed; the write side
is what stops new ones. Neither would be enough alone.

**Coverage is read for a stated enrollment and snapshot.** `coverage_for` counts
what this schema stores and requires the caller to state what it does not: the
eligible total, and any queued or unavailable counts. That asymmetry is
deliberate. Only the layer that enumerated the scope knows how many objects were
eligible, and deriving the denominator from the rows that happen to exist would
report complete coverage of a scope nobody measured — exactly the global
inference section 12 forbids.

A caller that never enumerated the scope says so, with `eligible=None`, and the
total is then derived from what was accounted for. That is the same arithmetic
the paragraph above rejects, and it is admissible only because it is *stated*:
`None` is a caller declaring the denominator unmeasured, where an integer is a
caller asserting one. What the two must not share is a coverage *state*, and
`None` is the fact a caller needs to hold the state below any that would claim
the whole scope reached an outcome. The alternative — making a caller invent a
plausible integer and then repair the counts afterwards — is what produced two
defects here already: an invented ceiling can disagree with the stored rows and
crash the read, and a repaired total leaves no record that it was repaired.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Connection, Text, any_, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc, utc_now
from my_pa.domain.extraction.coverage import (
    AggregateLimitation,
    CoverageCounts,
    LimitationReason,
    SnapshotState,
)
from my_pa.domain.extraction.quarantine import (
    QuarantineReason,
    QuarantineRecord,
    QuarantineReviewState,
)
from my_pa.domain.extraction.text import ExtractionOutcome, ExtractionStatus
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence import conflicting_row
from my_pa.infrastructure.persistence.tables import (
    coverage_limitations,
    enrollments,
    extractions,
    quarantine_records,
    source_objects,
)

__all__ = [
    "UnauthorizedObjectError",
    "authorized_object",
    "coverage_for",
    "quarantine_object",
    "record_limitation",
    "record_outcome",
]


class UnauthorizedObjectError(Exception):
    """An outcome was offered for an object its enrollment does not authorize.

    Added because nothing else in this module's vocabulary fits. A `ValueError`
    would say the arguments are malformed, and they are not — both identifiers
    passed `validate_identifier` before this was reached. `IsolationLevelError`
    is about a row that vanished. What happened is that the write was refused on
    authorization grounds, and that has to be distinguishable by type, because a
    caller may reasonably quarantine-and-continue on a malformed outcome and must
    not do the same with one it was never entitled to record.

    Carries the two identifiers, both of which the caller supplied in the call
    being refused, so nothing here discloses anything the caller did not already
    hold. There is no reason code and no content: this is not a quarantine.
    """


def authorized_object(
    source_object_id: ColumnElement[Any], *, enrollment_id: str
) -> ColumnElement[bool]:
    """Whether `enrollment_id` authorizes the object `source_object_id` names.

    The one definition of an enrollment's authorized object set, written once and
    used by every read and every write that touches an outcome. Two conditions,
    and each is a fact the schema already stores:

    * The object belongs to the enrollment's own source. True of both selectors.
      A root selector names an object of that source and depth walks within it,
      so no object of another source can be under it; an enrollment naming
      objects is accepted without anything checking they are that source's, which
      is why this is enforced here rather than assumed.
    * Where the enrollment named its objects, the object is one of them.
      `enrollments.object_ids` *is* the authorization for that selector, and
      `enrollment_names_exactly_one_selector` guarantees it is non-empty exactly
      when `root_object_id` is null.

    A root-selector enrollment stores no object set, so there is nothing to
    restrict against and this deliberately does not invent one — the objects
    under a root are known only to the enumeration that walked it, and nothing
    persists them. That is the same gap that leaves such an enrollment's
    denominator unmeasured, and `persistence.search` discloses it rather than
    covering it up. The source condition still applies to it.

    `correlate_except` rather than SQLAlchemy's automatic correlation: the two
    tables named here must stay in the subquery's own `FROM` even when the
    enclosing statement happens to select from one of them, which
    `match_statement` does.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    return (
        select(literal(1))
        .where(
            enrollments.c.enrollment_id == enrollment_id,
            source_objects.c.source_object_id == source_object_id,
            source_objects.c.source_id == enrollments.c.source_id,
            or_(
                enrollments.c.root_object_id.is_not(None),
                source_object_id == any_(enrollments.c.object_ids),
            ),
        )
        .correlate_except(enrollments, source_objects)
        .exists()
    )


def _refuse_an_unauthorized_object(
    connection: Connection, *, enrollment_id: str, source_object_id: str
) -> None:
    """Raise unless `enrollment_id` authorizes `source_object_id`.

    One round trip before the write, which is the price of the state being
    impossible rather than merely unreported. The alternative — a foreign key or
    a check constraint — cannot be written: the authorized set for the named
    selector is an array column on another table, and PostgreSQL has no
    constraint that reaches it.
    """
    authorized = connection.execute(
        select(authorized_object(literal(source_object_id, Text), enrollment_id=enrollment_id))
    ).scalar_one()
    if not authorized:
        raise UnauthorizedObjectError(
            f"enrollment {enrollment_id} does not authorize object {source_object_id}"
        )


def record_outcome(
    connection: Connection,
    *,
    enrollment_id: str,
    outcome: ExtractionOutcome,
) -> str:
    """Persist one extraction outcome and return the identifier of its row.

    Idempotent per (enrollment, observed version): re-extracting an unchanged
    object returns the identifier issued the first time rather than accumulating
    rows, because a retry is not new evidence. A changed object has a new
    `ver_…` and therefore a new row, which is what keeps stored text
    attributable to the bytes it came from.

    A quarantined outcome is written to `quarantine_records` instead, and its
    `kn_…` is returned. It is not idempotent there — section 12 makes
    reprocessing an explicit new operation, so a second quarantine is a second
    event.

    Raises `UnauthorizedObjectError` for an object the enrollment does not
    authorize, before anything is written. The check is `authorized_object`'s,
    so an enrollment that named its objects admits only those; one that named a
    root has no stored object set and is restricted by its source alone.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    provenance = outcome.provenance

    if outcome.status is ExtractionStatus.QUARANTINED:
        reason = outcome.quarantine_reason
        if reason is None:
            # `ExtractionOutcome` refuses to exist in this state. Checked rather
            # than asserted because a quarantine written without its reason
            # would be a record that cannot be reviewed.
            raise ValueError("a quarantined outcome carries a reason")
        return quarantine_object(
            connection,
            enrollment_id=enrollment_id,
            source_object_id=provenance.source_object_id,
            version_id=provenance.version_id,
            reason=reason,
        ).quarantine_id

    # Checked here rather than at the top of the function so the quarantine path
    # is checked exactly once, by `quarantine_object` itself: it is reachable
    # both through this routing and directly.
    _refuse_an_unauthorized_object(
        connection,
        enrollment_id=enrollment_id,
        source_object_id=provenance.source_object_id,
    )

    statement = (
        pg_insert(extractions)
        .values(
            extraction_id=issue_identifier(IdKind.KNOWLEDGE),
            enrollment_id=enrollment_id,
            source_object_id=provenance.source_object_id,
            version_id=provenance.version_id,
            status=outcome.status.value,
            media_type=outcome.media_type,
            extractor=provenance.extractor,
            extractor_version=provenance.extractor_version,
            trust_level=provenance.trust_level.value,
            text=outcome.text,
            is_truncated=outcome.is_truncated,
            observed_at=provenance.observed_at,
            processed_at=provenance.processed_at,
        )
        .on_conflict_do_nothing(constraint="one_extraction_per_version_per_enrollment")
        .returning(extractions.c.extraction_id)
    )
    inserted = connection.execute(statement).scalar_one_or_none()
    if inserted is not None:
        return str(inserted)

    # The insert conflicted, so the row exists and was committed by someone
    # else. Reading it here depends on READ COMMITTED taking a fresh snapshot
    # per statement; the package docstring records what a higher isolation level
    # does instead. `conflicting_row` keeps the remaining case — the row deleted
    # between the two statements — from looking like an absent extraction.
    existing = connection.execute(
        select(extractions.c.extraction_id).where(
            extractions.c.enrollment_id == enrollment_id,
            extractions.c.version_id == provenance.version_id,
        )
    ).scalar_one_or_none()
    return str(conflicting_row(existing, "knowledge.extractions"))


def quarantine_object(
    connection: Connection,
    *,
    enrollment_id: str,
    source_object_id: str,
    version_id: str | None,
    reason: QuarantineReason,
) -> QuarantineRecord:
    """Record that processing of one object stopped, and why.

    Takes no content parameter, by design. The only things it can be given are
    opaque identifiers and a closed reason code, so there is nothing a caller
    could hand it that would end up stored, logged, or echoed.

    `version_id` may be `None` when the trigger fired before any version was
    proven — a containment failure at listing time, for instance. Recording a
    version that was never observed would attribute the quarantine to bytes
    nobody saw.

    Raises `UnauthorizedObjectError` for an object outside what the enrollment
    authorizes, and identifier syntax is no longer the whole of what is checked.
    A quarantine for an object the enrollment never named used to be storable,
    and the row it left was counted as coverage of that enrollment's scope. For
    an enrollment that named a root there is no stored object set to check
    against, so only its source is checked; `authorized_object` records why.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    validate_identifier(source_object_id, IdKind.SOURCE_OBJECT)
    if version_id is not None:
        validate_identifier(version_id, IdKind.VERSION)
    _refuse_an_unauthorized_object(
        connection, enrollment_id=enrollment_id, source_object_id=source_object_id
    )

    quarantined_at = utc_now()
    quarantine_id = issue_identifier(IdKind.KNOWLEDGE)
    connection.execute(
        quarantine_records.insert().values(
            quarantine_id=quarantine_id,
            enrollment_id=enrollment_id,
            source_object_id=source_object_id,
            version_id=version_id,
            reason=reason.value,
            review_state=QuarantineReviewState.PENDING_REVIEW.value,
            quarantined_at=quarantined_at,
        )
    )
    return QuarantineRecord(
        quarantine_id=quarantine_id,
        enrollment_id=enrollment_id,
        source_object_id=source_object_id,
        version_id=version_id,
        reason=reason,
        review_state=QuarantineReviewState.PENDING_REVIEW,
        quarantined_at=quarantined_at,
    )


def record_limitation(
    connection: Connection,
    *,
    enrollment_id: str,
    observed_at: datetime,
    reason: LimitationReason,
    affected_count: int,
) -> AggregateLimitation:
    """Add `affected_count` objects to one enrollment's limitation for a snapshot.

    Accumulates rather than replaces, and returns the running total. A listing
    that is paginated reports the objects it could not account for page by page,
    and the enrollment's limitation for that pass is the sum of them; a writer
    that overwrote would report only the last page's omissions.

    The count is all that is stored. There is no parameter for which objects were
    affected, because `docs/specs` section 9.2 permits the aggregate in the same
    sentence that forbids the per-object side channel.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    if affected_count < 1:
        raise ValueError("a limitation affects at least one object")
    snapshot = ensure_utc(observed_at)

    statement = (
        pg_insert(coverage_limitations)
        .values(
            limitation_id=issue_identifier(IdKind.KNOWLEDGE),
            enrollment_id=enrollment_id,
            observed_at=snapshot,
            reason=reason.value,
            affected_count=affected_count,
        )
        .on_conflict_do_update(
            constraint="one_limitation_per_reason_per_snapshot",
            set_={
                "affected_count": coverage_limitations.c.affected_count + affected_count,
            },
        )
        .returning(coverage_limitations.c.affected_count)
    )
    total = connection.execute(statement).scalar_one()
    return AggregateLimitation(reason=reason, affected_count=int(total))


def coverage_for(
    connection: Connection,
    enrollment_id: str,
    *,
    observed_at: datetime,
    eligible: int | None,
    queued: int = 0,
    unavailable: int = 0,
    snapshot: SnapshotState = SnapshotState.CURRENT,
) -> CoverageCounts:
    """Report coverage of `enrollment_id` for the snapshot `observed_at` names.

    Outcomes are counted for the whole enrollment and for nothing beyond it.
    "For the enrollment" is `authorized_object` and not `enrollment_id` alone:
    an outcome stored against this enrollment for an object it does not
    authorize is not coverage of its scope, and counting it converted a partial
    result into a complete one — with a named-objects enrollment the stray
    outcomes fitted inside the denominator and the read reported
    `processed == eligible` while authorized objects had reached no outcome at
    all. Objects that are authorized and have no outcome stay uncounted, which
    is what leaves the result partial, and that is the direction this must fail
    in.

    Counted for the whole enrollment rather than for one pass, because that is
    the scope the grant defines and an outcome does not stop being true when the
    next pass starts. Limitations are matched to the snapshot exactly: a
    limitation is a property of one enumeration pass rather than a running total,
    and summing two passes over the same tree would report each omission twice.

    Deliberately not filtered by time. An extraction records when the version it
    read was observed and a quarantine records when processing stopped, which are
    facts about different clocks; comparing either against a snapshot timestamp
    would look like an as-of query and answer a different question depending on
    which table it hit. Where the stored outcomes predate the source's current
    state, that is what `SnapshotState.STALE` is for, and the caller states it
    because only the caller can compare the source against the snapshot.

    Every outcome is counted by distinct object, and the three sets are
    disjoint. Both tables record events rather than states — the quarantine
    ledger is append-only, and `extractions` holds one row per observed version —
    so an object quarantined twice is two rows and one uncovered object, and an
    object with a quarantine on one version and an extraction on another is two
    rows and one object with one outcome. Counting rows would report more
    outcomes than there are objects, and `eligible` is a count of objects, so
    every count beside it has to be one too.

    The precedence is quarantine, then unsupported, then extracted, and it runs
    in that direction because it is the one that cannot overclaim. An object
    with any quarantine row is quarantined and is *not* processed: a later
    success must never hide a quarantine behind it, which is what `INV-PKL-007`
    and threat-model `ABUSE-PKL-008` forbid. For the same reason an object with
    an unsupported row is unsupported even where another version of it was
    extracted. The cost is disclosed rather than hidden: an object quarantined at
    one version and successfully extracted at a later one keeps reporting as
    quarantined, because nothing in these counts orders versions or reads the
    quarantine's review state. That understates coverage, which is the direction
    this can afford; the reverse would be a false claim that the object is
    covered.

    `eligible` is the enumerated total, or `None` from a caller that has no
    enumeration to quote. `None` is not a default and not a convenience: it is
    the caller stating that the denominator was never measured, and the total is
    then the objects this schema can account for — the outcomes counted here plus
    whatever queued and unavailable work the caller declared. A caller passing
    `None` gets a total it must not present as a measured scope; the whole-scope
    coverage states are the claim it has to withhold, because a denominator taken
    from the numerator divides out to all of it whichever outcome dominates.

    Raises `ValueError` — through `CoverageCounts` — when the counts do not fit
    inside an `eligible` the caller supplied. That is the right failure: a scope
    smaller than what was processed within it means the caller's denominator is
    wrong, and reporting coverage from it would be a number that cannot be true.
    It cannot arise from `None`, which is derived to fit exactly.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    moment = ensure_utc(observed_at)

    # The authorization boundary, evaluated per object and applied to every
    # count below. Each is built separately because each restricts a different
    # table's `source_object_id`.
    quarantine_is_authorized = authorized_object(
        quarantine_records.c.source_object_id, enrollment_id=enrollment_id
    )
    extraction_is_authorized = authorized_object(
        extractions.c.source_object_id, enrollment_id=enrollment_id
    )

    # The two subqueries are the precedence, written once and subtracted from
    # the counts that rank below them. Neither is executed on its own; each
    # becomes an `IN (SELECT …)` inside the count that has to exclude it. Both
    # carry the boundary too: an unauthorized quarantine must not suppress an
    # authorized extraction any more than it may be counted itself.
    quarantined_objects = select(quarantine_records.c.source_object_id).where(
        quarantine_records.c.enrollment_id == enrollment_id,
        quarantine_is_authorized,
    )
    unsupported_objects = select(extractions.c.source_object_id).where(
        extractions.c.enrollment_id == enrollment_id,
        extractions.c.status == ExtractionStatus.UNSUPPORTED.value,
        extraction_is_authorized,
    )

    quarantined = connection.execute(
        select(func.count(func.distinct(quarantine_records.c.source_object_id))).where(
            quarantine_records.c.enrollment_id == enrollment_id,
            quarantine_is_authorized,
        )
    ).scalar_one()
    unsupported = connection.execute(
        select(func.count(func.distinct(extractions.c.source_object_id))).where(
            extractions.c.enrollment_id == enrollment_id,
            extractions.c.status == ExtractionStatus.UNSUPPORTED.value,
            extraction_is_authorized,
            extractions.c.source_object_id.not_in(quarantined_objects),
        )
    ).scalar_one()
    processed = connection.execute(
        select(func.count(func.distinct(extractions.c.source_object_id))).where(
            extractions.c.enrollment_id == enrollment_id,
            extractions.c.status == ExtractionStatus.EXTRACTED.value,
            extraction_is_authorized,
            extractions.c.source_object_id.not_in(quarantined_objects),
            extractions.c.source_object_id.not_in(unsupported_objects),
        )
    ).scalar_one()
    limitations = tuple(
        AggregateLimitation(reason=LimitationReason(row[0]), affected_count=int(row[1]))
        for row in connection.execute(
            select(coverage_limitations.c.reason, coverage_limitations.c.affected_count).where(
                coverage_limitations.c.enrollment_id == enrollment_id,
                coverage_limitations.c.observed_at == moment,
            )
        )
    )

    if eligible is None:
        # The caller has no enumeration, so the total is what is accounted for
        # and nothing is invented on top of it. `queued` and `unavailable` are
        # included because they are objects the caller already knows about:
        # leaving them out would build a total smaller than the counts beside it
        # and raise from `CoverageCounts`, which is the crash this branch exists
        # to remove rather than relocate.
        eligible = int(processed) + int(quarantined) + int(unsupported) + unavailable + queued

    return CoverageCounts(
        observed_at=moment,
        enrollment_id=enrollment_id,
        eligible=eligible,
        queued=queued,
        processed=int(processed),
        quarantined=int(quarantined),
        unsupported=int(unsupported),
        unavailable=unavailable,
        limitations=limitations,
        snapshot=snapshot,
    )
