"""WP5-S2: the Meeting context batch input read, `SqlMeetingRepository.read_context_inputs`.

The `database` tier, on a disposable current-head database. Meetings are made
through the real `ApplicationService` (`meetings.create`, `meetings.update`,
`meetings.provider.bind`), then read back in one batch. This module proves:

* **the same core as `meetings.read`** for every Meeting, its active attendees
  in `meetings.read` order, request order kept and duplicates dropped;
* **a foreign or unknown Meeting is absent**, never an error;
* **the provider binding states** (contract section 12.1, ruling D10): a
  single binding, an occurrence binding carrying its bound series (the same
  view `meetings.provider.bind` answers), a `no_provider_event` review mark,
  and none;
* **the identifier-scan heads** (ruling D14): the description, the *current*
  note head and the *current* prep head, each `left(content, 20000)` with the
  longer-than flag;
* **the Project number** of the linked Project;
* **the statement count is fixed** at seven, for 1 Meeting and for 10;
* **every statement reaches the partition** for every table it names.

Every identifier, title, address and number here is synthetic.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, event, insert, text, update
from sqlalchemy.engine import Connection

from my_pa.application.commands import BindMeetingProvider, Command, CreateMeeting, UpdateMeeting
from my_pa.application.meetings import _binding_view
from my_pa.contracts.ports import MeetingContextInput
from my_pa.domain.meeting.context import (
    ENGLISH_STOP_WORDS,
    IDENTIFIER_SCAN_CHARACTERS,
    ContextText,
    title_terms,
)
from my_pa.domain.meeting.model import MeetingNotesMode
from my_pa.infrastructure.persistence.meetings import SqlMeetingRepository
from my_pa.infrastructure.persistence.tables import meeting_provider_review_marks, projects
from tests.contract.test_meeting_mcp import Partition, _insert_partition
from tests.database.test_task_record_events import Runtime

pytestmark = pytest.mark.database

START: Final = datetime(2026, 12, 1, 15, tzinfo=UTC)
CALENDAR: Final = "cal-synthetic"
SERIES_UID: Final = "uid-ctx-series@example.invalid"
SINGLE_UID: Final = "uid-ctx-single@example.invalid"
PROJECT_NUMBER: Final = "SYN-0001"
#: The seven statements of the batch (design section 3.10, rows 1-7).
STATEMENTS: Final = 7


@dataclass
class Scene:
    runtime: Runtime
    mine: Partition
    theirs: Partition

    @property
    def principal_id(self) -> str:
        return self.mine.principal.principal_id

    @property
    def engine(self) -> Engine:
        return self.runtime.work_engine

    def ok(self, command: Command, *, principal_id: str | None = None) -> dict[str, Any]:
        return self.runtime.ok(command, principal_id=principal_id or self.principal_id)

    def create(
        self, key: str, *, principal_id: str | None = None, **fields: object
    ) -> dict[str, Any]:
        values: dict[str, object] = {
            "title": "Synthetic coordination",
            "start_at": START,
            "timezone_name": "UTC",
            "idempotency_key": key,
        }
        values.update(fields)
        return self.ok(CreateMeeting(**values), principal_id=principal_id)["meeting"]  # type: ignore[arg-type]

    def read(
        self, meeting_ids: list[str], *, principal_id: str | None = None
    ) -> tuple[MeetingContextInput, ...]:
        with self.engine.connect() as connection:
            return SqlMeetingRepository(connection).read_context_inputs(
                principal_id or self.principal_id, meeting_ids
            )


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
                .values(project_number=PROJECT_NUMBER)
            )
        yield Scene(runtime=runtime, mine=mine, theirs=theirs)
    finally:
        runtime.close()


def _attendees(scene: Scene) -> tuple[dict[str, object], ...]:
    return (
        {
            "entity_id": scene.mine.person_ids[0],
            "email": "Synthetic.Organizer@Example.TEST",
            "display_name": "Synthetic Organizer",
            "is_organizer": True,
            "response_status": "accepted",
        },
        {"email": "guest.one@example.test"},
        {"display_name": "Synthetic Guest Without Address"},
    )


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


# ---- the core --------------------------------------------------------------------


def test_the_batch_returns_the_same_core_as_meetings_read(scene: Scene) -> None:
    first = scene.create(
        "ctx-first",
        series_title="Synthetic series",
        description="Description naming RFI 7",
        project_id=scene.mine.project_id,
        attendees=_attendees(scene),
        notes_markdown="Notes naming CO 5",
        prep_markdown="Prep naming Submittal 033000-01",
        end_at=START + timedelta(hours=1),
    )
    second = scene.create("ctx-second", title="Standalone synthetic")
    third = scene.create("ctx-third", meeting_series_id=first["meeting_series_id"])
    wanted = [third["meeting_id"], first["meeting_id"], third["meeting_id"], second["meeting_id"]]
    answers = scene.read(wanted)
    assert [answer.meeting_id for answer in answers] == [
        third["meeting_id"],
        first["meeting_id"],
        second["meeting_id"],
    ]
    with scene.engine.connect() as connection:
        repository = SqlMeetingRepository(connection)
        for answer in answers:
            view = repository.read_meeting(scene.principal_id, answer.meeting_id)
            assert view is not None
            assert (
                answer.meeting_series_id,
                answer.series_title,
                answer.title,
                answer.status,
                answer.start_at,
                answer.end_at,
                answer.timezone_name,
                answer.project_id,
                answer.version,
                answer.attendees,
            ) == (
                view.meeting_series_id,
                view.series_title,
                view.title,
                view.status,
                view.start_at,
                view.end_at,
                view.timezone_name,
                view.project_id,
                view.version,
                view.attendees,
            )
    by_id = {answer.meeting_id: answer for answer in answers}
    full = by_id[first["meeting_id"]]
    assert [attendee.email for attendee in full.attendees].count(None) == 1
    assert "synthetic.organizer@example.test" in {a.email for a in full.attendees}
    assert full.description == ContextText("Description naming RFI 7")
    assert full.note == ContextText("Notes naming CO 5")
    assert full.prep == ContextText("Prep naming Submittal 033000-01")
    assert full.project_number == PROJECT_NUMBER
    bare = by_id[second["meeting_id"]]
    assert (bare.attendees, bare.description, bare.note, bare.prep) == ((), None, None, None)
    assert (bare.project_id, bare.project_number, bare.series_title) == (None, None, None)
    assert (bare.provider_binding, bare.review_marked) == (None, False)


def test_a_project_without_a_number_answers_none(scene: Scene) -> None:
    meeting = scene.create("ctx-project", project_id=scene.mine.project_id)
    with scene.engine.begin() as connection:
        connection.execute(
            update(projects)
            .where(projects.c.project_id == scene.mine.project_id)
            .values(project_number=None)
        )
    (answer,) = scene.read([meeting["meeting_id"]])
    assert (answer.project_id, answer.project_number) == (scene.mine.project_id, None)


def test_a_foreign_or_unknown_meeting_is_absent(scene: Scene) -> None:
    mine = scene.create("ctx-mine")
    theirs = scene.create(
        "ctx-theirs",
        principal_id=scene.theirs.principal.principal_id,
        attendees=({"email": "foreign@example.test"},),
        notes_markdown="Foreign notes RFI 9",
    )
    unknown = "mtg_" + "0" * 26
    answers = scene.read([theirs["meeting_id"], unknown, mine["meeting_id"]])
    assert [answer.meeting_id for answer in answers] == [mine["meeting_id"]]
    assert scene.read([theirs["meeting_id"]]) == ()
    assert scene.read([]) == ()
    (own,) = scene.read([theirs["meeting_id"]], principal_id=scene.theirs.principal.principal_id)
    assert own.note == ContextText("Foreign notes RFI 9")


# ---- the provider binding states -----------------------------------------------


def _bind(scene: Scene, meeting: dict[str, Any], key: str, *, occurrence: bool) -> None:
    values: dict[str, object] = {
        "action": "bind",
        "meeting_id": meeting["meeting_id"],
        "expected_version": meeting["version"],
        "idempotency_key": key,
        "calendar_ref": CALENDAR,
        "provider_event_id": f"evt-{key}",
        "provider_event_id_format": "mutable",
    }
    if occurrence:
        values.update(
            ical_uid=SERIES_UID,
            occurrence_original_start_utc=datetime(2026, 12, 2, 14, tzinfo=UTC),
            series_ical_uid=SERIES_UID,
        )
    else:
        values.update(ical_uid=SINGLE_UID, occurrence_original_start_utc=None)
    scene.ok(BindMeetingProvider(**values))  # type: ignore[arg-type]


def test_the_binding_states_bound_marked_and_none(scene: Scene) -> None:
    single = scene.create("ctx-single")
    occurrence = scene.create("ctx-occurrence", series_title="Synthetic bound series")
    marked = scene.create("ctx-marked")
    plain = scene.create("ctx-plain")
    _bind(scene, single, "bind-single", occurrence=False)
    _bind(scene, occurrence, "bind-occurrence", occurrence=True)
    with scene.engine.begin() as connection:
        connection.execute(
            insert(meeting_provider_review_marks).values(
                principal_id=scene.principal_id, meeting_id=marked["meeting_id"], marked_at=START
            )
        )
    ids = [m["meeting_id"] for m in (single, occurrence, marked, plain)]
    answers = {answer.meeting_id: answer for answer in scene.read(ids)}
    with scene.engine.connect() as connection:
        repository = SqlMeetingRepository(connection)
        for meeting_id in ids:
            assert answers[meeting_id].provider_binding == _binding_view(
                repository, scene.principal_id, meeting_id
            )
    bound = answers[occurrence["meeting_id"]].provider_binding
    assert bound is not None
    assert bound.meeting_series_id == occurrence["meeting_series_id"]
    assert bound.provider_state.value == "active"
    single_binding = answers[single["meeting_id"]].provider_binding
    assert single_binding is not None and single_binding.meeting_series_id is None
    assert answers[marked["meeting_id"]].provider_binding is None
    assert [answers[i].review_marked for i in ids] == [False, False, True, False]
    assert answers[plain["meeting_id"]].provider_binding is None


# ---- the identifier-scan heads --------------------------------------------------


def test_the_heads_are_current_and_capped_at_twenty_thousand(scene: Scene) -> None:
    long_text = "RFI 1 " + "x" * IDENTIFIER_SCAN_CHARACTERS
    meeting = scene.create(
        "ctx-heads",
        description=long_text,
        notes_markdown="First note RFI 2",
        prep_markdown="First prep RFI 3",
    )
    updated = scene.ok(
        UpdateMeeting(
            meeting_id=meeting["meeting_id"],
            expected_version=meeting["version"],
            idempotency_key="ctx-heads-update",
            notes_mode=MeetingNotesMode.REPLACE,
            notes_markdown=long_text,
            prep_markdown="Second prep RFI 4",
        )
    )["meeting"]
    (answer,) = scene.read([meeting["meeting_id"]])
    assert answer.version == updated["version"]
    capped = ContextText(long_text[:IDENTIFIER_SCAN_CHARACTERS], truncated=True)
    assert answer.description == capped
    assert answer.note == capped
    assert answer.prep == ContextText("Second prep RFI 4")
    exact = "y" * IDENTIFIER_SCAN_CHARACTERS
    second = scene.create("ctx-exact", description=exact)
    (at_cap,) = scene.read([second["meeting_id"]])
    assert at_cap.description == ContextText(exact, truncated=False)


# ---- statements ----------------------------------------------------------------


def test_one_meeting_costs_the_same_seven_statements_as_ten(scene: Scene) -> None:
    created = [
        scene.create(
            f"ctx-count-{n}",
            project_id=scene.mine.project_id,
            attendees=({"email": f"guest.{n}@example.test"},),
            notes_markdown=f"Note {n}",
            prep_markdown=f"Prep {n}",
        )
        for n in range(10)
    ]
    ids = [meeting["meeting_id"] for meeting in created]
    with _statements(scene.engine) as one:
        assert len(scene.read(ids[:1])) == 1
    with _statements(scene.engine) as ten:
        assert len(scene.read(ids)) == 10
    assert len(one) == len(ten) == STATEMENTS


_TABLE: Final = re.compile(r"(?:FROM|JOIN) knowledge\.(\w+)(?: AS (\w+))?")


def test_every_statement_reaches_the_partition_for_every_table_it_names(scene: Scene) -> None:
    """Each table or alias a statement names carries its `principal_id` predicate.

    The prove-red anchor of mutant m6: a statement built without the partition
    guard names a table whose `principal_id` it never constrains.
    """
    meeting = scene.create(
        "ctx-guard",
        series_title="Synthetic guard series",
        project_id=scene.mine.project_id,
        attendees=({"email": "guard@example.test"},),
        notes_markdown="Guard note",
        prep_markdown="Guard prep",
    )
    _bind(scene, meeting, "bind-guard", occurrence=True)
    with _statements(scene.engine) as seen:
        scene.read([meeting["meeting_id"]])
    assert len(seen) == STATEMENTS
    for statement, parameters in seen:
        named = _TABLE.findall(statement)
        assert named, statement
        for table, alias in named:
            reference = alias or f"knowledge.{table}"
            assert re.search(rf"(?<![\w.]){re.escape(reference)}\.principal_id\b", statement), (
                reference,
                statement,
            )
        # The outer table is bound to this Principal, never only correlated.
        assert scene.principal_id in parameters.values(), statement
        assert re.search(r"\.principal_id = %\(\w+\)s", statement), statement


# ---- the title-terms stop words, against the server -----------------------------


def test_every_stop_word_is_one_the_server_drops_and_no_term_is(scene: Scene) -> None:
    """`ENGLISH_STOP_WORDS` is exactly what `to_tsvector('english', ...)` drops.

    So a title word `title_terms` removes as a stop word is one the server would
    never have matched, and every word it keeps survives as a lexeme.
    """
    words = sorted(ENGLISH_STOP_WORDS)
    kept = list(title_terms("OAC coordination curtain wall mockup pour sequence crane"))
    with scene.engine.connect() as connection:
        dropped = connection.execute(
            text(
                "SELECT w FROM unnest(CAST(:words AS text[])) AS w "
                "WHERE to_tsvector('english', w) = ''::tsvector"
            ),
            {"words": words + kept},
        ).scalars()
        assert sorted(dropped) == words
