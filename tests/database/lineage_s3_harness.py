"""Shared seeds and request builders for the record lineage S3 write tests (package L2).

A helper module, not a test module: pytest does not collect it. It extends the
S2 harness (`lineage_s2_harness.S2Runtime`) with what the S3 contest,
`related_context`, handoff-correction, race and attested-write tests need:

* `S3Runtime` -- `S2Runtime` with the backfill sub-switch stated explicitly
  (S3 contract section 7.7);
* the S3 requests (`contest`, `reinstate`, `related`, `correct_handoff`) and
  the exact anchors their rules ask for (`contradicts`, `corroborates`);
* `blocks_scene`: an Issue whose context holds one active `blocks` link;
* row counts over every S1, S2 and S3 lineage table, and the knowledge
  clock's marks.

Every identity and every body here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Final

from sqlalchemy import Engine, event, func, insert, select, text

from my_pa.application.commands import (
    AssertRecordAssociation,
    ContestRecordAssociation,
    CorrectIssueHandoff,
    ReinstateRecordAssociation,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import UnitOfWork
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.commitment_management import (
    SqlAlchemyCommitmentManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.constraints import SqlAlchemyConstraintManagementUnitOfWork
from my_pa.infrastructure.persistence.tables import (
    issue_responsibility_corrections,
    lineage_commit_marks,
    tasks,
)
from my_pa.infrastructure.persistence.task_management import SqlAlchemyTaskManagementUnitOfWork
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.lineage_issue_harness import LIMITS, PRINCIPAL, WHEN
from tests.database.lineage_record_harness import GATEWAY, NOTE_BODY, meeting, note_anchor
from tests.database.lineage_s2_harness import S2Runtime, all_s2_counts, assertion

__all__ = [
    "GATEWAY",
    "S3Runtime",
    "all_s3_counts",
    "blocks_scene",
    "contest",
    "contradicts",
    "correct_handoff",
    "corroborates",
    "direct_task",
    "mark_count",
    "mark_taken_first",
    "reinstate",
    "related",
    "shortly_after",
    "statements",
]

#: The two S3 tables the L2 writes touch, beside every S1/S2 table.
_S3_TABLES: Final = (issue_responsibility_corrections, lineage_commit_marks)


def all_s3_counts(engine: Engine) -> dict[str, int]:
    """Row counts of every S1/S2 table, the correction table and the commit marks."""
    counts = dict(all_s2_counts(engine))
    with engine.connect() as connection:
        for table in _S3_TABLES:
            counts[table.name] = int(
                connection.execute(select(func.count()).select_from(table)).scalar_one()
            )
    return counts


def mark_count(engine: Engine, principal_id: str = PRINCIPAL) -> int:
    """How many commit marks the Principal holds."""
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM knowledge.lineage_commit_marks WHERE principal_id = :p"),
                {"p": principal_id},
            ).scalar_one()
        )


@contextmanager
def statements(engine: Engine) -> Iterator[list[str]]:
    """Every statement `engine` sends inside the block, in order."""
    seen: list[str] = []

    def record(*arguments: Any) -> None:  # noqa: ANN401
        seen.append(str(arguments[2]))

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


_LOCKS: Final = ("FOR UPDATE", "FOR SHARE", "pg_advisory_xact_lock")


def mark_taken_first(seen: list[str]) -> bool:
    """S3 section 6.2 step 1b: the commit mark is the statement right after the reservation.

    No statement up to the reservation takes a lock.
    """
    reservation = next(
        index
        for index, statement in enumerate(seen)
        if "INSERT INTO knowledge.lineage_write_requests" in statement
    )
    return "knowledge.lineage_commit_mark(" in seen[reservation + 1] and not any(
        lock in statement for statement in seen[: reservation + 1] for lock in _LOCKS
    )


class S3Runtime(S2Runtime):
    """`S2Runtime` with the backfill sub-switch stated (default off)."""

    def __init__(
        self,
        url: str,
        *,
        lineage_enabled: bool = True,
        lineage_backfill_enabled: bool = False,
    ) -> None:
        super().__init__(url, lineage_enabled=lineage_enabled)
        audit = SqlAlchemyAuditSink(self.audit_engine)
        engine = self.engine

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(engine, audit=audit, relationship_memory_enabled=True)

        self.service = ApplicationService(
            unit_of_work=unit_of_work,
            limits=LIMITS,
            task_management_unit_of_work=lambda: SqlAlchemyTaskManagementUnitOfWork(engine),
            commitment_management_unit_of_work=lambda: SqlAlchemyCommitmentManagementUnitOfWork(
                engine
            ),
            constraint_management_unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(
                engine
            ),
            relationship_intelligence_enabled=True,
            relationship_intelligence_writes_enabled=True,
            relationship_memory_enabled=True,
            lineage_enabled=lineage_enabled,
            lineage_backfill_enabled=lineage_backfill_enabled,
        )

    def note(self, key: str, *, principal_id: str = PRINCIPAL) -> tuple[str, str]:
        """A Meeting with one note version (`NOTE_BODY`)."""
        return meeting(self, key, principal_id=principal_id)


# --- anchors -----------------------------------------------------------------------


def contradicts(meeting_id: str, note_id: str) -> dict[str, object]:
    """An exact note anchor with role `contradicts` (the contest and void rule)."""
    return note_anchor(meeting_id, note_id, NOTE_BODY, role="contradicts", passage=None)


def corroborates(meeting_id: str, note_id: str) -> dict[str, object]:
    """An exact note anchor with role `corroborates` (`blocks`, `related_context`)."""
    return note_anchor(meeting_id, note_id, NOTE_BODY, role="corroborates", passage=None)


# --- requests ------------------------------------------------------------------------


def contest(
    link_id: str,
    revision: int,
    key: str,
    anchors: tuple[dict[str, object], ...],
    *,
    reason: str = "The source says otherwise.",
) -> ContestRecordAssociation:
    return ContestRecordAssociation(
        link_id=link_id,
        expected_revision=revision,
        idempotency_key=f"s3-contest-{key}",
        reason=reason,
        evidence_anchors=anchors,
    )


def reinstate(
    link_id: str,
    revision: int,
    key: str,
    anchors: tuple[dict[str, object], ...],
    *,
    reason: str = "The dispute is resolved.",
) -> ReinstateRecordAssociation:
    return ReinstateRecordAssociation(
        link_id=link_id,
        expected_revision=revision,
        idempotency_key=f"s3-reinstate-{key}",
        reason=reason,
        evidence_anchors=anchors,
    )


def related(
    source: tuple[str, str],
    target: tuple[str, str],
    key: str,
    anchors: tuple[dict[str, object], ...],
    *,
    context: str | None,
) -> AssertRecordAssociation:
    """`records.associations.assert` of a `related_context` link (`(family, record_id)` each)."""
    return AssertRecordAssociation(
        from_record={"family": source[0], "record_id": source[1]},
        to_record={"family": target[0], "record_id": target[1]},
        relation_type="related_context",
        idempotency_key=f"s3-related-{key}",
        evidence_anchors=anchors,
        context_issue_id=context,
    )


def correct_handoff(
    handoff_id: str,
    action: str,
    key: str,
    anchor: dict[str, object],
    *,
    effective_at: str | None = None,
    reason: str = "The recorded handoff was wrong.",
) -> CorrectIssueHandoff:
    return CorrectIssueHandoff(
        handoff_id=handoff_id,
        action=action,
        idempotency_key=f"s3-handoff-correct-{key}",
        reason=reason,
        evidence_anchor=anchor,
        effective_at=effective_at,
    )


# --- seeds ---------------------------------------------------------------------------


def direct_task(engine: Engine, task_id: str, *, principal_id: str = PRINCIPAL) -> str:
    """A Task row with a chosen identifier (for code-point order cases), inserted directly."""
    with engine.begin() as connection:
        connection.execute(
            insert(tasks).values(
                task_id=task_id,
                principal_id=principal_id,
                title="Synthetic task",
                origin_kind="direct_principal",
                opened_at=WHEN,
                created_at=WHEN,
                updated_at=WHEN,
            )
        )
    return task_id


def shortly_after(instant: str, microseconds: int) -> str:
    """`instant` (ISO-8601) plus one millisecond and `microseconds`, ISO-8601 with offset.

    A view shows instants to the millisecond, so the base is one millisecond
    later than the shown value (S2 harness convention).
    """
    value = datetime.fromisoformat(instant)
    return (value + timedelta(milliseconds=1, microseconds=microseconds)).isoformat()


def blocks_scene(
    runtime: S3Runtime, key: str, *, context: bool = True, members: bool = False
) -> dict[str, Any]:
    """An Issue and one active `blocks` link between two Tasks.

    With `context` the link is scoped to the Issue; without it the link has a
    null context, and `members` makes both Tasks `reference` members of the
    Issue (so the link lies inside it). The Issue has no mandatory member, so
    its gate is otherwise open. Returns the identifiers and an exact note
    source for further anchors.
    """
    issue = runtime.issue(key)
    first = runtime.task(f"{key}-a")
    second = runtime.task(f"{key}-b")
    if members:
        runtime.member(issue, "task", first, f"{key}-a", "reference")
        runtime.member(issue, "task", second, f"{key}-b", "reference")
    meeting_id, note_id = runtime.note(f"{key}-source")
    written = runtime.ok(
        assertion(
            "blocks",
            ("task", first),
            ("task", second),
            f"{key}-blocks",
            (corroborates(meeting_id, note_id),),
            context=issue if context else None,
        ),
        surface=GATEWAY,
    )
    return {
        "issue": issue,
        "first": first,
        "second": second,
        "link": str(written["association"]["link_id"]),
        "meeting": meeting_id,
        "note": note_id,
        "corroborates": corroborates(meeting_id, note_id),
        "contradicts": contradicts(meeting_id, note_id),
    }
