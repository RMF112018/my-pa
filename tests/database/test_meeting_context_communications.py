"""WP5-S3: the communications section of `meetings.context.read` on PostgreSQL.

The `database` tier, on a disposable current-head clone, through
`MeetingContextReads` over the real unit of work: Meetings are made through the
real `ApplicationService`, communications rows through the real repositories
(`tests/database/communications_search_world.py`). Proved here (WP5 design
sections 3.4 and 3.8-3.11; rulings D3-D6, D8, D11, D13, A-3):

* the union: participant OR identifier OR project number OR title terms,
  one row per message with every reason in `matched_by`, the tiers 1-4;
* the owner's derived address is never a participant criterion; only
  verified sent lanes derive it, an unverified one only when there is no
  verified one (`derived_unverified`, `self_unverified`), and without a sent
  lane every Meeting says `self_unknown` (ruling B-3, `self_from_sent_lane_v2`);
* the C9 bridge: a stored `lower` spelling matches its attendee's casefold key
  (run on the C and the en_US.UTF-8 clusters alike);
* bare `gmp` is never an input; the Project number is one exact term;
  `english` stems each title term (`meetings` matches `meeting`);
* the D5 total order (overlap before title rank), the collapse by
  conversation with `conversation_hits`, the per-Meeting limit with
  `matched_total` and `truncated`;
* the window, inclusive at both ends and clipped at the read instant;
* the snippet: a plain 300-character prefix, and `NULL` from the statement for
  a withheld or truncated body even with the table CHECK dropped;
* coverage `complete`, `partial` and `none` with the gaps, per Meeting;
* the `no_inputs` state and the `missing[]` codes; foreign rows never read;
* the statement count: 1 Meeting costs exactly what 10 cost;
* every statement reaches the partition for every table it names.

Every identifier, subject, text, address and number here is synthetic.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, event, text, update
from sqlalchemy.engine import Connection

from my_pa.application.commands import Command, CreateMeeting
from my_pa.application.meeting_context import (
    MeetingContext,
    MeetingContextAnswer,
    MeetingContextReads,
    MeetingContextRequest,
    context_payload,
)
from my_pa.contracts.ports import MeetingContextCandidateInput, MeetingContextCandidateQuery
from my_pa.domain.communications.identifiers import IDENTIFIER_VERSION
from my_pa.infrastructure.persistence.communications import SqlCommunicationsRepository
from my_pa.infrastructure.persistence.tables import projects
from tests.contract.test_meeting_mcp import Partition, _insert_partition
from tests.database.communications_search_world import NOW, World, at, unit_of_work
from tests.database.test_task_record_events import Runtime

pytestmark = pytest.mark.database

A: Final = "alpha.ctx@example.test"
B: Final = "bravo.ctx@example.test"
C: Final = "charlie.ctx@example.test"
SELF: Final = "owner.ctx@example.test"
NUMBER: Final = "SYN-4417"
#: A Meeting three hours before the read instant: its window is days 7-21, 09:00.
START: Final = NOW - timedelta(hours=3)


@dataclass
class Scene:
    runtime: Runtime
    mine: Partition
    theirs: Partition
    mail: World

    @property
    def principal_id(self) -> str:
        return self.mine.principal.principal_id

    @property
    def engine(self) -> Engine:
        return self.runtime.work_engine

    def ok(self, command: Command, *, principal_id: str | None = None) -> dict[str, Any]:
        return self.runtime.ok(command, principal_id=principal_id or self.principal_id)

    def meeting(
        self,
        key: str,
        *,
        title: str = "Coordination",
        emails: tuple[str, ...] = (),
        principal_id: str | None = None,
        **fields: object,
    ) -> str:
        values: dict[str, object] = {
            "title": title,
            "start_at": START,
            "timezone_name": "UTC",
            "idempotency_key": key,
            "attendees": tuple({"email": email} for email in emails),
        }
        values.update(fields)
        created = self.ok(CreateMeeting(**values), principal_id=principal_id)  # type: ignore[arg-type]
        return str(created["meeting"]["meeting_id"])

    def reads(self) -> MeetingContextReads:
        return MeetingContextReads(unit_of_work=unit_of_work(self.engine), clock=lambda: NOW)

    def read(self, ids: list[str], **fields: object) -> MeetingContextAnswer:
        return self.reads().read(
            self.principal_id,
            MeetingContextRequest(meeting_ids=ids, **fields),  # type: ignore[arg-type]
        )

    def one(self, meeting_id: str, **fields: object) -> MeetingContext:
        (context,) = self.read([meeting_id], **fields).meetings
        return context


@pytest.fixture
def scene(disposable_database: str) -> Iterator[Scene]:
    runtime = Runtime(disposable_database)
    try:
        with runtime.work_engine.begin() as connection:
            mine = _insert_partition(connection)
            theirs = _insert_partition(connection)
            connection.execute(
                update(projects)
                .where(projects.c.project_id == mine.project_id)
                .values(project_number=NUMBER)
            )
        mail = World(runtime.work_engine, principal_id=mine.principal.principal_id, tag="m")
        # The owner's address: the `from` of a message observed in the sent lane.
        mail.message(
            900,
            subject="Owner note",
            text="owner sent text",
            when=at(10, 8),
            participants=(("from", SELF), ("to", C)),
            lanes=(("sent", "verified"),),
        )
        yield Scene(runtime=runtime, mine=mine, theirs=theirs, mail=mail)
    finally:
        runtime.close()


def _ids(context: MeetingContext) -> list[str]:
    return [message.message_id for message in context.communications.messages]


@contextmanager
def _statements(engine: Engine) -> Iterator[list[tuple[str, Any]]]:
    seen: list[tuple[str, Any]] = []

    def record(
        _conn: Connection, _cursor: object, statement: str, parameters: object, *_: object
    ) -> None:
        seen.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


# ---- the union, the reasons and the tiers ------------------------------------------


def test_the_union_is_deduplicated_with_every_reason_and_tiered(scene: Scene) -> None:
    w = scene.mail
    both = w.message(
        1,
        subject="Slab pour RFI 174",
        text="Per RFI 174 the slab pour moves.",
        when=at(17, 10),
        participants=(("from", A), ("to", B)),
    )
    identifier = w.message(2, subject="Question", text="RFI 174 answered.", when=at(17, 11))
    participant = w.message(
        3, subject="Lunch", text="Unrelated.", when=at(17, 12), participants=(("from", A),)
    )
    title = w.message(4, subject="Slab", text="The slab finish.", when=at(17, 13))
    w.message(
        5,
        subject="Old RFI 174",
        text="RFI 174 long ago.",
        when=at(6, 10),
        participants=(("from", A),),
    )
    w.message(6, subject="Noise", text="Nothing relevant.", when=at(17, 14))
    foreign = World(scene.engine, principal_id=scene.theirs.principal.principal_id, tag="f")
    foreign.message(
        1, subject="Slab RFI 174", text="RFI 174 slab", when=at(17, 10), participants=(("from", A),)
    )
    meeting = scene.meeting("union", title="Slab pour", emails=(A, B), description="See RFI 174")
    context = scene.one(meeting)
    section = context.communications
    assert _ids(context) == [both, identifier, participant, title]
    assert [m.tier for m in section.messages] == [1, 2, 3, 4]
    reasons = {m.message_id: [r.value for r in m.matched_by] for m in section.messages}
    assert reasons == {
        both: ["participants", "identifiers", "title_terms"],
        identifier: ["identifiers"],
        participant: ["participants"],
        title: ["title_terms"],
    }
    first = section.messages[0]
    assert first.participant_overlap == 2
    assert first.matched_identifiers == ("rfi:174",)
    attendees = {a.email: a.attendee_id for a in context.attendees}
    assert set(first.matched_attendee_ids) == {attendees[A], attendees[B]}
    assert first.rank > 0 and section.messages[1].rank == 0
    assert (section.state.value, section.matched_total, section.truncated) == ("ok", 4, False)
    assert [i.identifier for i in section.inputs.identifiers] == ["rfi:174"]
    assert section.inputs.identifiers[0].sources == ("description",)
    assert first.lanes and first.lanes[0].folder_role == "inbox"


# ---- the owner's address (ruling D3) -------------------------------------------------


def test_the_owners_address_is_never_a_participant_criterion(scene: Scene) -> None:
    owners = scene.mail.message(
        1, subject="Lunch", text="Plain.", when=at(17, 10), participants=(("from", SELF), ("to", C))
    )
    other = scene.mail.message(
        2, subject="Other", text="Plain.", when=at(17, 11), participants=(("from", A),)
    )
    meeting = scene.meeting("self", emails=(SELF, A))
    answer = scene.read([meeting])
    (context,) = answer.meetings
    assert _ids(context) == [other]
    assert owners not in _ids(context)
    assert {a.email: a.is_self for a in context.attendees} == {SELF: True, A: False}
    inputs = context.communications.inputs
    assert (inputs.attendee_keys, inputs.self_attendees) == (1, 1)
    assert (answer.self_addresses.state.value, answer.self_addresses.count) == ("derived", 1)
    assert "self_unknown" not in [code.value for code in context.communications.missing]
    only_self = scene.one(scene.meeting("self-only", emails=(SELF,)))
    assert "only_self_attendees" in [code.value for code in only_self.communications.missing]
    assert only_self.communications.messages == ()


def test_without_a_sent_lane_the_owner_is_unknown_and_nothing_is_excluded(
    disposable_database: str,
) -> None:
    runtime = Runtime(disposable_database)
    try:
        with runtime.work_engine.begin() as connection:
            mine = _insert_partition(connection)
            theirs = _insert_partition(connection)
        mail = World(runtime.work_engine, principal_id=mine.principal.principal_id, tag="u")
        scene = Scene(runtime=runtime, mine=mine, theirs=theirs, mail=mail)
        message = mail.message(
            1, subject="Lunch", text="Plain.", when=at(17, 10), participants=(("from", SELF),)
        )
        answer = scene.read([scene.meeting("unknown", emails=(SELF,)), scene.meeting("bare")])
        assert (answer.self_addresses.state.value, answer.self_addresses.count) == ("unknown", 0)
        first, second = answer.meetings
        assert _ids(first) == [message]
        assert all(
            "self_unknown" in [code.value for code in context.communications.missing]
            for context in (first, second)
        )
    finally:
        runtime.close()


def _bare_scene(disposable_database: str, tag: str) -> Scene:
    runtime = Runtime(disposable_database)
    with runtime.work_engine.begin() as connection:
        mine = _insert_partition(connection)
        theirs = _insert_partition(connection)
    mail = World(runtime.work_engine, principal_id=mine.principal.principal_id, tag=tag)
    return Scene(runtime=runtime, mine=mine, theirs=theirs, mail=mail)


def test_an_unverified_sender_is_not_self_when_a_verified_lane_exists(scene: Scene) -> None:
    """Ruling B-3: an unverified sent lane can carry a non-owner sender; it is not excluded."""
    claimed = scene.mail.message(
        1,
        subject="Lunch",
        text="Plain.",
        when=at(17, 10),
        participants=(("from", A), ("to", C)),
        lanes=(("sent", "unverified_lane_claim"),),
    )
    answer = scene.read([scene.meeting("verified-tier", emails=(A, SELF))])
    (context,) = answer.meetings
    assert {a.email: a.is_self for a in context.attendees} == {A: False, SELF: True}
    assert _ids(context) == [claimed]
    assert (answer.self_addresses.state.value, answer.self_addresses.count) == ("derived", 1)
    missing = [code.value for code in context.communications.missing]
    assert "self_unverified" not in missing and "self_unknown" not in missing


def test_only_unverified_sent_lanes_derive_the_owner_unverified(disposable_database: str) -> None:
    scene = _bare_scene(disposable_database, "v")
    try:
        for n, sender in enumerate((SELF, A), start=1):
            scene.mail.message(
                n,
                subject="Sent",
                text="Plain.",
                when=at(17, 10 + n),
                participants=(("from", sender), ("to", C)),
                lanes=(("inbox", "verified"), ("sent", "unverified_lane_claim")),
            )
        other = scene.mail.message(
            3, subject="Other", text="Plain.", when=at(17, 13), participants=(("from", B),)
        )
        answer = scene.read([scene.meeting("fallback", emails=(SELF, B)), scene.meeting("bare")])
        assert (answer.self_addresses.state.value, answer.self_addresses.count) == (
            "derived_unverified",
            2,
        )
        assert context_payload(answer)["self_addresses"] == {
            "state": "derived_unverified",
            "rule": "self_from_sent_lane_v2",
            "count": 2,
            "used": 2,
        }
        first, second = answer.meetings
        assert {a.email: a.is_self for a in first.attendees} == {SELF: True, B: False}
        assert _ids(first) == [other]
        for context in (first, second):
            missing = [code.value for code in context.communications.missing]
            assert "self_unverified" in missing and "self_unknown" not in missing
            assert missing[-1] == "self_unverified"
    finally:
        scene.runtime.close()


# ---- the C9 bridge (ruling D11) ------------------------------------------------------

#: `raw` as an attendee writes it; the stored participant is `raw.strip().lower()`,
#: the attendee key `casefold`: they differ in each case, and the bridge joins them.
C9_CASES: Final = (
    "straße.ctx@example.test",
    "STRAẞE.ctx@example.test",
    "ΟΔΟΣ@example.test",
    "ﬁnance.ctx@example.test",
    "ꭰꭱ.ctx@example.test",
)


@pytest.mark.parametrize("raw", C9_CASES)
def test_the_bridge_matches_a_lower_spelling_to_its_casefold_key(scene: Scene, raw: str) -> None:
    stored = raw.strip().lower()
    assert stored != raw.casefold()
    message = scene.mail.message(
        1, subject="Plain", text="Plain.", when=at(17, 10), participants=(("from", stored),)
    )
    meeting = scene.meeting("c9", emails=(raw,))
    context = scene.one(meeting)
    assert context.attendees[0].email == raw.casefold()
    assert _ids(context) == [message]
    assert context.communications.messages[0].matched_attendee_ids == (
        context.attendees[0].attendee_id,
    )
    with scene.engine.connect() as connection:
        bridged = SqlCommunicationsRepository(connection).non_ascii_participant_addresses(
            scene.principal_id, limit=1000
        )
    assert bridged == (stored,)


# ---- identifiers, the Project number, title terms ----------------------------------


def test_bare_gmp_is_never_an_input(scene: Scene) -> None:
    scene.mail.message(1, subject="GMP", text="The GMP is final.", when=at(17, 10))
    context = scene.one(scene.meeting("gmp", title="Coordination", description="GMP and FPL"))
    section = context.communications
    assert section.inputs.identifiers == ()
    assert section.messages == ()


def test_the_project_number_is_one_exact_term(scene: Scene) -> None:
    exact = scene.mail.message(1, subject="Job", text=f"Job {NUMBER} invoice.", when=at(17, 10))
    scene.mail.message(2, subject="Job", text="Job SYN 4417 invoice.", when=at(17, 11))
    scene.mail.message(3, subject="Job", text="Job SYN-44170 invoice.", when=at(17, 12))
    context = scene.one(scene.meeting("number", project_id=scene.mine.project_id))
    section = context.communications
    assert _ids(context) == [exact]
    assert [r.value for r in section.messages[0].matched_by] == ["project_number"]
    assert section.messages[0].tier == 2
    assert section.inputs.project_number.value == "used"


def test_english_stems_each_title_term(scene: Scene) -> None:
    """Ruling A-3: `meetings` matches `meeting`, at the statement and end to end."""
    singular = scene.mail.message(1, subject="Notes", text="After the meeting.", when=at(17, 10))
    inspection = scene.mail.message(
        2, subject="Notes", text="The inspection passed.", when=at(17, 11)
    )
    with scene.engine.connect() as connection:
        rows = SqlCommunicationsRepository(connection).context_candidates(
            scene.principal_id,
            MeetingContextCandidateQuery(
                meetings=(
                    MeetingContextCandidateInput(
                        ordinal=0,
                        window_start=at(7),
                        window_end=at(21),
                        addresses=(),
                        identifiers=(),
                        title_terms=("meetings",),
                        project_number=None,
                    ),
                ),
                identifier_version=IDENTIFIER_VERSION,
                limit=15,
            ),
        )
    assert [row.message_id for row in rows] == [singular]
    context = scene.one(scene.meeting("stem", title="Inspections"))
    assert _ids(context) == [inspection]


#: The on-the-fly `simple` document as EXPLAIN prints it (`'simple'::regconfig`,
#: or the bound `('simple'::cstring)::regconfig`).
_SIMPLE_TSVECTOR: Final = re.compile(r"to_tsvector\(\(?'simple'")


def _evaluations(plan: dict[str, Any], marker: re.Pattern[str]) -> int:
    """Rows a plan evaluated `marker` on: loops x (rows kept + rows removed), summed."""
    total = 0
    for key, removed in (
        ("Filter", "Rows Removed by Filter"),
        ("Join Filter", "Rows Removed by Join Filter"),
    ):
        if marker.search(plan.get(key, "")):
            total += plan["Actual Loops"] * (plan["Actual Rows"] + plan.get(removed, 0))
    for child in plan.get("Plans", ()):
        total += _evaluations(child, marker)
    return total


def test_the_simple_text_is_built_once_per_message_not_per_meeting(scene: Scene) -> None:
    """WP5-R1 F-1: the Project number's `simple` text never per (Meeting, message).

    Ten Meetings with the same number and title terms over one window: the
    on-the-fly `to_tsvector('simple', ...)` is evaluated at most once per
    message of the partition, which a per-pair rebuild exceeds tenfold.
    """
    for n in range(1, 31):
        scene.mail.message(
            n,
            subject="Slab pour",
            text=f"Slab pour {NUMBER} note {n}" if n % 3 == 0 else f"Slab pour note {n}",
            when=at(10 + n % 10, 10),
        )
    query = MeetingContextCandidateQuery(
        meetings=tuple(
            MeetingContextCandidateInput(
                ordinal=k,
                window_start=at(7),
                window_end=at(21),
                addresses=((A, A),),
                identifiers=(("rfi", str(k)),),
                title_terms=("slab",),
                project_number=NUMBER,
            )
            for k in range(10)
        ),
        identifier_version=IDENTIFIER_VERSION,
        limit=15,
    )
    with scene.engine.connect() as connection:
        repository = SqlCommunicationsRepository(connection)
        with _statements(scene.engine) as seen:
            rows = repository.context_candidates(scene.principal_id, query)
        assert len({row.ordinal for row in rows if row.project_number_hit}) == 10
        ((statement, parameters),) = seen
        (plan,) = connection.exec_driver_sql(
            "EXPLAIN (ANALYZE, FORMAT JSON) " + statement, parameters
        ).scalar_one()
    evaluated = _evaluations(plan["Plan"], _SIMPLE_TSVECTOR)
    # The fixture's message and these 30: every message of the partition.
    assert 0 < evaluated <= 31, evaluated


# ---- batch isolation (WP5-R1 F-2) ------------------------------------------------------

#: Per Meeting of the batch: its attendee, identifier, title term and Project number.
_ISOLATED: Final = (
    ("p0.iso@example.test", ("rfi", "1001"), "girder", "SYN-1001"),
    ("p1.iso@example.test", ("rfi", "2002"), "plinth", "SYN-2002"),
    ("p2.iso@example.test", ("rfi", "3003"), "louver", "SYN-3003"),
)


def _isolated_input(ordinal: int, k: int, *, days: tuple[int, int]) -> MeetingContextCandidateInput:
    address, identifier, term, number = _ISOLATED[k]
    return MeetingContextCandidateInput(
        ordinal=ordinal,
        window_start=at(days[0]),
        window_end=at(days[1]),
        addresses=((address, address),),
        identifiers=(identifier,),
        title_terms=(term,),
        project_number=number,
    )


def test_no_meeting_of_a_batch_reaches_another_meetings_matches(scene: Scene) -> None:
    """Every criterion matches only its own Meeting's messages, in one batch.

    Meetings 0-2 share a window, each with its own attendee, identifier, title
    term and number, and every message matches exactly one criterion of
    exactly one of them. Meeting 3 asks as Meeting 0 does, over an earlier,
    disjoint window, which holds one message only it may see.
    """
    w = scene.mail
    expected: dict[int, dict[str, list[str]]] = {0: {}, 1: {}, 2: {}, 3: {}}
    n = 0
    for k, (address, (_, value), term, number) in enumerate(_ISOLATED):
        for reason, fields in (
            ("participants", {"text": "Plain.", "participants": (("from", address),)}),
            ("identifiers", {"text": f"Per RFI {value}."}),
            ("title_terms", {"text": f"The {term} detail."}),
            ("project_number", {"text": f"Job {number} invoice."}),
        ):
            n += 1
            message = w.message(n, subject="Note", when=at(12 + k, n % 24), **fields)  # type: ignore[arg-type]
            expected[k][message] = [reason]
    early = w.message(
        99,
        subject="Note",
        text="Per RFI 1001, the girder, job SYN-1001.",
        when=at(3, 10),
        participants=(("from", _ISOLATED[0][0]),),
    )
    expected[3][early] = ["participants", "identifiers", "project_number", "title_terms"]
    query = MeetingContextCandidateQuery(
        meetings=(
            _isolated_input(0, 0, days=(7, 21)),
            _isolated_input(1, 1, days=(7, 21)),
            _isolated_input(2, 2, days=(7, 21)),
            _isolated_input(3, 0, days=(1, 5)),
        ),
        identifier_version=IDENTIFIER_VERSION,
        limit=15,
    )
    with scene.engine.connect() as connection:
        repository = SqlCommunicationsRepository(connection)
        rows = repository.context_candidates(scene.principal_id, query)
        alone = {
            meeting.ordinal: repository.context_candidates(
                scene.principal_id,
                MeetingContextCandidateQuery(
                    meetings=(meeting,), identifier_version=IDENTIFIER_VERSION, limit=15
                ),
            )
            for meeting in query.meetings
        }
    for ordinal, wanted in expected.items():
        mine = [row for row in rows if row.ordinal == ordinal]
        reasons = {
            row.message_id: [
                reason
                for reason, hit in (
                    ("participants", bool(row.matched_keys)),
                    ("identifiers", bool(row.matched_identifiers)),
                    ("project_number", row.project_number_hit),
                    ("title_terms", row.title_hit),
                )
                if hit
            ]
            for row in mine
        }
        assert reasons == wanted, ordinal
        assert {row.matched_total for row in mine} == {len(wanted)}, ordinal
        # The batch answers each Meeting exactly as it is answered alone.
        assert mine == list(alone[ordinal]), ordinal
    # End to end: two Meetings with disjoint attendees and identifiers, in one batch.
    first = scene.meeting("iso-a", emails=(_ISOLATED[0][0],), description="RFI 1001")
    second = scene.meeting("iso-b", emails=(_ISOLATED[1][0],), description="RFI 2002")
    a, b = scene.read([first, second]).meetings
    assert set(_ids(a)) == {
        m for m, r in expected[0].items() if r[0] in ("participants", "identifiers")
    }
    assert set(_ids(b)) == {
        m for m, r in expected[1].items() if r[0] in ("participants", "identifiers")
    }


# ---- order, collapse, limit ------------------------------------------------------------


def test_overlap_orders_before_title_rank(scene: Scene) -> None:
    """Ruling D5: section 14 ranks text first; the context ranks the attendees first."""
    two = scene.mail.message(
        1,
        subject="Plain",
        text="Nothing.",
        when=at(17, 10),
        participants=(("from", A), ("to", B)),
    )
    ranked = scene.mail.message(
        2,
        subject="Curtain wall curtain wall",
        text="Curtain wall mockup curtain wall.",
        when=at(17, 11),
        participants=(("from", A),),
    )
    context = scene.one(scene.meeting("order", title="Curtain wall", emails=(A, B)))
    messages = context.communications.messages
    assert _ids(context) == [two, ranked]
    assert [m.tier for m in messages] == [3, 3]
    assert messages[0].participant_overlap == 2 and messages[0].rank == 0
    assert messages[1].participant_overlap == 1 and messages[1].rank > 0


def test_the_collapse_keeps_each_conversations_best_and_counts_its_hits(scene: Scene) -> None:
    weaker = scene.mail.message(
        1,
        subject="Plain",
        text="Nothing.",
        when=at(18, 10),
        conversation="conv-ctx",
        participants=(("from", A),),
    )
    best = scene.mail.message(
        2,
        subject="RFI 9",
        text="RFI 9 per A.",
        when=at(17, 10),
        conversation="conv-ctx",
        participants=(("from", A),),
    )
    alone = scene.mail.message(
        3, subject="Plain", text="Nothing.", when=at(17, 9), participants=(("from", A),)
    )
    context = scene.one(scene.meeting("collapse", emails=(A,), description="RFI 9"))
    assert _ids(context) == [best, alone]
    assert weaker not in _ids(context)
    assert [m.conversation_hits for m in context.communications.messages] == [2, 1]
    assert context.communications.matched_total == 2


def test_the_per_meeting_limit_with_the_total(scene: Scene) -> None:
    sent = [
        scene.mail.message(
            n, subject="Plain", text="Nothing.", when=at(17, n), participants=(("from", A),)
        )
        for n in range(1, 6)
    ]
    meeting = scene.meeting("limit", emails=(A,))
    other = scene.meeting("limit-other", emails=(A,))
    answer = scene.read([meeting, other], per_meeting_limit=2)
    for context in answer.meetings:
        section = context.communications
        assert _ids(context) == [sent[4], sent[3]]
        assert (section.matched_total, section.truncated) == (5, True)
    full = scene.one(meeting, per_meeting_limit=5)
    assert (full.communications.matched_total, full.communications.truncated) == (5, False)


# ---- the window ----------------------------------------------------------------------


def test_the_window_is_inclusive_at_both_ends(scene: Scene) -> None:
    start, end = START - timedelta(days=2), START
    inside = [
        scene.mail.message(n, subject="Plain", text="x", when=when, participants=(("from", A),))
        for n, when in ((1, start), (2, end))
    ]
    for n, when in ((3, start - timedelta(seconds=1)), (4, end + timedelta(seconds=1))):
        scene.mail.message(n, subject="Plain", text="x", when=when, participants=(("from", A),))
    context = scene.one(scene.meeting("window", emails=(A,)), lookback_days=2)
    assert sorted(_ids(context)) == sorted(inside)
    window = context.communications.window
    assert (window.start, window.end, window.clipped_to_now) == (start, end, False)


def test_an_upcoming_meetings_window_is_clipped_at_now(scene: Scene) -> None:
    before = scene.mail.message(
        1, subject="Plain", text="x", when=NOW - timedelta(hours=1), participants=(("from", A),)
    )
    scene.mail.message(
        2, subject="Plain", text="x", when=NOW + timedelta(hours=1), participants=(("from", A),)
    )
    meeting = scene.meeting("upcoming", emails=(A,), start_at=NOW + timedelta(days=1))
    context = scene.one(meeting)
    assert _ids(context) == [before]
    window = context.communications.window
    assert (window.end, window.clipped_to_now) == (NOW, True)


# ---- the snippet (ruling D8) -----------------------------------------------------------


def test_the_snippet_is_a_plain_prefix_and_never_a_withheld_bodys(scene: Scene) -> None:
    long_text = "RFI 3 " + "y" * 400
    plain = scene.mail.message(1, subject="RFI 3", text=long_text, when=at(17, 10))
    scene.mail.message(
        2, subject="RFI 3 withheld", text=None, when=at(17, 11), body_state="withheld"
    )
    context = scene.one(scene.meeting("snippet", description="RFI 3"))
    snippets = {m.message_id: m.snippet for m in context.communications.messages}
    assert snippets[plain] == long_text[:300]
    assert list(snippets.values()).count(None) == 1


def test_the_statement_refuses_a_withheld_bodys_text_even_without_the_check(
    migrated_engine: Engine,
) -> None:
    """The statement's own guard, reached by dropping the table CHECK on this clone."""
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE knowledge.communication_messages "
                "DROP CONSTRAINT a_withheld_or_truncated_body_has_no_search_text"
            )
        )
    world = World(migrated_engine, tag="w")
    ids = {
        state: world.message(
            n, subject="RFI 4", text="RFI 4 secret text", when=at(17, n), body_state=state
        )
        for n, state in enumerate(("withheld", "truncated", "present"), start=1)
    }
    with migrated_engine.connect() as connection:
        rows = SqlCommunicationsRepository(connection).context_candidates(
            world.principal_id,
            MeetingContextCandidateQuery(
                meetings=(
                    MeetingContextCandidateInput(
                        ordinal=0,
                        window_start=at(7),
                        window_end=at(21),
                        addresses=(),
                        identifiers=(("rfi", "4"),),
                        title_terms=(),
                        project_number=None,
                    ),
                ),
                identifier_version=IDENTIFIER_VERSION,
                limit=15,
            ),
        )
    snippets = {row.message_id: row.snippet for row in rows}
    assert snippets == {
        ids["withheld"]: None,
        ids["truncated"]: None,
        ids["present"]: "RFI 4 secret text",
    }


# ---- coverage per Meeting ----------------------------------------------------------------


def test_coverage_complete_partial_and_none_with_the_gaps(scene: Scene) -> None:
    # The fixture covers day 10; these cover 17, 18 and 20 (19 is a gap).
    for n, day in enumerate((17, 18, 20), start=1):
        scene.mail.message(n, subject="Plain", text="x", when=at(day, 12))
    complete = scene.meeting("cov-complete", start_at=at(18, 18))
    partial = scene.meeting("cov-partial", start_at=at(20, 18))
    none = scene.meeting("cov-none", start_at=at(3, 12))
    answer = scene.read([complete, partial, none], lookback_days=1)
    states = [context.communications.coverage.state for context in answer.meetings]
    assert states == ["complete", "partial", "none"]
    gaps = answer.meetings[1].communications.coverage.gaps
    assert [(gap.start.day, gap.end.day) for gap in gaps] == [(19, 19)]


# ---- states and missing codes -------------------------------------------------------------


def test_no_inputs_and_the_missing_codes(scene: Scene) -> None:
    bare = scene.meeting("bare", title="Weekly sync")
    numbered = scene.meeting("numbered", title="Weekly sync", project_id=scene.mine.project_id)
    answer = scene.read([bare, numbered])
    first, second = answer.meetings
    assert first.communications.state.value == "no_inputs"
    assert [code.value for code in first.communications.missing] == [
        "no_attendee_address",
        "no_identifiers",
        "no_title_terms",
        "no_project",
        "provider_unbound",
    ]
    assert first.communications.messages == ()
    assert first.provider_binding_state.value == "unbound"
    assert second.communications.state.value == "ok"
    with scene.engine.begin() as connection:
        connection.execute(
            update(projects)
            .where(projects.c.project_id == scene.mine.project_id)
            .values(project_number=None)
        )
    absent = scene.one(numbered)
    assert absent.communications.state.value == "no_inputs"
    assert "project_without_number" in [code.value for code in absent.communications.missing]
    assert absent.communications.inputs.project_number.value == "absent"


def test_not_found_lists_foreign_and_unknown_ids_without_failing(scene: Scene) -> None:
    mine = scene.meeting("found", emails=(A,))
    theirs = scene.meeting("foreign", emails=(A,), principal_id=scene.theirs.principal.principal_id)
    unknown = "mtg_" + "0" * 26
    answer = scene.read([theirs, mine, unknown, mine])
    assert [context.meeting.meeting_id for context in answer.meetings] == [mine]
    assert answer.not_found == (theirs, unknown)
    payload = context_payload(answer)
    assert payload["not_found"] == [theirs, unknown]


# ---- statements and the partition -----------------------------------------------------------


def _count_world(scene: Scene) -> list[str]:
    for n in range(1, 21):
        scene.mail.message(
            n,
            subject=f"RFI {n} slab",
            text=f"RFI {n} {NUMBER} slab pour",
            when=at(10 + n % 10, 10),
            conversation=f"conv-{n % 4}",
            participants=(("from", A if n % 2 else B), ("to", C)),
            lanes=(("inbox", "verified"),),
        )
    # The owner is SELF (the fixture's verified sent lane); A and B are not.
    return [
        scene.meeting(
            f"count-{n}",
            title=f"Slab pour RFI {n}",
            emails=(A, B, SELF),
            description=f"RFI {n + 1}",
            project_id=scene.mine.project_id,
        )
        for n in range(10)
    ]


def test_one_meeting_costs_the_same_statements_as_ten(scene: Scene) -> None:
    ids = _count_world(scene)
    with _statements(scene.engine) as one:
        answer = scene.read(ids[:1])
        messages = answer.meetings[0].communications.messages
        assert messages
        # The participant criterion is exercised, not only the text and identifiers.
        assert answer.meetings[0].communications.inputs.attendee_keys == 2
        assert all(m.participant_overlap == 1 for m in messages)
    with _statements(scene.engine) as ten:
        assert len(scene.read(ids).meetings) == 10
    # 7 inputs + 2 versions + 1 + 1 coverage (one source) + self + bridge
    # + the candidate statement + the lanes.
    assert len(one) == len(ten) == 15


_TABLE: Final = re.compile(r"(?:FROM|JOIN) knowledge\.(\w+)(?: AS (\w+))?")


def test_every_statement_reaches_the_partition_for_every_table_it_names(scene: Scene) -> None:
    ids = _count_world(scene)
    with _statements(scene.engine) as seen:
        scene.read(ids[:2])
    assert len(seen) == 15
    for statement, parameters in seen:
        named = _TABLE.findall(statement)
        assert named, statement
        for table, alias in named:
            reference = alias or f"knowledge.{table}"
            assert re.search(rf"(?<![\w.]){re.escape(reference)}\.principal_id\b", statement), (
                reference,
                statement,
            )
        assert scene.principal_id in parameters.values(), statement


def test_the_identifiers_of_messages_by_kind_and_version(scene: Scene) -> None:
    first = scene.mail.message(1, subject="RFI 7", text="RFI 8 and CO 2", when=at(17, 10))
    second = scene.mail.message(2, subject="Plain", text="RFI 7", when=at(17, 11))
    with scene.engine.connect() as connection:
        repository = SqlCommunicationsRepository(connection)
        found = repository.list_message_identifiers(
            scene.principal_id,
            [first, second, "cmsg_" + "0" * 26],
            kind="rfi",
            version=IDENTIFIER_VERSION,
        )
        assert dict(found) == {first: ("7", "8"), second: ("7",)}
        assert (
            repository.list_message_identifiers(
                scene.theirs.principal.principal_id, [first], kind="rfi", version=IDENTIFIER_VERSION
            )
            == {}
        )


def test_the_payload_states_rules_and_never_an_input_address(scene: Scene) -> None:
    scene.mail.message(1, subject="Plain", text="x", when=at(17, 10), participants=(("from", A),))
    payload = context_payload(scene.read([scene.meeting("payload", emails=(A,))]))
    versions = payload["versions"]
    assert isinstance(versions, dict)
    assert (versions["address_rule"], versions["title_terms_rule"]) == (
        "casefold_bridge_v1",
        "meeting_title_terms_v1",
    )
    assert payload["self_addresses"] == {
        "state": "derived",
        "rule": "self_from_sent_lane_v2",
        "count": 1,
        "used": 1,
    }
    assert SELF not in repr(payload)
