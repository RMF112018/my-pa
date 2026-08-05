"""MU-AC-05: one Principal's continuity records are invisible to another.

FAST tier. These are the negative half of the WP-06 acceptance criteria: a
Situation, Project, relationship-timeline event, or Pulse item created as
Principal A is structurally invisible to Principal B — B's list comes back empty,
not filtered-with-leftovers and not an error (criterion 3, "foreign principal gets
empty result, not an error"; criterion 4, "no shared identity records legible
across Principals"). The same guarantee is proved against real PostgreSQL rows in
`tests/database/test_cross_principal_r5_isolation.py`; this tier proves the port
contract, that tier proves the server enforces it.

The partition is a predicate, not a policy layered on top, so the stubs in
`conftest.py` reproduce it the way the real repositories do: a read adds
`principal_id == <caller>` and a foreign record simply is not among the rows.

Every identity is synthetic: two invented Moss principals and a made-up Person.
"""

from __future__ import annotations

from datetime import UTC, datetime

from tests.situation.conftest import (
    PERSON_ONE,
    PRINCIPAL_A,
    PRINCIPAL_B,
    InMemoryProjectRepository,
    InMemoryPulseRepository,
    InMemoryRelationshipEventRepository,
    InMemorySituationRepository,
)

from my_pa.application.commands import (
    AddProjectCommand,
    OpenSituationCommand,
    RecordRelationshipEventCommand,
)
from my_pa.application.situation_service import SituationService
from my_pa.domain.relationship.event import RelationshipEventType
from my_pa.domain.situation.situation import PulseItemType

WHEN = datetime(2026, 8, 5, 12, tzinfo=UTC)


def test_situation_from_principal_a_invisible_to_principal_b(
    service: SituationService, situations: InMemorySituationRepository
) -> None:
    """A opens a Situation; B lists Situations and gets nothing."""
    opened = service.open_situation(
        situations,
        OpenSituationCommand(principal_id=PRINCIPAL_A, title="A's private context"),
    )
    # B sees an empty list, not a filtered one and not an error.
    assert situations.list_situations(PRINCIPAL_B) == ()
    # And a direct lookup of A's identifier from B's partition is `None` — a
    # foreign Situation is indistinguishable from an absent one.
    assert situations.get_situation(PRINCIPAL_B, opened.situation_id) is None
    # A still sees exactly its own.
    assert [s.situation_id for s in situations.list_situations(PRINCIPAL_A)] == [
        opened.situation_id
    ]


def test_project_from_principal_a_invisible_to_principal_b(
    service: SituationService, projects: InMemoryProjectRepository
) -> None:
    """A adds a Project; B lists Projects and gets nothing."""
    project = service.add_project(
        projects,
        AddProjectCommand(principal_id=PRINCIPAL_A, name="A's roadmap"),
    )
    assert projects.list_projects(PRINCIPAL_B) == ()
    assert projects.get_project(PRINCIPAL_B, project.project_id) is None
    assert [p.project_id for p in projects.list_projects(PRINCIPAL_A)] == [project.project_id]


def test_relationship_event_from_principal_a_invisible_to_principal_b(
    service: SituationService,
    relationship_events: InMemoryRelationshipEventRepository,
) -> None:
    """A records events for a Person; B, asking about the same Person, sees none.

    The Person identifier is deliberately shared across the two commands — the
    point is that even a *shared identity* record is not legible across
    Principals (criterion 4). B's timeline and accepted-timeline reads are both
    empty.
    """
    service.record_relationship_event(
        relationship_events,
        RecordRelationshipEventCommand(
            principal_id=PRINCIPAL_A,
            person_id=PERSON_ONE,
            event_type=RelationshipEventType.MEETING,
            occurred_at=WHEN,
            accepted=True,
        ),
    )
    # B asks about the very same person_id and gets an empty timeline …
    assert relationship_events.list_events(PRINCIPAL_B, PERSON_ONE) == ()
    # … and an empty accepted-timeline read.
    assert relationship_events.list_accepted_events(PRINCIPAL_B) == ()
    # A sees its own accepted event.
    assert len(relationship_events.list_accepted_events(PRINCIPAL_A)) == 1


def test_pulse_items_never_cross_principal_boundary(
    pulse: InMemoryPulseRepository,
) -> None:
    """A and B each generate a Pulse; the two results are disjoint by Principal."""
    a_item = pulse.seed(
        principal_id=PRINCIPAL_A,
        item_type=PulseItemType.COMMITMENT,
        item_ref="cmt_ref_00000000000a",
        reason="A owes a reply",
    )
    b_item = pulse.seed(
        principal_id=PRINCIPAL_B,
        item_type=PulseItemType.DECISION,
        item_ref="dec_ref_00000000000b",
        reason="B must decide",
    )
    a_pulse = pulse.generate_pulse(PRINCIPAL_A)
    b_pulse = pulse.generate_pulse(PRINCIPAL_B)

    assert [item.pulse_id for item in a_pulse] == [a_item.pulse_id]
    assert [item.pulse_id for item in b_pulse] == [b_item.pulse_id]
    # Disjoint: neither Principal's Pulse contains the other's item, and every
    # item each sees is stamped with that same Principal.
    a_ids = {item.pulse_id for item in a_pulse}
    b_ids = {item.pulse_id for item in b_pulse}
    assert a_ids.isdisjoint(b_ids)
    assert all(item.principal_id == PRINCIPAL_A for item in a_pulse)
    assert all(item.principal_id == PRINCIPAL_B for item in b_pulse)
