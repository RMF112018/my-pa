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

**Coverage is read for a stated enrollment and snapshot.** `coverage_for` counts
what this schema stores and requires the caller to supply what it does not: the
eligible total, and any queued or unavailable counts. That asymmetry is
deliberate. Only the layer that enumerated the scope knows how many objects were
eligible, and deriving the denominator from the rows that happen to exist would
report complete coverage of a scope nobody measured — exactly the global
inference section 12 forbids.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, func, select
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
    extractions,
    quarantine_records,
)

__all__ = [
    "coverage_for",
    "quarantine_object",
    "record_limitation",
    "record_outcome",
]


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
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    validate_identifier(source_object_id, IdKind.SOURCE_OBJECT)
    if version_id is not None:
        validate_identifier(version_id, IdKind.VERSION)

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
    eligible: int,
    queued: int = 0,
    unavailable: int = 0,
    snapshot: SnapshotState = SnapshotState.CURRENT,
) -> CoverageCounts:
    """Report coverage of `enrollment_id` for the snapshot `observed_at` names.

    Outcomes are counted for the whole enrollment, because that is the scope the
    grant defines and an outcome does not stop being true when the next pass
    starts. Limitations are matched to the snapshot exactly: a limitation is a
    property of one enumeration pass rather than a running total, and summing two
    passes over the same tree would report each omission twice.

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

    Raises `ValueError` — through `CoverageCounts` — when the counts do not fit
    inside `eligible`. That is the right failure: a scope smaller than what was
    processed within it means the caller's denominator is wrong, and reporting
    coverage from it would be a number that cannot be true.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    moment = ensure_utc(observed_at)

    # The two subqueries are the precedence, written once and subtracted from
    # the counts that rank below them. Neither is executed on its own; each
    # becomes an `IN (SELECT …)` inside the count that has to exclude it.
    quarantined_objects = select(quarantine_records.c.source_object_id).where(
        quarantine_records.c.enrollment_id == enrollment_id
    )
    unsupported_objects = select(extractions.c.source_object_id).where(
        extractions.c.enrollment_id == enrollment_id,
        extractions.c.status == ExtractionStatus.UNSUPPORTED.value,
    )

    quarantined = connection.execute(
        select(func.count(func.distinct(quarantine_records.c.source_object_id))).where(
            quarantine_records.c.enrollment_id == enrollment_id,
        )
    ).scalar_one()
    unsupported = connection.execute(
        select(func.count(func.distinct(extractions.c.source_object_id))).where(
            extractions.c.enrollment_id == enrollment_id,
            extractions.c.status == ExtractionStatus.UNSUPPORTED.value,
            extractions.c.source_object_id.not_in(quarantined_objects),
        )
    ).scalar_one()
    processed = connection.execute(
        select(func.count(func.distinct(extractions.c.source_object_id))).where(
            extractions.c.enrollment_id == enrollment_id,
            extractions.c.status == ExtractionStatus.EXTRACTED.value,
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
