"""WP5-S3: the FAST fakes the context assembler is tested over answer as PostgreSQL does.

`tests/unit/test_meeting_context_assembly.py` runs `MeetingContextReads` over
the conftest Meeting fake (`read_context_inputs`) and `FakeCommunications`
(`context_self_addresses`, `non_ascii_participant_addresses`,
`list_message_identifiers`; the candidate statement is canned there). Here the
same inputs go to both and the answers are compared:

* the communications rows are written to PostgreSQL through the real
  repositories, read back, and copied into the fake, so both hold the same rows;
* the Meetings are made by the same `MeetingApplication.create_meeting` calls
  over the fake unit of work and over the SQL one, and compared with their
  generated ids aligned.

Every identifier, address and text here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy import Engine, insert

from my_pa.application.meetings import MeetingApplication
from my_pa.contracts.ports import MeetingContextInput, MeetingProviderReviewMarkRecord
from my_pa.domain.communications.identifiers import IDENTIFIER_VERSION
from my_pa.domain.meeting.context import IDENTIFIER_SCAN_CHARACTERS
from my_pa.domain.meeting.model import MeetingCreateRequest, normalize_attendee
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.tables import meeting_provider_review_marks
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.conftest import FakeUnitOfWork, World
from tests.contract.test_meeting_mcp import _insert_partition
from tests.database.communications_search_world import World as MailWorld
from tests.database.communications_search_world import at
from tests.unit.communications_ingest_fakes import FakeCommunications, IngestWorld

pytestmark = pytest.mark.database

NOW: Final = datetime(2026, 11, 21, 12, tzinfo=UTC)
APP: Final = MeetingApplication()


def _unit(engine: Engine) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(engine, audit=SqlAlchemyAuditSink(engine))


@pytest.fixture
def principal(migrated_engine: Engine) -> Iterator[str]:
    with migrated_engine.begin() as connection:
        yield _insert_partition(connection).principal.principal_id


def _copy_into_fake(engine: Engine, principal_id: str, message_ids: list[str]) -> IngestWorld:
    world = IngestWorld()
    fake = FakeCommunications(world)
    with _unit(engine) as unit:
        sql = unit.communications
        for message in sql.list_messages(principal_id, message_ids):
            fake.insert_message(principal_id, message)
            for item in sql.list_items(principal_id, message.message_id):
                fake.insert_item(principal_id, item)
            for observation in sql.list_observations(principal_id, message.message_id):
                fake.insert_observation(principal_id, observation)
            fake.insert_participants(
                principal_id, sql.list_participants(principal_id, message.message_id)
            )
            fake.insert_identifiers(
                principal_id, sql.list_identifiers(principal_id, message.message_id)
            )
    return world


def test_the_communications_context_reads_answer_alike(
    migrated_engine: Engine, principal: str
) -> None:
    mail = MailWorld(migrated_engine, principal_id=principal, tag="p")
    other = MailWorld(migrated_engine, tag="q")
    ids = [
        mail.message(
            1,
            subject="RFI 7",
            text="RFI 8 and CO 2",
            when=at(17, 10),
            participants=(("from", "owner.b@example.test"), ("to", "straße@example.test")),
            lanes=(("sent", "verified"),),
        ),
        mail.message(
            2,
            subject="Plain",
            text="RFI 7",
            when=at(17, 11),
            participants=(("from", "owner.a@example.test"),),
            lanes=(("inbox", "verified"), ("sent", "unverified_lane_claim")),
        ),
        mail.message(
            3,
            subject="Plain",
            text="x",
            when=at(17, 12),
            participants=(("from", "ꭰꭱ@example.test"), ("cc", "οδος@example.test")),
        ),
        mail.message(
            4,
            subject="Plain",
            text="x",
            when=at(17, 13),
            participants=(("from", "inbox.only@example.test"),),
        ),
    ]
    other.message(
        1,
        subject="Foreign",
        text="RFI 7",
        when=at(17, 10),
        participants=(("from", "foreign@example.test"),),
        lanes=(("sent", "verified"),),
    )
    fake = FakeCommunications(_copy_into_fake(migrated_engine, principal, ids))
    with _unit(migrated_engine) as unit:
        sql = unit.communications
        for limit in (1, 2, 20):
            assert fake.context_self_addresses(principal, limit=limit) == (
                sql.context_self_addresses(principal, limit=limit)
            )
            assert fake.non_ascii_participant_addresses(principal, limit=limit) == (
                sql.non_ascii_participant_addresses(principal, limit=limit)
            )
        # Ruling B-3: a verified sent lane exists, so only its sender is the owner.
        owner = sql.context_self_addresses(principal, limit=20)
        assert (owner.addresses, owner.total, owner.verified) == (
            ("owner.b@example.test",),
            1,
            True,
        )
        for kind in ("rfi", "co", "gmp"):
            assert dict(
                fake.list_message_identifiers(principal, ids, kind=kind, version=IDENTIFIER_VERSION)
            ) == dict(
                sql.list_message_identifiers(principal, ids, kind=kind, version=IDENTIFIER_VERSION)
            )


@pytest.mark.parametrize(
    ("lanes", "expected"),
    [
        pytest.param(
            (("sent", "unverified_lane_claim"),),
            (("owner.a@example.test", "owner.b@example.test", "owner.c@example.test"), 3, False),
            id="unverified-only",
        ),
        pytest.param((("inbox", "verified"),), ((), 0, False), id="none"),
    ],
)
def test_the_self_address_tiers_answer_alike(
    migrated_engine: Engine,
    principal: str,
    lanes: tuple[tuple[str, str], ...],
    expected: tuple[tuple[str, ...], int, bool],
) -> None:
    """`self_from_sent_lane_v2` with no verified sent lane: the fallback tier, or none."""
    mail = MailWorld(migrated_engine, principal_id=principal, tag="t")
    ids = [
        mail.message(
            n,
            subject="Plain",
            text="x",
            when=at(17, 10 + n),
            participants=(("from", f"owner.{letter}@example.test"), ("to", "to@example.test")),
            lanes=lanes,
        )
        for n, letter in enumerate("cab", start=1)
    ]
    fake = FakeCommunications(_copy_into_fake(migrated_engine, principal, ids))
    with _unit(migrated_engine) as unit:
        sql = unit.communications
        owner = sql.context_self_addresses(principal, limit=20)
        assert (owner.addresses, owner.total, owner.verified) == expected
        for limit in (1, 2, 20):
            assert fake.context_self_addresses(principal, limit=limit) == (
                sql.context_self_addresses(principal, limit=limit)
            )


def _requests(project_id: str | None) -> list[MeetingCreateRequest]:
    long_text = "RFI 1 " + "z" * IDENTIFIER_SCAN_CHARACTERS
    start = NOW - timedelta(hours=3)
    return [
        MeetingCreateRequest(
            title="Slab pour RFI 5",
            start_at=start,
            end_at=start + timedelta(hours=1),
            timezone_name="UTC",
            series_title="Synthetic parity series",
            description=long_text,
            project_id=project_id,
            attendees=(
                normalize_attendee(email="Straße@Example.TEST", is_organizer=True),
                normalize_attendee(email="b.parity@example.test"),
                normalize_attendee(display_name="Synthetic guest"),
            ),
            notes_markdown="Notes CO 3",
            prep_markdown=long_text,
        ),
        MeetingCreateRequest(title="Bare", start_at=start, timezone_name="UTC"),
    ]


def _aligned(answers: tuple[MeetingContextInput, ...]) -> list[MeetingContextInput]:
    """The answers with their generated ids and instants replaced by positions."""
    out = []
    for index, answer in enumerate(answers):
        out.append(
            replace(
                answer,
                meeting_id=f"m{index}",
                meeting_series_id=None if answer.meeting_series_id is None else "s",
                # Both order by the organizer, then the generated attendee id:
                # aligned here by a content order instead.
                attendees=tuple(
                    attendee.model_copy(update={"attendee_id": "a"})
                    for attendee in sorted(
                        answer.attendees,
                        key=lambda a: (not a.is_organizer, a.email or "", a.display_name or ""),
                    )
                ),
            )
        )
    return out


def test_the_meeting_context_inputs_answer_alike(migrated_engine: Engine, principal: str) -> None:
    fake_world = World()
    fake_unit = FakeUnitOfWork(fake_world)
    fake_ids = [
        APP.create_meeting(fake_unit, principal, request, f"par-{n}", NOW).meeting.meeting_id
        for n, request in enumerate(_requests(None))
    ]
    sql_ids = []
    for n, request in enumerate(_requests(None)):
        with _unit(migrated_engine) as unit:
            sql_ids.append(
                APP.create_meeting(unit, principal, request, f"par-{n}", NOW).meeting.meeting_id
            )
    fake_world.meeting_provider_review_marks[(principal, fake_ids[1])] = (
        MeetingProviderReviewMarkRecord(meeting_id=fake_ids[1], marked_at=NOW)
    )
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(meeting_provider_review_marks).values(
                principal_id=principal, meeting_id=sql_ids[1], marked_at=NOW
            )
        )
    unknown = "mtg_" + "0" * 26
    fake = fake_unit.meetings.read_context_inputs(
        principal, [fake_ids[1], unknown, fake_ids[0], fake_ids[1]]
    )
    with _unit(migrated_engine) as unit:
        sql = unit.meetings.read_context_inputs(
            principal, [sql_ids[1], unknown, sql_ids[0], sql_ids[1]]
        )
    assert len(sql) == 2
    assert _aligned(fake) == _aligned(sql)
    assert sql[1].prep is not None and sql[1].prep.truncated
    assert sql[0].review_marked
