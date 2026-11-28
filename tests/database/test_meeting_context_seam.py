"""WP5-R3 F3: the `read_inputs` seam answers exactly what `read` answers, on PostgreSQL.

The `database` tier, on the C and the en_US.UTF-8 clusters alike.
`measure-context` (WP5-S6) times `MeetingContextReads.read_inputs` over
Meetings it is given; the authority run for the D15 maximum target relies on
it running the capability's own code with the bounds it is asked. So, on one
synthetic world (Meetings through the real `ApplicationService`, messages
through the real repositories, the project-report world through the real
WP3P path), for the Meeting inputs `read_context_inputs` reads:

* `context_payload(read(ids, ...))` and `context_payload(read_inputs(inputs,
  ...))` are the same bytes at the defaults (14 days, 15 per Meeting), at the
  maximum (90 days, 50 per Meeting) and at a tight bound, with the
  project-report switch off and on;
* the statements `read` sends are the 7 Meeting input reads, then exactly the
  statements `read_inputs` sends, in order (the CLI's count is `read`'s less 7,
  runbook section 13.3);
* the bounds reach the answer: each bound answers differently from the
  defaults, so a seam that ignored one could not pass.

Every identifier, subject, text, address and number here is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Final

import pytest
from sqlalchemy import update

from my_pa.application.meeting_context import (
    MeetingContextAnswer,
    MeetingContextRequest,
    context_payload,
)
from my_pa.bootstrap.project_reports import project_reports_unit_of_work
from my_pa.infrastructure.persistence.tables import projects
from tests.contract.test_meeting_mcp import _insert_partition
from tests.database.communications_search_world import World, at, unit_of_work
from tests.database.project_report_reads_backstop import Backstop, current_derivations_backstop
from tests.database.test_meeting_context_communications import (
    NUMBER,
    SELF,
    A,
    B,
    C,
    Scene,
    _statements,
)
from tests.database.test_meeting_context_pulse import PulseScene
from tests.database.test_task_record_events import Runtime
from tests.unit.project_report_reads_scene import RFI_PROJECT, ReadsScene
from tests.unit.project_reports_reads_service_cases import NEVER_PROJECT

pytestmark = pytest.mark.database

#: `read_context_inputs`: the Meeting input reads `read` makes and the seam does not.
INPUT_READS: Final = 7
#: (lookback_days, per_meeting_limit): the defaults, the maximum and a tight bound.
BOUNDS: Final = ((14, 15), (90, 50), (3, 1))


@pytest.fixture(autouse=True)
def _current_derivations_backstop() -> Iterator[Backstop]:
    with current_derivations_backstop() as seen:
        yield seen


@pytest.fixture
def scene(disposable_database: str) -> Iterator[PulseScene]:
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
        principal_id = mine.principal.principal_id
        mail = World(runtime.work_engine, principal_id=principal_id, tag="s")
        mail.message(
            900,
            subject="Owner note",
            text="owner sent text",
            when=at(10, 8),
            participants=(("from", SELF), ("to", C)),
            lanes=(("sent", "verified"),),
        )
        base = Scene(runtime=runtime, mine=mine, theirs=theirs, mail=mail)
        built = PulseScene(base=base, reports=None)  # type: ignore[arg-type]
        built.reports = ReadsScene(
            unit=project_reports_unit_of_work(runtime.work_engine),
            add_project=lambda _principal, project_id, number: built.project(project_id, number),
            principal_id=principal_id,
        )
        yield built
    finally:
        runtime.close()


def _bytes(answer: MeetingContextAnswer) -> bytes:
    return json.dumps(context_payload(answer), ensure_ascii=False, sort_keys=True).encode()


def _world(scene: PulseScene) -> list[str]:
    """Messages inside 3, 14 and 90 days of the Meetings, and 5 Meetings of every shape."""
    scene.populate()
    w = scene.base.mail
    # Inside 3 days of the Meetings' start (the 21st, 09:00).
    w.message(
        1,
        subject="Slab pour RFI 176",
        text="RFI 176 and RFI 175 for the slab.",
        when=at(19, 10),
        participants=(("from", A), ("to", B)),
    )
    w.message(2, subject="Slab question", text="RFI 176 again.", when=at(20, 11))
    # Inside 14 days, outside 3.
    w.message(
        3,
        subject="Slab pour",
        text=f"Project {NUMBER} and RFI 174.",
        when=at(12, 9),
        participants=(("from", B), ("to", A)),
    )
    w.message(4, subject="Slab", text="RFI 9 is elsewhere.", when=at(10, 13))
    # Outside 14 days, inside 90 (October).
    for n in range(5, 25):
        w.message(
            n,
            subject=f"Slab pour {n}",
            text=f"RFI 174 and RFI {170 + n % 3}, slab pour.",
            when=at(1, 10) - (n * (at(2) - at(1))),
            participants=(("from", A if n % 2 else C), ("to", B)),
        )
    base = scene.base
    return [
        base.meeting("rfis", title="Slab pour RFI 174", emails=(A,), project_id=RFI_PROJECT[1]),
        base.meeting(
            "unbound",
            title="Slab pour",
            emails=(A, B, SELF),
            project_id=base.mine.project_id,
            description="See RFI 176.",
        ),
        base.meeting("never", title="Slab question", project_id=NEVER_PROJECT[1]),
        base.meeting("plain", title="Slab", emails=(B,)),
        base.meeting("nothing", title="The"),
    ]


def test_read_inputs_answers_read_byte_for_byte_statement_for_statement(
    scene: PulseScene,
) -> None:
    ids = _world(scene)
    principal_id = scene.principal_id
    with unit_of_work(scene.engine)() as unit:
        inputs = unit.meetings.read_context_inputs(principal_id, ids)
    assert [meeting.meeting_id for meeting in inputs] == ids
    for pulse in (False, True):
        reads = scene.reads(pulse=pulse)
        answers: dict[tuple[int, int], bytes] = {}
        for lookback, limit in BOUNDS:
            with _statements(scene.engine) as by_read:
                read = reads.read(
                    principal_id,
                    MeetingContextRequest(
                        meeting_ids=ids, lookback_days=lookback, per_meeting_limit=limit
                    ),
                )
            with _statements(scene.engine) as by_seam:
                seam = reads.read_inputs(
                    principal_id, inputs, lookback_days=lookback, per_meeting_limit=limit
                )
            assert _bytes(seam) == _bytes(read), (pulse, lookback, limit)
            sent = [statement for statement, _parameters in by_read]
            assert len(sent) == len(by_seam) + INPUT_READS
            assert sent[INPUT_READS:] == [statement for statement, _parameters in by_seam]
            answers[lookback, limit] = _bytes(read)
            if (lookback, limit) == (3, 1):
                assert max(len(c.communications.messages) for c in read.meetings) == 1
        # Each bound answers differently, beyond the echoed limits.
        assert len(set(answers.values())) == len(BOUNDS)
        defaults = json.loads(answers[14, 15])
        maximum = json.loads(answers[90, 50])
        # The maximum reaches the October messages the defaults cannot.
        assert (
            maximum["meetings"][0]["communications"]["matched_total"]
            > (defaults["meetings"][0]["communications"]["matched_total"])
        )
