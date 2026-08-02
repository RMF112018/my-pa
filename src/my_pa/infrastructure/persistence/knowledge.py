"""The three reads `knowledge.read` and `sources.status` need, and no writes.

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
"""

from __future__ import annotations

from sqlalchemy import Connection, Row, func, literal, select

from my_pa.contracts.ports import KnowledgeRecord
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.provenance import Provenance, TrustLevel
from my_pa.domain.extraction.coverage import AggregateLimitation, LimitationReason
from my_pa.domain.extraction.text import ExtractionStatus
from my_pa.infrastructure.persistence.extraction import authorized_object, extracted_text_in_scope
from my_pa.infrastructure.persistence.tables import (
    coverage_limitations,
    extractions,
    quarantine_records,
    source_objects,
)

__all__ = ["latest_limitations", "outcome_for_object", "read_extraction"]

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
