"""WP5-S4: the `pulse` section of `meetings.context.read` on PostgreSQL.

The `database` tier, on a disposable current-head clone, run on the C and the
en_US.UTF-8 clusters alike, through `MeetingContextReads` over the real unit of
work. Meetings are made through the real `ApplicationService`, communications
rows through the real repositories (`tests/database/communications_search_world.py`),
and the project-report world through the real WP3P path
(`tests/unit/project_report_reads_scene.py`, `build_world` and `extend_world`),
all under one Principal. Proved here (WP5 design 3.5 and 3.10; rulings D7, D8,
D12; PULSE plan section 10 and PULSE-AC-16):

* the states: `reads_disabled` with the switch off (no project-report table is
  read), `not_linked`, and the facade's `unbound`, `never_ingested`,
  `all_quarantined` and `available`;
* an `available` section is the facade's answer for its Project: the counts in
  family order with their total, the RFIs the Meeting's own numbers and its
  returned messages' numbers match (Meeting first), `ambiguous_prefix` with its
  candidates, `none` only counted, and the versions and qualifiers;
* PULSE-AC-16: every byte of the answer but the `pulse` sections is the same
  with the switch off, with it on over empty project-report tables, and with it
  on over the populated world;
* the statement count: the communications part's, plus the identifiers of
  the returned messages, plus 6 + 2L for the facade (bindings; versions, 3;
  cross-checks; RFI candidates; L line reads of 2 statements each, the lines
  and their values), the same for 1 Meeting and for 10 of one Project, and
  6 + 2L over 3 Projects;
* the runtime current-derivations backstop sees every child-table statement.

Every identifier, subject, text, address and number here is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Final

import pytest
from sqlalchemy import Engine, update
from sqlalchemy.dialects.postgresql import insert

from my_pa.application.meeting_context import (
    MAX_PULSE_COUNTS,
    MeetingContextAnswer,
    MeetingContextReads,
    MeetingContextRequest,
    PulseState,
    RfiSource,
    context_payload,
)
from my_pa.application.project_reports_reads import (
    ProjectReportReads,
    measure_entry_payload,
    project_summary_payload,
)
from my_pa.bootstrap.project_reports import project_reports_unit_of_work
from my_pa.domain.project_reports.model import DerivationState, RecordFamily
from my_pa.infrastructure.persistence.tables import projects
from tests.contract.test_meeting_mcp import _insert_partition
from tests.database.communications_search_world import NOW, World, at, unit_of_work
from tests.database.project_report_reads_backstop import Backstop, current_derivations_backstop
from tests.database.test_meeting_context_communications import (
    _SOURCES,
    NUMBER,
    SELF,
    A,
    B,
    C,
    Scene,
    _statements,
)
from tests.database.test_task_record_events import Runtime
from tests.unit.project_report_reads_scene import (
    OBS_PROJECT,
    RFI_PROJECT,
    WHEN,
    ReadsScene,
    build_world,
)
from tests.unit.project_reports_reads_service_cases import (
    NEVER_PROJECT,
    PAIR_PROJECT,
    QUARANTINED_PROJECT,
    extend_world,
)

pytestmark = pytest.mark.database

#: The communications part of a batch (WP5-C ruling C-1): 14 + 1 per source.
COMMUNICATIONS_STATEMENTS: Final = 14 + _SOURCES


@pytest.fixture(autouse=True)
def _current_derivations_backstop() -> Iterator[Backstop]:
    """Ruling R2-02: every child-table statement the reads send joins the view."""
    with current_derivations_backstop() as seen:
        yield seen


@dataclass
class PulseScene:
    base: Scene
    reports: ReadsScene

    @property
    def engine(self) -> Engine:
        return self.base.engine

    @property
    def principal_id(self) -> str:
        return self.base.principal_id

    def project(self, project_id: str, number: str) -> None:
        """A Project of the Principal (a no-op when it exists): a Meeting may name it."""
        with self.engine.begin() as connection:
            connection.execute(
                insert(projects)
                .values(
                    project_id=project_id,
                    principal_id=self.principal_id,
                    name="Synthetic project",
                    opened_at=WHEN,
                    created_at=WHEN,
                    updated_at=WHEN,
                    project_number=number,
                )
                .on_conflict_do_nothing()
            )

    def populate(self) -> None:
        build_world(self.reports)
        extend_world(self.reports)

    def reads(self, *, pulse: bool) -> MeetingContextReads:
        return MeetingContextReads(
            unit_of_work=unit_of_work(self.engine), clock=lambda: NOW, project_reports_enabled=pulse
        )

    def read(self, ids: list[str], *, pulse: bool = True) -> MeetingContextAnswer:
        return self.reads(pulse=pulse).read(self.principal_id, MeetingContextRequest(ids))

    def facade(self) -> ProjectReportReads:
        return ProjectReportReads(unit_of_work=unit_of_work(self.engine), clock=lambda: NOW)


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
        mail = World(runtime.work_engine, principal_id=principal_id, tag="p")
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


def _pulse(answer: MeetingContextAnswer) -> list[dict[str, Any]]:
    return [meeting["pulse"] for meeting in _payload(answer)["meetings"]]


def _payload(answer: MeetingContextAnswer) -> Any:  # noqa: ANN401 - the JSON answer
    return context_payload(answer)


def _without_pulse(answer: MeetingContextAnswer) -> bytes:
    payload = _payload(answer)
    for meeting in payload["meetings"]:
        del meeting["pulse"]
    return json.dumps(payload, ensure_ascii=False).encode()


def _mail(scene: PulseScene) -> None:
    w = scene.base.mail
    w.message(
        1,
        subject="Slab pour RFI 176",
        text="RFI 176 and RFI 175 for the slab.",
        when=at(17, 10),
        participants=(("from", A), ("to", B)),
    )
    w.message(2, subject="Question", text="RFI 176 again.", when=at(17, 11))
    w.message(3, subject="Other", text="RFI 9 is elsewhere.", when=at(17, 12))
    w.message(4, subject="Slab", text="Nothing numbered.", when=at(17, 13))


# ---- the states ------------------------------------------------------------------------


def test_every_state_of_the_section(scene: PulseScene) -> None:
    scene.populate()
    _mail(scene)
    base = scene.base
    ids = [
        base.meeting("none", title="Slab pour"),
        base.meeting("unbound", title="Slab pour", project_id=base.mine.project_id),
        base.meeting("never", title="Slab pour", project_id=NEVER_PROJECT[1]),
        base.meeting("quarantined", title="Slab pour", project_id=QUARANTINED_PROJECT[1]),
        base.meeting("rfis", title="Slab pour RFI 174", project_id=RFI_PROJECT[1]),
    ]
    sections = _pulse(scene.read(ids))
    assert [s["state"] for s in sections] == [
        "not_linked",
        "unavailable",
        "unavailable",
        "unavailable",
        "available",
    ]
    assert sections[0] == {"state": "not_linked"}
    assert sections[1] == {
        "state": "unavailable",
        "reason": "unbound",
        "project_id": base.mine.project_id,
    }
    assert [s.get("reason") for s in sections[2:4]] == ["never_ingested", "all_quarantined"]
    assert [s["project_id"] for s in sections[1:]] == [
        base.mine.project_id,
        NEVER_PROJECT[1],
        QUARANTINED_PROJECT[1],
        RFI_PROJECT[1],
    ]
    # Ruling D8: with the switch off nothing project-report is read.
    with _statements(scene.engine) as seen:
        off = _pulse(scene.read(ids, pulse=False))
    assert off == [{"state": "unavailable", "reason": "reads_disabled"}] * len(ids)
    assert len(seen) == COMMUNICATIONS_STATEMENTS
    assert not [s for s, _ in seen if "project_report" in s]


def test_an_available_section_is_the_facades_answer_for_its_project(scene: PulseScene) -> None:
    scene.populate()
    _mail(scene)
    meeting = scene.base.meeting(
        "rfis",
        title="Slab pour RFI 174",
        emails=(A,),
        description="See RFI 1741 and RFI 175.",
        project_id=RFI_PROJECT[1],
    )
    answer = scene.read([meeting])
    (context,) = answer.meetings
    section = context.pulse
    assert section.state is PulseState.AVAILABLE
    (pulse,) = _pulse(answer)
    # The Meeting's own numbers ascending, then the messages' by how many carry each.
    returned = {m.message_id for m in context.communications.messages}
    assert len(returned) >= 3
    asked = [(174, "meeting"), (175, "meeting"), (1741, "meeting"), (176, "communications")]
    asked += [(9, "communications")]
    facade = scene.facade()
    expected = facade.match_rfis(scene.principal_id, RFI_PROJECT[1], [(None, n) for n, _ in asked])
    sources = dict(asked)
    assert [(r.match, r.source.value) for r in section.rfis] == [
        (m, sources[m.suffix]) for m in expected if m.state != "none"
    ]
    assert {r.match.state for r in section.rfis} == {"exact", "ambiguous_prefix"}
    assert {r.source for r in section.rfis} == {RfiSource.MEETING, RfiSource.COMMUNICATIONS}
    ambiguous = next(r for r in pulse["rfis"] if r["state"] == "ambiguous_prefix")
    assert ambiguous["suffix"] == 174 and len(ambiguous["candidates"]) >= 2
    assert pulse["rfi_numbers_total"] == len(asked)
    assert pulse["rfi_numbers_truncated"] is False
    # Counts, versions and qualifiers are the facade's, the counts in family order.
    summary = facade.project_summary(scene.principal_id, RFI_PROJECT[1])
    rendered = project_summary_payload(summary)
    assert pulse["versions"] == rendered["versions"]
    assert pulse["qualifiers"] == rendered["qualifiers"]
    family = {b.record.snapshot_id: b.record.record_family for b in summary.versions}
    order = (RecordFamily.OBSERVATIONS, RecordFamily.COORDINATION_ISSUES, RecordFamily.RFIS)
    ranked = sorted(summary.counts, key=lambda e: order.index(family[str(e.version)]))
    assert pulse["counts"] == [measure_entry_payload(e) for e in ranked[:MAX_PULSE_COUNTS]]
    assert pulse["counts_total"] == len(summary.counts) and pulse["counts_total"] > 0
    assert pulse["counts_truncated"] is (len(summary.counts) > MAX_PULSE_COUNTS)
    assert pulse["project_id"] == RFI_PROJECT[1]


def test_two_meetings_of_one_project_ask_their_own_numbers(scene: PulseScene) -> None:
    scene.populate()
    base = scene.base
    first = base.meeting("first", title="RFI 174 call", project_id=RFI_PROJECT[1])
    second = base.meeting("second", title="RFI 175 call", project_id=RFI_PROJECT[1])
    observations = base.meeting("obs", title="RFI 175 call", project_id=OBS_PROJECT[1])
    sections = [c.pulse for c in scene.read([first, second, observations]).meetings]
    assert [[r.match.suffix for r in s.rfis] for s in sections] == [[174], [175], []]
    assert [s.rfi_numbers_total for s in sections] == [1, 1, 1]
    assert sections[0].summary == sections[1].summary
    assert sections[2].summary != sections[0].summary


# ---- PULSE-AC-16 -----------------------------------------------------------------------


def test_the_communications_answer_is_byte_identical_with_pulse_off_absent_and_on(
    scene: PulseScene,
) -> None:
    """PULSE-AC-16, with `pulse.state = unavailable` while PULSE is off or absent."""
    _mail(scene)
    base = scene.base
    for project_id, number in (RFI_PROJECT[1:], OBS_PROJECT[1:], PAIR_PROJECT[1:]):
        scene.project(project_id, number)
    ids = [
        base.meeting("rfis", title="Slab pour RFI 174", emails=(A, B), project_id=RFI_PROJECT[1]),
        base.meeting("obs", title="Slab RFI 203", emails=(B,), project_id=OBS_PROJECT[1]),
        base.meeting("pair", title="Pour", emails=(A,), project_id=PAIR_PROJECT[1]),
        base.meeting("own", title="Slab", emails=(A, C), project_id=base.mine.project_id),
        base.meeting("none", title="Slab pour RFI 175", emails=(A,)),
    ]
    off = scene.read(ids, pulse=False)
    absent = scene.read(ids)
    assert all(s["state"] == "unavailable" for s in _pulse(off))
    assert [s["state"] for s in _pulse(absent)] == ["unavailable"] * 4 + ["not_linked"]
    assert {s.get("reason") for s in _pulse(absent)[:4]} == {"unbound"}
    scene.populate()
    on = scene.read(ids)
    assert [s["state"] for s in _pulse(on)] == ["available"] * 3 + ["unavailable", "not_linked"]
    assert any(s["rfis"] for s in _pulse(on)[:3])
    assert any(c.communications.messages for c in on.meetings)
    assert _without_pulse(off) == _without_pulse(absent) == _without_pulse(on)


# ---- the statement count ---------------------------------------------------------------


def _lines_read(scene: PulseScene, project_ids: set[str]) -> int:
    """L: the latest classified summary versions of the Projects (each under 1,000 lines)."""
    facade = scene.facade()
    return sum(
        1
        for project_id in project_ids
        for block in facade.project_summary(scene.principal_id, project_id).versions
        if block.record.state is DerivationState.CLASSIFIED and block.record.family_view
    )


def _numbered_world(scene: PulseScene, project_ids: list[str]) -> list[str]:
    for n in range(1, 21):
        scene.base.mail.message(
            n,
            subject=f"RFI {n} slab",
            text=f"RFI {n} {NUMBER} slab pour",
            when=at(10 + n % 10, 10),
            conversation=f"conv-{n % 4}",
            participants=(("from", A if n % 2 else B), ("to", C)),
            lanes=(("inbox", "verified"),),
        )
    return [
        scene.base.meeting(
            f"count-{n}",
            title=f"Slab pour RFI {n}",
            emails=(A, B, SELF),
            description=f"RFI {n + 1}",
            project_id=project_ids[n % len(project_ids)],
        )
        for n in range(10)
    ]


def test_one_meeting_costs_the_same_statements_as_ten_with_pulse_on(scene: PulseScene) -> None:
    scene.populate()
    ids = _numbered_world(scene, [RFI_PROJECT[1]])
    with _statements(scene.engine) as one:
        answer = scene.read(ids[:1])
    assert answer.meetings[0].pulse.state is PulseState.AVAILABLE
    assert answer.meetings[0].communications.messages
    with _statements(scene.engine) as ten:
        assert all(c.pulse.state is PulseState.AVAILABLE for c in scene.read(ids).meetings)
    lines = _lines_read(scene, {RFI_PROJECT[1]})
    assert lines > 0
    # The communications part, the returned messages' `rfi` identifiers, then the
    # facade: bindings, versions (3), cross-checks, RFI candidates, and L line
    # reads of 2 statements each (the lines, then their values).
    assert len(one) == len(ten) == COMMUNICATIONS_STATEMENTS + 1 + 6 + 2 * lines


def test_three_projects_cost_one_facade_batch(scene: PulseScene) -> None:
    scene.populate()
    three = [RFI_PROJECT[1], OBS_PROJECT[1], PAIR_PROJECT[1]]
    ids = _numbered_world(scene, three)
    with _statements(scene.engine) as seen:
        answer = scene.read(ids)
    assert {c.pulse.state for c in answer.meetings} == {PulseState.AVAILABLE}
    project_reports = [s for s, _ in seen if "project_report" in s]
    assert len(seen) == COMMUNICATIONS_STATEMENTS + 1 + 6 + 2 * _lines_read(scene, set(three))
    # One bindings read, one version list, however many Meetings and Projects.
    assert (
        len([s for s in project_reports if "project_report_bindings" in s and "JOIN" not in s]) == 1
    )
