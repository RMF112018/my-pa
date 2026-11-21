"""ADR-020: the Meeting prep brief chain behind `SqlMeetingRepository`, on a live server.

The `database` tier, on a disposable head-migrated clone. What is proved here is
the persistence half of ADR-020: a first version and a supersede chain written
through `insert_prep_version`; `read_prep_head` is the one unsuperseded version;
`read_prep_version` finds a version by number and says whether it is current;
another Principal sees nothing of the chain; `meetings.search` matches the
current prep version and never a superseded one (C5); and the current-prep
expression is eligible for its GIN index.

Every identifier, title and body here is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy import Engine, func, literal_column, select, text
from sqlalchemy.dialects.postgresql import REGCONFIG

from my_pa.contracts.ports import MeetingPrepRecord, MeetingRecord
from my_pa.contracts.v1.meetings import MeetingHistoryView
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.meeting.model import (
    MeetingActor,
    MeetingHistoryAction,
    MeetingOutcome,
    MeetingSearchRequest,
    MeetingStatus,
    note_content_sha256,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.meetings import SqlMeetingRepository, _prep_document
from my_pa.infrastructure.persistence.tables import meeting_prep_versions

pytestmark = pytest.mark.database

T0: Final = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
NOW: Final = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
DIGEST: Final = "a" * 64


def _meeting(title: str, start_at: datetime = T0) -> MeetingRecord:
    return MeetingRecord(
        meeting_id=issue_identifier(IdKind.MEETING),
        meeting_series_id=None,
        title=title,
        start_at=start_at,
        end_at=None,
        timezone_name="UTC",
        status=MeetingStatus.SCHEDULED,
        cancelled_at=None,
        location_text=None,
        virtual_meeting_url=None,
        description=None,
        project_id=None,
        version=1,
        created_at=T0,
        updated_at=T0,
    )


def _receipt(meeting_id: str, *, before: int, after: int) -> MeetingHistoryView:
    return MeetingHistoryView(
        history_id=issue_identifier(IdKind.MEETING_HISTORY),
        meeting_id=meeting_id,
        action=MeetingHistoryAction.CREATE if before == 0 else MeetingHistoryAction.UPDATE,
        actor=MeetingActor.PRINCIPAL,
        outcome=MeetingOutcome.APPLIED,
        before_version=before,
        after_version=after,
        occurred_at=T0,
        recorded_at=T0,
    )


def _prep(
    meeting_id: str,
    history_id: str,
    body: str,
    *,
    version_number: int = 1,
    supersedes: str | None = None,
) -> MeetingPrepRecord:
    return MeetingPrepRecord(
        prep_version_id=issue_identifier(IdKind.MEETING_PREP_VERSION),
        meeting_id=meeting_id,
        version_number=version_number,
        supersedes_prep_version_id=supersedes,
        content_markdown=body,
        content_sha256=note_content_sha256(body),
        meeting_history_id=history_id,
        recorded_at=T0 + timedelta(minutes=version_number),
    )


def _write_chain(
    engine: Engine, principal_id: str, title: str, bodies: tuple[str, ...]
) -> tuple[MeetingRecord, list[MeetingPrepRecord]]:
    """One Meeting, one receipt per version, and a prep chain of `bodies` in order."""
    meeting = _meeting(title)
    written: list[MeetingPrepRecord] = []
    with engine.begin() as connection:
        repository = SqlMeetingRepository(connection)
        repository.insert_meeting(principal_id, meeting)
        for number, body in enumerate(bodies, start=1):
            receipt = _receipt(meeting.meeting_id, before=number - 1, after=number)
            repository.insert_meeting_history(
                principal_id,
                receipt,
                meeting_series_id=None,
                idempotency_key=f"prep-{number}",
                request_digest=DIGEST,
            )
            prep = _prep(
                meeting.meeting_id,
                receipt.history_id,
                body,
                version_number=number,
                supersedes=written[-1].prep_version_id if written else None,
            )
            repository.insert_prep_version(principal_id, prep)
            written.append(prep)
    return meeting, written


def _search(engine: Engine, principal_id: str, query: str) -> list[str]:
    with engine.connect() as connection:
        page = SqlMeetingRepository(connection).search_meetings(
            principal_id, MeetingSearchRequest(query=query), now=NOW
        )
    return [entry.meeting_id for entry in page.entries]


@pytest.fixture
def principals() -> tuple[str, str]:
    return issue_identifier(IdKind.PRINCIPAL), issue_identifier(IdKind.PRINCIPAL)


def test_a_meeting_without_prep_has_no_head_and_no_versions(
    db_engine: Engine, principals: tuple[str, str]
) -> None:
    mine, _ = principals
    meeting, _ = _write_chain(db_engine, mine, "Synthetic standup", ())
    with db_engine.connect() as connection:
        repository = SqlMeetingRepository(connection)
        assert repository.read_prep_head(mine, meeting.meeting_id) is None
        assert repository.read_prep_version(mine, meeting.meeting_id, 1) is None


def test_the_first_version_is_the_head(db_engine: Engine, principals: tuple[str, str]) -> None:
    mine, _ = principals
    meeting, (first,) = _write_chain(db_engine, mine, "Synthetic review", ("Agenda one.",))
    with db_engine.connect() as connection:
        head = SqlMeetingRepository(connection).read_prep_head(mine, meeting.meeting_id)
    assert head is not None
    assert head.prep_version_id == first.prep_version_id
    assert head.meeting_id == meeting.meeting_id
    assert head.version_number == 1
    assert head.supersedes_prep_version_id is None
    assert head.body == "Agenda one."
    assert head.content_sha256 == note_content_sha256("Agenda one.")
    assert head.recorded_at == first.recorded_at
    assert head.is_current is True


def test_the_head_is_the_unsuperseded_end_of_the_chain_and_each_version_is_by_number(
    db_engine: Engine, principals: tuple[str, str]
) -> None:
    mine, _ = principals
    bodies = ("Draft agenda.", "Second agenda.", "Final agenda.")
    meeting, chain = _write_chain(db_engine, mine, "Synthetic planning", bodies)
    with db_engine.connect() as connection:
        repository = SqlMeetingRepository(connection)
        head = repository.read_prep_head(mine, meeting.meeting_id)
        versions = [repository.read_prep_version(mine, meeting.meeting_id, n) for n in (1, 2, 3)]
        absent = repository.read_prep_version(mine, meeting.meeting_id, 4)
    assert head is not None
    assert (head.prep_version_id, head.version_number, head.body) == (
        chain[2].prep_version_id,
        3,
        "Final agenda.",
    )
    assert head.supersedes_prep_version_id == chain[1].prep_version_id
    assert [v.prep_version_id for v in versions if v is not None] == [
        p.prep_version_id for p in chain
    ]
    assert [v.is_current for v in versions if v is not None] == [False, False, True]
    assert [v.body for v in versions if v is not None] == list(bodies)
    assert versions[1] is not None
    assert versions[1].supersedes_prep_version_id == chain[0].prep_version_id
    assert absent is None


def test_another_principal_sees_nothing_of_the_chain(
    db_engine: Engine, principals: tuple[str, str]
) -> None:
    mine, theirs = principals
    meeting, _ = _write_chain(db_engine, mine, "Synthetic one-on-one", ("Mine.", "Mine again."))
    with db_engine.connect() as connection:
        repository = SqlMeetingRepository(connection)
        assert repository.read_prep_head(theirs, meeting.meeting_id) is None
        assert repository.read_prep_version(theirs, meeting.meeting_id, 1) is None
        assert repository.read_prep_version(theirs, meeting.meeting_id, 2) is None
    assert _search(db_engine, theirs, "again") == []


def test_search_matches_the_current_prep_and_never_a_superseded_one(
    db_engine: Engine, principals: tuple[str, str]
) -> None:
    mine, theirs = principals
    current, _ = _write_chain(db_engine, mine, "Synthetic sync", ("Discuss the narwhal budget.",))
    rewritten, _ = _write_chain(
        db_engine, mine, "Synthetic retro", ("Old axolotl wording.", "Rewritten quokka wording.")
    )
    _write_chain(db_engine, theirs, "Their sync", ("Their narwhal agenda.",))
    assert _search(db_engine, mine, "narwhal") == [current.meeting_id]
    assert _search(db_engine, mine, "quokka") == [rewritten.meeting_id]
    assert _search(db_engine, mine, "axolotl") == []
    assert _search(db_engine, theirs, "narwhal") != []
    assert current.meeting_id not in _search(db_engine, theirs, "narwhal")


def test_the_current_prep_expression_is_eligible_for_its_gin_index(
    db_engine: Engine, principals: tuple[str, str]
) -> None:
    mine, _ = principals
    _write_chain(db_engine, mine, "Synthetic index", ("Word13 agenda.",))
    query = func.websearch_to_tsquery(literal_column("'simple'", REGCONFIG), "word13")
    # The text predicate alone: on a handful of rows the planner would rather
    # probe the Principal btree, which is not what this test is about.
    statement = select(meeting_prep_versions.c.prep_version_id).where(
        _prep_document().bool_op("@@")(query)
    )
    with db_engine.begin() as connection:
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        compiled = statement.compile(connection)
        plan = "\n".join(
            connection.exec_driver_sql(f"EXPLAIN {compiled.string}", compiled.params).scalars()
        )
    assert "meeting_prep_versions_text" in plan
