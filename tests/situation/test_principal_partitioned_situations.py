"""WP-06: the continuity surface binds its Principal, and Pulse gates on acceptance.

FAST tier. Seven unit tests drive `SituationService` over the in-memory,
principal-partitioned port stubs in this package's `conftest.py`. What they assert
is the positive half of the WP-06 acceptance criteria: a Situation, Frame, Trace,
Project, PulseItem, and RelationshipEvent each carry the `principal_id` the command
resolved (criterion 1 — records are principal-scoped end to end), and Today/Pulse
plus the accepted-timeline read surface only accepted records (criterion 2). The
cross-principal negative half is in
`test_cross_principal_situation_isolation.py` (MU-AC-05).

Every identity is synthetic: the two invented Moss principals and a made-up Person.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from tests.situation.conftest import (
    PERSON_ONE,
    PRINCIPAL_A,
    InMemoryFrameRepository,
    InMemoryProjectRepository,
    InMemoryRelationshipEventRepository,
    InMemorySituationRepository,
    InMemoryTraceRepository,
)

from my_pa.application.commands import (
    AddProjectCommand,
    CloseSituationCommand,
    EnterFrameCommand,
    OpenSituationCommand,
    RecordRelationshipEventCommand,
    TraceObjectCommand,
)
from my_pa.application.situation_service import SituationService
from my_pa.domain.relationship.event import RelationshipEventType
from my_pa.domain.situation.situation import PulseItem, PulseItemType, SituationState

WHEN = datetime(2026, 8, 5, 12, tzinfo=UTC)


def test_open_situation_binds_principal_id(
    service: SituationService, situations: InMemorySituationRepository
) -> None:
    """The opened Situation carries the command's Principal, not a caller field."""
    opened = service.open_situation(
        situations,
        OpenSituationCommand(
            principal_id=PRINCIPAL_A,
            title="North dock reconciliation",
            object_refs=("cap_00000000000000000001",),
        ),
    )
    assert opened.principal_id == PRINCIPAL_A
    assert opened.state is SituationState.OPEN
    # And it is legible only through its own Principal's partition.
    assert situations.get_situation(PRINCIPAL_A, opened.situation_id) == opened


def test_close_situation_sets_state_closed(
    service: SituationService, situations: InMemorySituationRepository
) -> None:
    """Closing moves state to CLOSED, records an outcome, and pins closed_at."""
    opened = service.open_situation(
        situations,
        OpenSituationCommand(principal_id=PRINCIPAL_A, title="Weekly close"),
    )
    closed = service.close_situation(
        situations,
        CloseSituationCommand(
            principal_id=PRINCIPAL_A,
            situation_id=opened.situation_id,
            outcome="carried the open commitment forward",
        ),
    )
    assert closed.state is SituationState.CLOSED
    assert closed.outcome == "carried the open commitment forward"
    # A closed Situation records when it closed, and only then (the domain and
    # the migration CHECK `a_closed_situation_records_when_it_closed` agree).
    assert closed.closed_at is not None
    assert closed.principal_id == PRINCIPAL_A


def test_enter_frame_binds_situation_and_principal(
    service: SituationService,
    situations: InMemorySituationRepository,
    frames: InMemoryFrameRepository,
) -> None:
    """A Frame carries both its Situation and the command's Principal."""
    opened = service.open_situation(
        situations,
        OpenSituationCommand(principal_id=PRINCIPAL_A, title="Vendor dispute"),
    )
    frame = service.enter_frame(
        frames,
        EnterFrameCommand(
            principal_id=PRINCIPAL_A,
            situation_id=opened.situation_id,
            label="What matters now",
            obligations=("owe a reply by Friday",),
        ),
    )
    assert frame.principal_id == PRINCIPAL_A
    assert frame.situation_id == opened.situation_id
    assert frame.obligations == ("owe a reply by Friday",)


def test_add_project_binds_principal_id(
    service: SituationService, projects: InMemoryProjectRepository
) -> None:
    """The created Project carries the command's Principal."""
    project = service.add_project(
        projects,
        AddProjectCommand(
            principal_id=PRINCIPAL_A,
            name="Q3 platform rollout",
            participants=(PERSON_ONE,),
        ),
    )
    assert project.principal_id == PRINCIPAL_A
    assert projects.get_project(PRINCIPAL_A, project.project_id) == project


def test_trace_object_binds_principal_id(
    service: SituationService, traces: InMemoryTraceRepository
) -> None:
    """A Trace carries the command's Principal and the object it reconstructs."""
    trace = service.trace_object(
        traces,
        TraceObjectCommand(
            principal_id=PRINCIPAL_A,
            object_id="cap_00000000000000000009",
            object_type="capture",
            time_range_start=WHEN,
            time_range_end=WHEN,
        ),
    )
    assert trace.principal_id == PRINCIPAL_A
    assert trace.object_id == "cap_00000000000000000009"
    assert traces.get_trace(PRINCIPAL_A, trace.trace_id) == trace


def test_pulse_item_accepted_only_is_always_true() -> None:
    """`accepted_only` cannot be built false — the domain half of the gate.

    The migration pins it with the CHECK `pulse_reads_only_accepted_records`;
    the dataclass refuses a false value in `__post_init__`, so a Pulse item that
    reads an unaccepted record cannot even be constructed.
    """
    # The default is true and constructs.
    accepted = PulseItem(
        pulse_id="puls_00000000000000000001",
        principal_id=PRINCIPAL_A,
        item_type=PulseItemType.COMMITMENT,
        item_ref="cmt_ref_000000000001",
        reason="due tomorrow",
        generated_at=WHEN,
    )
    assert accepted.accepted_only is True
    # A false value is refused at construction.
    with pytest.raises(ValueError, match="reads only accepted records"):
        PulseItem(
            pulse_id="puls_00000000000000000002",
            principal_id=PRINCIPAL_A,
            item_type=PulseItemType.COMMITMENT,
            item_ref="cmt_ref_000000000001",
            reason="due tomorrow",
            generated_at=WHEN,
            accepted_only=False,
        )


def test_relationship_event_accepted_flag_gates_pulse(
    service: SituationService,
    relationship_events: InMemoryRelationshipEventRepository,
) -> None:
    """Only accepted relationship events reach the accepted-timeline read.

    An event recorded proposed (`accepted=False`, the command default) is legible
    on the full timeline but never on `list_accepted_events`, which is what Today
    and the briefing read — invariant 5, "no timeline entry presents a proposal
    as accepted".
    """
    proposed = service.record_relationship_event(
        relationship_events,
        RecordRelationshipEventCommand(
            principal_id=PRINCIPAL_A,
            person_id=PERSON_ONE,
            event_type=RelationshipEventType.INTERACTION,
            occurred_at=WHEN,
            context="left a voicemail",
        ),
    )
    accepted = service.record_relationship_event(
        relationship_events,
        RecordRelationshipEventCommand(
            principal_id=PRINCIPAL_A,
            person_id=PERSON_ONE,
            event_type=RelationshipEventType.MEETING,
            occurred_at=WHEN,
            context="kickoff meeting",
            accepted=True,
        ),
    )
    assert proposed.accepted is False
    assert accepted.accepted is True
    # The full timeline holds both; the accepted read holds only the accepted one.
    everything = relationship_events.list_events(PRINCIPAL_A, PERSON_ONE)
    accepted_only = relationship_events.list_accepted_events(PRINCIPAL_A)
    assert {event.event_id for event in everything} == {proposed.event_id, accepted.event_id}
    assert [event.event_id for event in accepted_only] == [accepted.event_id]
