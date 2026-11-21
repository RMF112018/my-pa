"""ADR-020 (meeting prep briefs): `MeetingApplication` writes and reads prep versions.

The `database` tier. Every case drives `MeetingApplication` through the real
`SqlAlchemyUnitOfWork` `ApplicationService.invoke` opens, on a disposable
current-head database, exactly as `test_meeting_application.py` does for the
note chain this one parallels (ADR-020 C1-C8):

* the first version on create and on a later update, each naming its receipt;
* the supersede chain v1 -> v2 -> v3, whose head is v3;
* an identical body is a `no_op` receipt with no version and no version bump;
* a stale `expected_version` is a conflict that writes nothing;
* same key and body replays with no extra version, another body conflicts;
* the cap and a blank body are refused before any write;
* every prep row carries the Meeting's Principal, and another Principal's
  Meeting (and so its prep and its history) is `not_found`;
* search matches the current prep only, inside the caller's partition;
* the history read returns each version's body, digest and currency;
* the Record Event names the field `prep`, never the body;
* two overlapping prep writers serialize on the Meeting row and the loser is
  stale, so the chain stays linear (also `recovery`, as the note race is).

Every identifier, title and body here is synthetic.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, select

from my_pa.contracts.v1.meetings import MeetingView
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.meeting.model import (
    MAX_MEETING_PREP_CHARACTERS,
    MEETINGS_UPDATE_NAME,
    MeetingCreateRequest,
    MeetingErrorField,
    MeetingIdempotencyConflictError,
    MeetingInvalidRequestError,
    MeetingNotFoundError,
    MeetingOutcome,
    MeetingSearchRequest,
    MeetingStaleVersionError,
    MeetingUpdateRequest,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.tables import (
    meeting_history,
    meeting_prep_versions,
    record_events,
)
from tests.database.test_meeting_application import (
    APP,
    NOW,
    T0,
    ZONE,
    Harness,
    Stage,
    _count,
    _meeting_rows_of,
    _partition,
    _race,
    _request_row,
)

pytestmark = pytest.mark.database

_START: Final = T0 + timedelta(days=30)


@pytest.fixture
def harness(db_engine: Engine) -> Harness:
    return Harness(db_engine)


@pytest.fixture
def stage(db_engine: Engine) -> Stage:
    with db_engine.begin() as connection:
        return Stage(mine=_partition(connection), theirs=_partition(connection))


def _create(harness: Harness, principal_id: str, key: str, **extra: Any) -> MeetingView:  # noqa: ANN401
    request = MeetingCreateRequest(
        title="Synthetic prep sync", start_at=_START, timezone_name=ZONE, **extra
    )
    return harness.create(principal_id, request, key).meeting


def _prep(meeting_id: str, body: str) -> MeetingUpdateRequest:
    return MeetingUpdateRequest(meeting_id=meeting_id, prep_markdown=body)


def _prep_rows(engine: Engine, meeting_id: str) -> list[dict[str, Any]]:
    statement = (
        select(meeting_prep_versions)
        .where(meeting_prep_versions.c.meeting_id == meeting_id)
        .order_by(meeting_prep_versions.c.version_number)
    )
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(statement).mappings()]


def _sha(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def test_the_first_version_on_create_names_the_create_receipt(
    harness: Harness, stage: Stage
) -> None:
    principal = stage.mine.principal_id
    written = harness.create(
        principal,
        MeetingCreateRequest(
            title="Synthetic prep sync",
            start_at=_START,
            timezone_name=ZONE,
            prep_markdown="Agenda: **budget**",
        ),
        "prep-create",
    )
    prep = written.meeting.prep
    assert prep is not None
    assert (prep.version_number, prep.supersedes_prep_version_id, prep.is_current) == (
        1,
        None,
        True,
    )
    assert prep.body_markdown == "Agenda: **budget**"
    assert prep.content_sha256 == _sha("Agenda: **budget**")
    assert prep.character_count == len("Agenda: **budget**")
    (row,) = _prep_rows(harness.engine, written.meeting.meeting_id)
    assert row["meeting_history_id"] == written.receipt.history_id
    assert row["principal_id"] == principal
    assert written.meeting.prep_version is None
    assert harness.read(principal, written.meeting.meeting_id).prep == prep


def test_the_chain_supersedes_and_each_version_names_its_receipt(
    harness: Harness, stage: Stage
) -> None:
    principal = stage.mine.principal_id
    meeting = _create(harness, principal, "seed")
    assert meeting.prep is None
    receipts: list[str] = []
    for version, body in enumerate(("first brief", "second brief", "third brief"), start=1):
        written = harness.update(principal, _prep(meeting.meeting_id, body), version, f"p{version}")
        assert written.receipt.outcome is MeetingOutcome.APPLIED
        assert written.meeting.version == version + 1
        receipts.append(written.receipt.history_id)
    head = written.meeting.prep
    assert head is not None and head.version_number == 3 and head.body_markdown == "third brief"

    rows = _prep_rows(harness.engine, meeting.meeting_id)
    assert [row["version_number"] for row in rows] == [1, 2, 3]
    assert [row["meeting_history_id"] for row in rows] == receipts
    assert rows[0]["supersedes_prep_version_id"] is None
    assert rows[1]["supersedes_prep_version_id"] == rows[0]["prep_version_id"]
    assert rows[2]["supersedes_prep_version_id"] == rows[1]["prep_version_id"]
    assert {row["principal_id"] for row in rows} == {principal}
    assert head.prep_version_id == rows[2]["prep_version_id"]


def test_an_identical_body_is_a_no_op_with_no_version(harness: Harness, stage: Stage) -> None:
    principal = stage.mine.principal_id
    meeting = _create(harness, principal, "seed", prep_markdown="Same brief")
    same = harness.update(principal, _prep(meeting.meeting_id, "Same brief"), 1, "same")
    assert same.receipt.outcome is MeetingOutcome.NO_OP
    assert (same.receipt.before_version, same.receipt.after_version) == (1, 1)
    assert same.meeting.version == 1
    assert same.meeting.prep == meeting.prep
    assert len(_prep_rows(harness.engine, meeting.meeting_id)) == 1
    row = _request_row(harness.engine, principal, MEETINGS_UPDATE_NAME, "same")
    assert row["completed_at"] is not None and row["result_version"] == 1


def test_a_stale_version_conflicts_and_writes_nothing(harness: Harness, stage: Stage) -> None:
    principal = stage.mine.principal_id
    meeting = _create(harness, principal, "seed", prep_markdown="v1")
    harness.update(principal, _prep(meeting.meeting_id, "v2"), 1, "v2")
    before = _meeting_rows_of(harness.engine, principal)
    prep_before = _prep_rows(harness.engine, meeting.meeting_id)
    with pytest.raises(MeetingStaleVersionError):
        harness.update(principal, _prep(meeting.meeting_id, "v3"), 1, "stale")
    assert _meeting_rows_of(harness.engine, principal) == before
    assert _prep_rows(harness.engine, meeting.meeting_id) == prep_before


def test_a_replay_writes_no_version_and_another_body_conflicts(
    harness: Harness, stage: Stage
) -> None:
    principal = stage.mine.principal_id
    meeting = _create(harness, principal, "seed")
    first = harness.update(principal, _prep(meeting.meeting_id, "brief"), 1, "k")
    again = harness.update(principal, _prep(meeting.meeting_id, "brief"), 1, "k")
    assert again.replayed is True
    assert again.receipt == first.receipt
    assert again.meeting.prep == first.meeting.prep
    assert len(_prep_rows(harness.engine, meeting.meeting_id)) == 1
    with pytest.raises(MeetingIdempotencyConflictError):
        harness.update(principal, _prep(meeting.meeting_id, "other brief"), 1, "k")
    assert len(_prep_rows(harness.engine, meeting.meeting_id)) == 1


def test_the_cap_is_stored_and_one_over_or_blank_is_refused(harness: Harness, stage: Stage) -> None:
    principal = stage.mine.principal_id
    at_cap = "a" * MAX_MEETING_PREP_CHARACTERS
    meeting = _create(harness, principal, "seed", prep_markdown=at_cap)
    assert meeting.prep is not None and meeting.prep.character_count == MAX_MEETING_PREP_CHARACTERS
    for refused in (at_cap + "a", "", "  \n\t"):
        with pytest.raises(MeetingInvalidRequestError) as error:
            _prep(meeting.meeting_id, refused)
        assert error.value.field is MeetingErrorField.PREP
    assert len(_prep_rows(harness.engine, meeting.meeting_id)) == 1


def test_another_principals_meeting_and_its_prep_are_not_found(
    harness: Harness, stage: Stage
) -> None:
    theirs = _create(harness, stage.theirs.principal_id, "theirs", prep_markdown="their brief")
    mine = stage.mine.principal_id
    absent = issue_identifier(IdKind.MEETING)
    for meeting_id in (theirs.meeting_id, absent):
        for number in (None, 1):
            with pytest.raises(MeetingNotFoundError) as error:
                harness.run(lambda uow, m=meeting_id, n=number: APP.read_meeting(uow, mine, m, n))
            assert error.value.field is MeetingErrorField.MEETING_ID
        with pytest.raises(MeetingNotFoundError) as error:
            harness.update(mine, _prep(meeting_id, "hijack"), 1, f"u-{meeting_id[-6:]}")
        assert error.value.field is MeetingErrorField.MEETING_ID
    assert [row["content_markdown"] for row in _prep_rows(harness.engine, theirs.meeting_id)] == [
        "their brief"
    ]


def test_search_matches_the_current_prep_inside_the_partition(
    harness: Harness, stage: Stage
) -> None:
    principal = stage.mine.principal_id
    meeting = _create(harness, principal, "seed", prep_markdown="zebracrossing")
    harness.update(principal, _prep(meeting.meeting_id, "yakshaving"), 1, "replace")
    _create(harness, stage.theirs.principal_id, "theirs", prep_markdown="yakshaving")

    def search(owner: str, query: str) -> list[str]:
        page = harness.run(
            lambda uow: APP.search_meetings(uow, owner, MeetingSearchRequest(query=query), NOW)
        )
        return [entry.meeting_id for entry in page.entries]

    assert search(principal, "yakshaving") == [meeting.meeting_id]
    assert search(principal, "zebracrossing") == []


def test_the_history_read_returns_each_version_by_number(harness: Harness, stage: Stage) -> None:
    principal = stage.mine.principal_id
    meeting = _create(harness, principal, "seed", prep_markdown="one")
    harness.update(principal, _prep(meeting.meeting_id, "two"), 1, "two")
    rows = _prep_rows(harness.engine, meeting.meeting_id)
    for row in rows:
        view = harness.run(
            lambda uow, n=row["version_number"]: APP.read_meeting(
                uow, principal, meeting.meeting_id, n
            )
        )
        assert view.prep is not None and view.prep.version_number == 2
        version = view.prep_version
        assert version is not None
        assert version.prep_version_id == row["prep_version_id"]
        assert version.body_markdown == row["content_markdown"]
        assert version.content_sha256 == row["content_sha256"] == _sha(row["content_markdown"])
        assert version.is_current is (row["version_number"] == 2)
    with pytest.raises(MeetingNotFoundError) as error:
        harness.run(lambda uow: APP.read_meeting(uow, principal, meeting.meeting_id, 3))
    assert error.value.field is MeetingErrorField.PREP


def test_the_record_event_names_prep_and_never_the_body(harness: Harness, stage: Stage) -> None:
    principal = stage.mine.principal_id
    meeting = _create(harness, principal, "seed", prep_markdown="MARKERPREPCREATE")
    written = harness.update(principal, _prep(meeting.meeting_id, "MARKERPREPUPDATE"), 1, "u")
    statement = (
        select(record_events)
        .where(record_events.c.record_id == meeting.meeting_id)
        .order_by(record_events.c.sequence_number)
    )
    with harness.engine.connect() as connection:
        events = [dict(row) for row in connection.execute(statement).mappings()]
    assert len(events) == 2
    created, updated = events
    assert "prep" in created["changed_fields"]
    assert updated["changed_fields"] == ["prep"]
    assert updated["source_receipt_id"] == written.receipt.history_id
    for event in events:
        assert "MARKERPREP" not in repr(event)
    assert _count(harness.engine, meeting_history, meeting_id=meeting.meeting_id) == 2


@pytest.mark.recovery
def test_two_concurrent_prep_writers_serialize_and_the_second_is_stale(
    harness: Harness, stage: Stage
) -> None:
    principal = stage.mine.principal_id
    meeting = _create(harness, principal, "seed", prep_markdown="base brief")
    first, future = _race(
        harness,
        lambda uow: APP.update_meeting(
            uow, principal, _prep(meeting.meeting_id, "first brief"), 1, "first", NOW
        ),
        lambda: harness.update(principal, _prep(meeting.meeting_id, "second brief"), 1, "second"),
    )
    assert first.meeting.prep is not None and first.meeting.prep.version_number == 2
    with pytest.raises(MeetingStaleVersionError):
        future.result()
    rows = _prep_rows(harness.engine, meeting.meeting_id)
    assert [row["content_markdown"] for row in rows] == ["base brief", "first brief"]
    assert rows[1]["supersedes_prep_version_id"] == rows[0]["prep_version_id"]
