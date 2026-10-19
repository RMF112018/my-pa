"""AT-014 (knowledge clock): every lineage write takes one commit-ordered mark.

S3 contract sections 3.4, 4.1, 4.2 and 6.2. The S3 revision gives every lineage
fact row the commit mark of its own transaction (`commit_seq`), allocated per
Principal from a row-locked allocator (`knowledge.lineage_commit_mark`), and
caps every `known_at` read at the committed horizon -- the allocator row's
`last_marked_at`, read without a lock. This module proves, on a live server:

* each of the fifteen S1/S2 lineage writes takes exactly one mark, stamped on
  every fact row it writes and on its request row, and takes it immediately
  after its reservation, before any other lock (a statement recorder on the
  writing engine);
* a replay and a refused write take none; marks are contiguous and strictly
  increasing in time, even past a clock that lags the allocator;
* no fact row can carry a forged mark or name a mark that does not exist;
* the horizon excludes a write still in flight, so an answer at a past
  `known_at` never changes after later commits; a row written before the S3
  revision is known by its own `recorded_at`.

The S3 writes take their marks through the same seam; their own write tests
are their packages' (S3 contract section 9). `database` tier on a disposable
head-migrated clone per test. Every value is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any, Final

import pytest
from sqlalchemy import Engine, event, insert, text
from sqlalchemy.engine import Connection

from my_pa.application.commands import (
    AddIssueMembership,
    AddIssueProjectLink,
    Command,
    CorrectRecordAssociation,
    CreateIssue,
    EndIssueMembership,
    EndIssueProjectLink,
    EndRecordAssociation,
    UpdateIssue,
)
from my_pa.domain.lineage.asof import effective_known_at
from my_pa.domain.lineage.vocabulary import (
    LINEAGE_WRITE_CAPABILITIES,
    S1_LINEAGE_WRITE_CAPABILITIES,
    S2_LINEAGE_WRITE_CAPABILITIES,
    LinkLifecycleState,
)
from my_pa.infrastructure.persistence.record_lineage import SqlRecordLineageRepository
from my_pa.infrastructure.persistence.tables import issue_revisions, situations
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL, PRINCIPAL
from tests.database.lineage_record_harness import (
    NOTE_BODY,
    capture,
    meeting,
    membership,
    note_anchor,
    originated_from,
)
from tests.database.lineage_s2_harness import (
    GATEWAY,
    REVIEW_DECISION,
    S2Runtime,
    close,
    correct,
    handoff,
    reopen,
    resolution_anchor,
    work_commitment,
    work_task,
)
from tests.database.test_commitment_entity_counterparty import seed_counterparty_entity
from tests.database.test_lineage_integrity_guards import (
    _issue,
    _link_values,
    _revision_values,
    _task,
    _write_link,
)

pytestmark = pytest.mark.database

CHECK: Final = "23514"
FOREIGN_KEY: Final = "23503"
#: The four S1/S2 fact tables and the S3 correction table: every row a mark.
FACT_TABLES: Final = (
    "issue_revisions",
    "issue_project_membership_events",
    "record_link_revisions",
    "issue_responsibility_events",
)
#: The lineage writes this package's writers cover (S1's nine and S2's six);
#: the four S3 writes take their marks through the same seam in their packages.
S1_S2_WRITES: Final = S1_LINEAGE_WRITE_CAPABILITIES | S2_LINEAGE_WRITE_CAPABILITIES
_LOCKS: Final = ("FOR UPDATE", "FOR SHARE", "pg_advisory_xact_lock")
#: Statements over one of the fixed table names above (never caller input).
_COUNT_MARKED: Final = (
    "SELECT count(*) FROM knowledge.{table} WHERE principal_id = :p AND commit_seq = :mark"
)
_COUNT_ORPHANED: Final = (
    "SELECT count(*) FROM knowledge.{table} f WHERE f.commit_seq IS NOT NULL AND NOT EXISTS "
    "(SELECT 1 FROM knowledge.lineage_commit_marks m WHERE m.principal_id = f.principal_id "
    "AND m.commit_seq = f.commit_seq)"
)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S2Runtime]:
    composed = S2Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


# ---- helpers -------------------------------------------------------------------------


def _marks(engine: Engine, principal: str = PRINCIPAL) -> list[tuple[int, datetime]]:
    with engine.connect() as c:
        return [
            (int(row.commit_seq), row.marked_at)
            for row in c.execute(
                text(
                    "SELECT commit_seq, marked_at FROM knowledge.lineage_commit_marks "
                    "WHERE principal_id = :p ORDER BY commit_seq"
                ),
                {"p": principal},
            )
        ]


def _allocator(engine: Engine, principal: str = PRINCIPAL) -> tuple[int, datetime] | None:
    with engine.connect() as c:
        row = c.execute(
            text(
                "SELECT last_seq, last_marked_at FROM knowledge.lineage_commit_sequences "
                "WHERE principal_id = :p"
            ),
            {"p": principal},
        ).one_or_none()
    return None if row is None else (int(row.last_seq), row.last_marked_at)


def _stamped(engine: Engine, mark: int, principal: str = PRINCIPAL) -> dict[str, int]:
    """How many rows of each marked table carry `mark`."""
    with engine.connect() as c:
        return {
            table: int(
                c.execute(
                    text(_COUNT_MARKED.format(table=table)),
                    {"p": principal, "mark": mark},
                ).scalar_one()
            )
            for table in (*FACT_TABLES, "issue_responsibility_corrections")
        }


def _request_mark(engine: Engine, capability: str, key: str) -> int | None:
    with engine.connect() as c:
        value = c.execute(
            text(
                "SELECT commit_seq FROM knowledge.lineage_write_requests "
                "WHERE principal_id = :p AND capability = :capability "
                "AND idempotency_key = :key AND completed_at IS NOT NULL"
            ),
            {"p": PRINCIPAL, "capability": capability, "key": key},
        ).scalar_one()
    return None if value is None else int(value)


@dataclass
class _Recorder:
    """Every statement the writing engine sends, per write."""

    statements: list[str] = field(default_factory=list)

    def __call__(
        self,
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        self.statements.append(statement)


@dataclass(frozen=True)
class _Write:
    capability: str
    key: str
    statements: tuple[str, ...]
    marks_before: int
    marks_after: int


def _write(
    runtime: S2Runtime, command: Command, recorded: list[_Write], *, surface: bool = True
) -> dict[str, Any]:
    recorder = _Recorder()
    before = len(_marks(runtime.engine))
    event.listen(runtime.engine, "before_cursor_execute", recorder)
    try:
        answer = runtime.ok(command, surface=GATEWAY) if surface else runtime.ok(command)
    finally:
        event.remove(runtime.engine, "before_cursor_execute", recorder)
    recorded.append(
        _Write(
            capability=command.capability.value,
            key=str(command.idempotency_key),  # type: ignore[attr-defined]
            statements=tuple(recorder.statements),
            marks_before=before,
            marks_after=len(_marks(runtime.engine)),
        )
    )
    return answer


def _every_s1_s2_write(runtime: S2Runtime) -> list[_Write]:
    """One of each of the fifteen S1/S2 lineage writes, recorded."""
    done: list[_Write] = []
    issue = _write(
        runtime, CreateIssue(title="Synthetic issue cm", idempotency_key="cm-create"), done
    )["issue"]["issue_id"]
    _write(
        runtime,
        UpdateIssue(
            issue_id=issue, expected_version=1, idempotency_key="cm-update", title="Renamed cm"
        ),
        done,
    )
    project = runtime.project("cm-project")
    _write(
        runtime,
        AddIssueProjectLink(
            issue_id=issue,
            project_id=project,
            expected_membership_revision=0,
            idempotency_key="cm-plink-add",
        ),
        done,
    )
    _write(
        runtime,
        EndIssueProjectLink(
            issue_id=issue,
            project_id=project,
            expected_membership_revision=1,
            idempotency_key="cm-plink-end",
            reason="Synthetic end.",
        ),
        done,
    )
    task = runtime.task("cm-task")
    member = _write(runtime, membership(issue, "task", task, "cm-member"), done)["membership"][
        "link_id"
    ]
    _meeting_id, _note_id, anchor = runtime.evidence_source("cm-evidence")
    _write(runtime, correct(member, 1, "cm-member-correct", (anchor,)), done)
    meeting_id, note_id = meeting(runtime, "cm-origin")
    origin = _write(
        runtime,
        originated_from(
            "task",
            task,
            "meeting_note_version",
            note_id,
            "cm-assert",
            (note_anchor(meeting_id, note_id, NOTE_BODY),),
        ),
        done,
    )["association"]["link_id"]
    _write(
        runtime,
        CorrectRecordAssociation(
            link_id=origin,
            expected_revision=1,
            idempotency_key="cm-assoc-correct",
            reason="Synthetic correction.",
            evidence_anchors=(
                note_anchor(meeting_id, note_id, NOTE_BODY, passage="Ana will send"),
            ),
        ),
        done,
    )
    _write(
        runtime,
        EndRecordAssociation(
            link_id=origin,
            expected_revision=2,
            idempotency_key="cm-assoc-end",
            reason="Synthetic end.",
        ),
        done,
    )
    _write(
        runtime,
        EndIssueMembership(
            link_id=member,
            expected_revision=2,
            idempotency_key="cm-member-end",
            reason="Synthetic end.",
        ),
        done,
    )
    commitment = runtime.commitment("cm-commitment")
    runtime.member(issue, "commitment", commitment, "cm-commitment", "work")
    view = runtime.commitment_view(commitment)
    created = datetime.fromisoformat(str(view["created_at"]))
    effective = (created + timedelta(milliseconds=1, microseconds=5)).isoformat()
    _write(
        runtime,
        handoff(
            issue,
            commitment,
            "counterparty",
            effective,
            "cm-handoff",
            runtime.handoff_anchor("cm-handoff"),
        ),
        done,
    )
    _write(runtime, work_task(issue, "cm-work-task"), done)
    origin_capture, _, _ = capture(runtime, "cm-work-origin")
    _write(
        runtime,
        work_commitment(
            issue,
            "cm-work-commitment",
            {
                "counterparty_entity_id": seed_counterparty_entity(runtime.engine, PRINCIPAL),
                "direction": "owed_to_principal",
                "summary": "Synthetic composite commitment",
                "origin_evidence_ref": origin_capture,
                "accepted_by_review_decision_id": REVIEW_DECISION,
            },
        ),
        done,
    )
    closable = runtime.issue("cm-closable")
    close_meeting, close_note, _ = runtime.evidence_source("cm-close")
    _write(
        runtime,
        close(closable, 1, "cm-close", (resolution_anchor(close_meeting, close_note),)),
        done,
    )
    _write(runtime, reopen(closable, 2, "cm-reopen"), done)
    return done


def _refused(
    engine: Engine, statement: Callable[[Connection], object], sqlstate: str, needle: str
) -> None:
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError) as refused, engine.begin() as connection:
        statement(connection)
    assert getattr(refused.value.orig, "sqlstate", None) == sqlstate, refused.value
    assert needle in str(refused.value), refused.value


# ---- each write, one mark -------------------------------------------------------------


def test_every_lineage_write_takes_exactly_one_commit_mark(runtime: S2Runtime) -> None:
    writes = _every_s1_s2_write(runtime)
    assert {write.capability for write in writes} == S1_S2_WRITES
    assert S1_S2_WRITES < LINEAGE_WRITE_CAPABILITIES
    marks = _marks(runtime.engine)
    for write in writes:
        # Exactly one new mark, and the write's request names it.
        assert write.marks_after == write.marks_before + 1, write.capability
        mark = marks[write.marks_after - 1][0]
        assert mark == write.marks_after, write.capability
        assert _request_mark(runtime.engine, write.capability, write.key) == mark
        # The mark is stamped on the fact rows that write wrote, and no others.
        stamped = _stamped(runtime.engine, mark)
        assert sum(stamped.values()) >= 1, (write.capability, stamped)
    # Every fact row written since the revision carries a mark.
    with runtime.engine.connect() as c:
        for table in FACT_TABLES:
            unmarked = c.execute(
                text(f"SELECT count(*) FROM knowledge.{table} WHERE commit_seq IS NULL")  # noqa: S608
            ).scalar_one()
            assert unmarked == 0, table
        # Every request that took a mark names a distinct one.
        named = c.execute(
            text(
                "SELECT count(*), count(DISTINCT commit_seq) FROM knowledge.lineage_write_requests "
                "WHERE principal_id = :p AND commit_seq IS NOT NULL"
            ),
            {"p": PRINCIPAL},
        ).one()
    assert named[0] == named[1] >= len(writes)


def test_every_writer_takes_its_mark_before_any_other_lock(runtime: S2Runtime) -> None:
    """The mark is the statement right after the reservation; no lock precedes it."""
    writes = _every_s1_s2_write(runtime)
    assert {write.capability for write in writes} == S1_S2_WRITES
    for write in writes:
        reservation = next(
            index
            for index, statement in enumerate(write.statements)
            if "INSERT INTO knowledge.lineage_write_requests" in statement
        )
        taken = write.statements[reservation + 1]
        assert "knowledge.lineage_commit_mark(" in taken, (write.capability, taken)
        for statement in write.statements[: reservation + 1]:
            assert not any(lock in statement for lock in _LOCKS), (write.capability, statement)


def test_a_replay_takes_no_commit_mark(runtime: S2Runtime) -> None:
    command = CreateIssue(title="Synthetic issue replay", idempotency_key="cm-replay")
    first = runtime.ok(command, surface=GATEWAY)
    marks = _marks(runtime.engine)
    allocator = _allocator(runtime.engine)
    again = runtime.ok(command, surface=GATEWAY)
    assert again["replayed"] is True
    assert again["issue"] == first["issue"]
    assert _marks(runtime.engine) == marks
    assert _allocator(runtime.engine) == allocator
    # A different request under the same key is a conflict, and takes none either.
    error = runtime.refused(
        CreateIssue(title="Another title", idempotency_key="cm-replay"), surface=GATEWAY
    )
    assert error["code"] == "conflict"
    assert _marks(runtime.engine) == marks
    assert _allocator(runtime.engine) == allocator


def test_a_refused_write_leaves_no_commit_mark(runtime: S2Runtime) -> None:
    issue = runtime.issue("cm-refused")
    marks = _marks(runtime.engine)
    allocator = _allocator(runtime.engine)
    # Reserved, marked and then refused (an absent member): all of it rolls back.
    error = runtime.refused(
        AddIssueMembership(
            issue_id=issue,
            member={"family": "task", "record_id": "tsk_lineages3absent01"},
            role="work",
            idempotency_key="cm-refused-member",
        ),
        surface=GATEWAY,
    )
    assert error["code"] == "not_found"
    assert _marks(runtime.engine) == marks
    assert _allocator(runtime.engine) == allocator
    with runtime.engine.connect() as c:
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM knowledge.lineage_write_requests "
                    "WHERE idempotency_key = 'cm-refused-member'"
                )
            ).scalar_one()
            == 0
        )
    # A Principal with no lineage fact gets no allocator row from a refusal.
    other = runtime.refused(
        UpdateIssue(
            issue_id=issue, expected_version=1, idempotency_key="cm-refused-other", title="X"
        ),
        principal_id=OTHER_PRINCIPAL,
        surface=GATEWAY,
    )
    assert other["code"] == "not_found"
    assert _allocator(runtime.engine, OTHER_PRINCIPAL) is None
    assert _marks(runtime.engine, OTHER_PRINCIPAL) == []


def test_commit_marks_are_contiguous_and_strictly_increasing(runtime: S2Runtime) -> None:
    engine = runtime.engine
    # A clock behind the allocator: the allocator row is seeded in the future,
    # so only `greatest(clock_timestamp(), last + 1 microsecond)` keeps each
    # mark later than the one before.
    principal = "prn_lineages3clock001"
    future = datetime.now(UTC) + timedelta(days=1)
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO knowledge.lineage_commit_sequences "
                "(principal_id, last_seq, last_marked_at) VALUES (:p, 0, :at)"
            ),
            {"p": principal, "at": future},
        )
    for _ in range(3):
        with engine.begin() as c:
            c.execute(text("SELECT knowledge.lineage_commit_mark(:p)"), {"p": principal})
    taken = _marks(engine, principal)
    assert [mark for mark, _ in taken] == [1, 2, 3]
    times = [marked for _, marked in taken]
    assert times[0] > future
    assert times == sorted(times) and len(set(times)) == 3
    assert _allocator(engine, principal) == taken[-1]
    # One transaction holds one mark, however often it asks.
    with engine.begin() as c:
        held = [
            c.execute(
                text("SELECT knowledge.lineage_commit_mark(:p)"), {"p": principal}
            ).scalar_one()
            for _ in range(3)
        ]
    assert held == [4, 4, 4]
    # Real writes: contiguous from 1, strictly increasing, the allocator at the last.
    _every_s1_s2_write(runtime)
    written = _marks(engine)
    assert [mark for mark, _ in written] == list(range(1, len(written) + 1))
    assert all(later[1] > earlier[1] for earlier, later in pairwise(written))
    assert _allocator(engine) == written[-1]


# ---- the guards -------------------------------------------------------------------------


def _bare_issue(c: Connection, principal: str = PRINCIPAL) -> str:
    """A `situations` Issue row at version 1 with no revision yet."""
    from my_pa.domain.common.identifiers import IdKind
    from my_pa.domain.source.registry import issue_identifier

    issue_id = issue_identifier(IdKind.SITUATION)
    when = datetime(2026, 10, 19, 12, tzinfo=UTC)
    c.execute(
        insert(situations).values(
            situation_id=issue_id,
            principal_id=principal,
            title="Synthetic issue",
            state="open",
            opened_at=when,
            created_at=when,
            updated_at=when,
            kind="issue_workstream",
            version=1,
        )
    )
    return issue_id


def test_a_fact_row_cannot_carry_a_forged_commit_seq(runtime: S2Runtime) -> None:
    engine = runtime.engine
    # Mark 1 committed by an earlier transaction.
    with engine.begin() as c:
        _issue(c, PRINCIPAL)
    assert [mark for mark, _ in _marks(engine)] == [1]

    def forged(value: int) -> Callable[[Connection], object]:
        def statement(c: Connection) -> None:
            issue_id = _bare_issue(c)
            row = _revision_values(PRINCIPAL, issue_id, 1, "Synthetic issue")
            c.execute(insert(issue_revisions).values(**row, commit_seq=value))

        return statement

    # Another transaction's (committed) mark, and a mark nobody holds.
    for value in (1, 99):
        _refused(engine, forged(value), CHECK, "carries its own transaction's commit mark")
    assert [mark for mark, _ in _marks(engine)] == [1]
    # Naming this transaction's own mark is the one admitted value.
    with engine.begin() as c:
        mark = int(
            c.execute(
                text("SELECT knowledge.lineage_commit_mark(:p)"), {"p": PRINCIPAL}
            ).scalar_one()
        )
        issue_id = _bare_issue(c)
        c.execute(
            insert(issue_revisions).values(
                **_revision_values(PRINCIPAL, issue_id, 1, "Synthetic issue"), commit_seq=mark
            )
        )
    assert mark == 2
    assert _stamped(engine, 2)["issue_revisions"] == 1


def test_every_fact_row_names_an_existing_mark(runtime: S2Runtime) -> None:
    engine = runtime.engine
    _every_s1_s2_write(runtime)
    with engine.connect() as c:
        for table in (*FACT_TABLES, "lineage_write_requests"):
            orphaned = c.execute(text(_COUNT_ORPHANED.format(table=table))).scalar_one()
            assert orphaned == 0, table
    # With the stamping trigger silenced, a fact naming no mark is refused by
    # the foreign key itself (`a_lineage_fact_names_its_commit_mark`).
    link = _link_row(engine)

    def unmarked(c: Connection) -> None:
        c.execute(
            text(
                "ALTER TABLE knowledge.record_link_revisions "
                "DISABLE TRIGGER a_lineage_fact_takes_its_commit_mark"
            )
        )
        c.execute(
            text(
                "INSERT INTO knowledge.record_link_revisions (principal_id, link_id, revision_no, "
                "revision_id, predecessor_revision_no, action, lifecycle_state, acceptance_basis, "
                "authority_class, decision_channel, source_capability, reason, evidence_count, "
                "evidence_set_digest, recorded_at, commit_seq) VALUES (:p, :link, :next, "
                "'irv_lineages3forged01', :previous, 'end', 'ended', 'user_confirmed', "
                "'local_operator', 'local_cli', 'records.associations.end', 'Synthetic.', 0, "
                ":digest, now(), 9999)"
            ),
            {
                "p": PRINCIPAL,
                "link": link[0],
                "next": link[1] + 1,
                "previous": link[1],
                "digest": "e" * 64,
            },
        )

    _refused(engine, unmarked, FOREIGN_KEY, "a_lineage_fact_names_its_commit_mark")


def _link_row(engine: Engine) -> tuple[str, int]:
    """An active association and its head revision number."""
    with engine.connect() as c:
        row = c.execute(
            text(
                "SELECT h.link_id, h.revision_no FROM knowledge.record_link_heads h "
                "JOIN knowledge.record_links l ON l.principal_id = h.principal_id "
                "AND l.link_id = h.link_id WHERE h.principal_id = :p "
                "AND h.lifecycle_state = 'active' ORDER BY h.link_id LIMIT 1"
            ),
            {"p": PRINCIPAL},
        ).one()
    return str(row.link_id), int(row.revision_no)


# ---- the horizon ---------------------------------------------------------------------------


def _cut(connection: Connection, principal: str = PRINCIPAL) -> tuple[datetime | None, int | None]:
    """`(T_k, W(T_k))` for a current read: the horizon and its watermark."""
    lineage = SqlRecordLineageRepository(connection)
    horizon = lineage.commit_horizon(principal)
    known_at = effective_known_at(None, now=datetime.now(UTC), horizon=horizon)
    watermark = None if known_at is None else lineage.commit_watermark(principal, known_at)
    return known_at, watermark


def test_the_horizon_excludes_an_in_flight_write(runtime: S2Runtime) -> None:
    engine = runtime.engine
    with engine.begin() as c:
        _issue(c, PRINCIPAL)
    with engine.connect() as reader:
        before = _cut(reader)
        reader.commit()
    assert before[1] == 1
    writer = engine.connect()
    try:
        transaction = writer.begin()
        # A lineage write in flight: its mark is allocated (the allocator row
        # locked and advanced) but not committed.
        _issue(writer, PRINCIPAL)
        in_flight = int(
            writer.execute(
                text("SELECT knowledge.lineage_commit_mark(:p)"), {"p": PRINCIPAL}
            ).scalar_one()
        )
        assert in_flight == 2
        with engine.connect() as reader:
            known_at, watermark = _cut(reader)
            reader.commit()
        # The reader neither waits nor sees it: its cut is the committed horizon.
        assert (known_at, watermark) == before
        transaction.commit()
    finally:
        writer.close()
    with engine.connect() as reader:
        lineage = SqlRecordLineageRepository(reader)
        # After the commit, the answer at that same cut is unchanged, forever.
        assert known_at is not None
        assert lineage.commit_watermark(PRINCIPAL, known_at) == watermark == 1
        marked = dict(_marks(engine))[2]
        assert marked > known_at
        later = _cut(reader)
        reader.commit()
    assert later[1] == 2


def test_a_past_known_at_answer_never_changes_after_later_commits(runtime: S2Runtime) -> None:
    engine = runtime.engine
    issue = runtime.issue("cm-past")
    task = runtime.task("cm-past-task")
    member = runtime.member(issue, "task", task, "cm-past-member", "work")
    meeting_id, note_id = meeting(runtime, "cm-past-origin")
    origin = runtime.ok(
        originated_from(
            "task",
            task,
            "meeting_note_version",
            note_id,
            "cm-past-assert",
            (note_anchor(meeting_id, note_id, NOTE_BODY),),
        ),
        surface=GATEWAY,
    )["association"]["link_id"]
    links = (member, origin)
    with engine.connect() as reader:
        known_at, watermark = _cut(reader)
        answer = SqlRecordLineageRepository(reader).link_states_known_at(
            PRINCIPAL, links, watermark=watermark, at=known_at
        )
        reader.commit()
    assert answer == {
        member: (1, LinkLifecycleState.ACTIVE),
        origin: (1, LinkLifecycleState.ACTIVE),
    }
    # Later commits end both links and add a new one.
    runtime.ok(
        EndRecordAssociation(
            link_id=origin, expected_revision=1, idempotency_key="cm-past-end", reason="Ended."
        ),
        surface=GATEWAY,
    )
    runtime.ok(
        EndIssueMembership(
            link_id=member, expected_revision=1, idempotency_key="cm-past-member-end", reason="X."
        ),
        surface=GATEWAY,
    )
    runtime.member(issue, "task", runtime.task("cm-past-later"), "cm-past-later", "work")
    with engine.connect() as reader:
        lineage = SqlRecordLineageRepository(reader)
        assert known_at is not None
        assert lineage.commit_watermark(PRINCIPAL, known_at) == watermark
        again = lineage.link_states_known_at(PRINCIPAL, links, watermark=watermark, at=known_at)
        now_at, now_watermark = _cut(reader)
        current = lineage.link_states_known_at(PRINCIPAL, links, watermark=now_watermark, at=now_at)
        reader.commit()
    assert again == answer
    # The current read does see the later commits.
    assert current == {
        member: (2, LinkLifecycleState.ENDED),
        origin: (2, LinkLifecycleState.ENDED),
    }


def test_pre_s3_rows_are_known_by_their_recorded_at(runtime: S2Runtime) -> None:
    engine = runtime.engine
    with engine.begin() as c:
        # Rows as the S2 schema wrote them: no mark. Every trigger is silenced for
        # this seeding transaction (`replica`), the stamping one included.
        c.execute(text("SET LOCAL session_replication_role = replica"))
        issue = _issue(c, PRINCIPAL)
        task = _task(c, PRINCIPAL)
        link = _write_link(
            c,
            _link_values(
                PRINCIPAL,
                kind="issue_membership",
                relation="issue_member",
                source=("situation", issue),
                target=("task", task),
                member_role="work",
                context=issue,
            ),
        )
    with engine.connect() as c:
        stored = c.execute(
            text(
                "SELECT commit_seq, recorded_at FROM knowledge.record_link_revisions "
                "WHERE link_id = :link"
            ),
            {"link": link},
        ).one()
    assert stored.commit_seq is None
    written_at = stored.recorded_at
    assert written_at <= datetime.now(UTC)
    with engine.connect() as reader:
        lineage = SqlRecordLineageRepository(reader)
        # No mark exists: a pre-S3 row is known exactly from its own recorded_at.
        assert lineage.commit_horizon(PRINCIPAL) is None
        assert (
            lineage.link_states_known_at(
                PRINCIPAL, (link,), watermark=None, at=written_at - timedelta(microseconds=1)
            )
            == {}
        )
        assert lineage.link_states_known_at(PRINCIPAL, (link,), watermark=None, at=written_at) == {
            link: (1, LinkLifecycleState.ACTIVE)
        }
        reader.commit()
    # A marked revision after it is known only from its mark onwards.
    runtime.ok(
        EndIssueMembership(
            link_id=link, expected_revision=1, idempotency_key="cm-pre-end", reason="Ended."
        ),
        surface=GATEWAY,
    )
    marks = _marks(engine)
    assert [mark for mark, _ in marks] == [1]
    with engine.connect() as reader:
        lineage = SqlRecordLineageRepository(reader)
        before_mark = marks[0][1] - timedelta(microseconds=1)
        assert lineage.commit_watermark(PRINCIPAL, before_mark) is None
        assert lineage.link_states_known_at(PRINCIPAL, (link,), watermark=None, at=before_mark) == {
            link: (1, LinkLifecycleState.ACTIVE)
        }
        assert lineage.link_states_known_at(PRINCIPAL, (link,), watermark=1, at=marks[0][1]) == {
            link: (2, LinkLifecycleState.ENDED)
        }
        reader.commit()
