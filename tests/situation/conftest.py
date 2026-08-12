"""In-memory, principal-partitioned stubs for the WP-06 continuity ports.

The FAST tier is required to be database-free (`module-boundaries.md` section 11),
so the situation/frame/trace/project/relationship-event/pulse use cases are driven
here against fakes that implement the *ports* declared in `contracts.ports` rather
than the store. What these fakes reproduce, faithfully, is the one discipline the
work package is about: **every read filters by `principal_id` and every write
stamps it.** A lookup for a record another Principal owns adds `principal_id ==
<caller>` and finds nothing, exactly as the real `SqlSituationRepository` does — so
a cross-principal read is answered `None`/`()`/`UnknownScopeError`, never with a
foreign record.

What these fakes cannot prove is that the *server* enforces the same partition
(the `principal_id` CHECK, the `pulse_reads_only_accepted_records` CHECK, and the
real `WHERE principal_id = …` predicate). That claim belongs to the `database`
tier — `tests/database/test_situation_schema_migration.py` and
`tests/database/test_cross_principal_r5_isolation.py` — against a live PostgreSQL
server. Neither tier is sufficient alone.

Everything is synthetic: two invented Moss principals and made-up person, object,
and reference identifiers. No real path, person, or source appears.
"""

from __future__ import annotations

import itertools
from datetime import datetime

import pytest

from my_pa.application.situation_service import SituationService
from my_pa.contracts.ports import (
    FrameRepository,
    ProjectRepository,
    PulseRepository,
    RelationshipEventRepository,
    SituationRepository,
    TraceRepository,
    UnknownScopeError,
)
from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.common.time import utc_now
from my_pa.domain.relationship.event import RelationshipEvent, RelationshipEventType
from my_pa.domain.situation.situation import (
    Frame,
    FrameState,
    Project,
    ProjectState,
    PulseItem,
    PulseItemType,
    Situation,
    SituationState,
    Trace,
)

#: Two synthetic Moss principals, in the shape every prior isolation suite uses.
PRINCIPAL_A = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B = "prn_bbbb0002bbbb0002bbbb0002"

#: A synthetic already-resolved Person the relationship-timeline tests record against.
PERSON_ONE = "per_person0001person0001"


_COUNTER = itertools.count(1)


def _issue(kind: IdKind) -> str:
    """A well-formed, non-semantic opaque identifier for a fake to hand back.

    Mirrors what `domain.source.registry.issue_identifier` does for the real
    repositories — the fakes must mint identity server-side too, because the
    Principal travels as a resolved partition and never as a caller-supplied id.
    """
    return make_identifier(kind, f"{next(_COUNTER):0>16d}")


class InMemorySituationRepository(SituationRepository):
    """Situations in a dict, every operation confined to one Principal's partition."""

    def __init__(self) -> None:
        self._rows: dict[str, Situation] = {}

    def open_situation(
        self,
        *,
        principal_id: str,
        title: str,
        description: str | None,
        object_refs: tuple[str, ...],
    ) -> Situation:
        now = utc_now()
        situation = Situation(
            situation_id=_issue(IdKind.SITUATION),
            principal_id=principal_id,
            title=title,
            state=SituationState.OPEN,
            opened_at=now,
            created_at=now,
            updated_at=now,
            description=description,
            object_refs=tuple(object_refs),
        )
        self._rows[situation.situation_id] = situation
        return situation

    def close_situation(self, *, principal_id: str, situation_id: str, outcome: str) -> Situation:
        current = self._rows.get(situation_id)
        # The partition predicate: a Situation owned by another Principal is
        # indistinguishable from one that does not exist.
        if current is None or current.principal_id != principal_id:
            raise UnknownScopeError
        now = utc_now()
        closed = Situation(
            situation_id=current.situation_id,
            principal_id=current.principal_id,
            title=current.title,
            state=SituationState.CLOSED,
            opened_at=current.opened_at,
            created_at=current.created_at,
            updated_at=now,
            description=current.description,
            object_refs=current.object_refs,
            closed_at=now,
            outcome=outcome,
        )
        self._rows[situation_id] = closed
        return closed

    def get_situation(self, principal_id: str, situation_id: str) -> Situation | None:
        current = self._rows.get(situation_id)
        if current is None or current.principal_id != principal_id:
            return None
        return current

    def list_situations(
        self, principal_id: str, state_filter: SituationState | None = None
    ) -> tuple[Situation, ...]:
        rows = [row for row in self._rows.values() if row.principal_id == principal_id]
        if state_filter is not None:
            rows = [row for row in rows if row.state is state_filter]
        rows.sort(key=lambda row: row.created_at, reverse=True)
        return tuple(rows)


class InMemoryFrameRepository(FrameRepository):
    """Frames within Situations, partitioned by Principal like everything else."""

    def __init__(self, situations: InMemorySituationRepository) -> None:
        self._situations = situations
        self._rows: dict[str, Frame] = {}

    def enter_frame(
        self,
        *,
        principal_id: str,
        situation_id: str,
        label: str,
        evidence_refs: tuple[str, ...],
        alternatives: tuple[str, ...],
        obligations: tuple[str, ...],
        uncertainty: str | None,
        next_authority: str | None,
    ) -> Frame:
        # A Frame may only be entered in a Situation this Principal owns; the
        # ownership check is itself partition-scoped.
        if self._situations.get_situation(principal_id, situation_id) is None:
            raise UnknownScopeError
        now = utc_now()
        frame = Frame(
            frame_id=_issue(IdKind.FRAME),
            situation_id=situation_id,
            principal_id=principal_id,
            label=label,
            state=FrameState.CURRENT,
            created_at=now,
            updated_at=now,
            evidence_refs=tuple(evidence_refs),
            alternatives=tuple(alternatives),
            obligations=tuple(obligations),
            uncertainty=uncertainty,
            next_authority=next_authority,
        )
        self._rows[frame.frame_id] = frame
        return frame

    def get_frames(self, principal_id: str, situation_id: str) -> tuple[Frame, ...]:
        rows = [
            row
            for row in self._rows.values()
            if row.principal_id == principal_id and row.situation_id == situation_id
        ]
        rows.sort(key=lambda row: row.created_at, reverse=True)
        return tuple(rows)


class InMemoryTraceRepository(TraceRepository):
    """Traces: derived reconstructions, principal-scoped."""

    def __init__(self) -> None:
        self._rows: dict[str, Trace] = {}

    def record_trace(
        self,
        *,
        principal_id: str,
        object_id: str,
        object_type: str,
        time_range_start: datetime | None,
        time_range_end: datetime | None,
    ) -> Trace:
        trace = Trace(
            trace_id=_issue(IdKind.TRACE),
            principal_id=principal_id,
            object_id=object_id,
            object_type=object_type,
            created_at=utc_now(),
            time_range_start=time_range_start,
            time_range_end=time_range_end,
        )
        self._rows[trace.trace_id] = trace
        return trace

    def get_trace(self, principal_id: str, trace_id: str) -> Trace | None:
        current = self._rows.get(trace_id)
        if current is None or current.principal_id != principal_id:
            return None
        return current


class InMemoryProjectRepository(ProjectRepository):
    """Projects and the Project↔Situation link, principal-scoped throughout."""

    def __init__(self, situations: InMemorySituationRepository) -> None:
        self._situations = situations
        self._rows: dict[str, Project] = {}
        self._links: set[tuple[str, str, str]] = set()

    def add_project(
        self,
        *,
        principal_id: str,
        name: str,
        description: str | None,
        participants: tuple[str, ...],
    ) -> Project:
        now = utc_now()
        project = Project(
            project_id=_issue(IdKind.PROJECT),
            principal_id=principal_id,
            name=name,
            state=ProjectState.ACTIVE,
            opened_at=now,
            created_at=now,
            updated_at=now,
            description=description,
            participants=tuple(participants),
        )
        self._rows[project.project_id] = project
        return project

    def get_project(self, principal_id: str, project_id: str) -> Project | None:
        current = self._rows.get(project_id)
        if current is None or current.principal_id != principal_id:
            return None
        return current

    def list_projects(
        self, principal_id: str, state_filter: ProjectState | None = None
    ) -> tuple[Project, ...]:
        rows = [row for row in self._rows.values() if row.principal_id == principal_id]
        if state_filter is not None:
            rows = [row for row in rows if row.state is state_filter]
        rows.sort(key=lambda row: row.created_at, reverse=True)
        return tuple(rows)

    def link_situation(self, *, principal_id: str, project_id: str, situation_id: str) -> None:
        project = self.get_project(principal_id, project_id)
        situation = self._situations.get_situation(principal_id, situation_id)
        if project is None or situation is None:
            raise UnknownScopeError
        # Idempotent per (principal, project, situation).
        self._links.add((principal_id, project_id, situation_id))


class InMemoryRelationshipEventRepository(RelationshipEventRepository):
    """Relationship-timeline events; acceptance gates what Today/Pulse read."""

    def __init__(self) -> None:
        self._rows: dict[str, RelationshipEvent] = {}

    def record_event(
        self,
        *,
        principal_id: str,
        person_id: str,
        event_type: RelationshipEventType,
        occurred_at: datetime,
        context: str | None,
        accepted: bool,
        source_ref: str | None,
    ) -> RelationshipEvent:
        event = RelationshipEvent(
            event_id=_issue(IdKind.RELATIONSHIP_EVENT),
            principal_id=principal_id,
            person_id=person_id,
            event_type=event_type,
            occurred_at=occurred_at,
            created_at=utc_now(),
            context=context,
            accepted=accepted,
            source_ref=source_ref,
        )
        self._rows[event.event_id] = event
        return event

    def list_events(self, principal_id: str, person_id: str) -> tuple[RelationshipEvent, ...]:
        rows = [
            row
            for row in self._rows.values()
            if row.principal_id == principal_id and row.person_id == person_id
        ]
        rows.sort(key=lambda row: row.occurred_at, reverse=True)
        return tuple(rows)

    def list_accepted_events(self, principal_id: str) -> tuple[RelationshipEvent, ...]:
        # The accepted-timeline read: the `accepted` gate is added to the
        # partition predicate, so a proposed event is structurally excluded.
        rows = [
            row
            for row in self._rows.values()
            if row.principal_id == principal_id and row.accepted is True
        ]
        rows.sort(key=lambda row: row.occurred_at, reverse=True)
        return tuple(rows)


class InMemoryPulseRepository(PulseRepository):
    """Pulse: derived attention recommendations, read only from accepted state.

    A test seeds items through `seed`; `generate_pulse` then applies the WP-06
    read contract — this Principal's partition, `accepted_only` true, and not
    dismissed — so the fake cannot surface an item a writer marked otherwise.
    """

    def __init__(self) -> None:
        self._rows: dict[str, PulseItem] = {}

    def seed(
        self,
        *,
        principal_id: str,
        item_type: PulseItemType,
        item_ref: str,
        reason: str,
        priority: int = 5,
    ) -> PulseItem:
        item = PulseItem(
            pulse_id=_issue(IdKind.PULSE),
            principal_id=principal_id,
            item_type=item_type,
            item_ref=item_ref,
            reason=reason,
            generated_at=utc_now(),
            priority=priority,
        )
        self._rows[item.pulse_id] = item
        return item

    def generate_pulse(self, principal_id: str) -> tuple[PulseItem, ...]:
        rows = [
            row
            for row in self._rows.values()
            if row.principal_id == principal_id
            and row.accepted_only is True
            and row.dismissed_at is None
        ]
        rows.sort(key=lambda row: (row.priority, row.generated_at), reverse=True)
        return tuple(rows)

    def dismiss_pulse_item(self, principal_id: str, pulse_id: str) -> None:
        current = self._rows.get(pulse_id)
        if current is None or current.principal_id != principal_id:
            raise UnknownScopeError
        self._rows[pulse_id] = PulseItem(
            pulse_id=current.pulse_id,
            principal_id=current.principal_id,
            item_type=current.item_type,
            item_ref=current.item_ref,
            reason=current.reason,
            generated_at=current.generated_at,
            consequence=current.consequence,
            next_step=current.next_step,
            priority=current.priority,
            dismissed_at=utc_now(),
        )


@pytest.fixture
def service() -> SituationService:
    """The one continuity application service, holding no state."""
    return SituationService()


@pytest.fixture
def situations() -> InMemorySituationRepository:
    return InMemorySituationRepository()


@pytest.fixture
def frames(situations: InMemorySituationRepository) -> InMemoryFrameRepository:
    return InMemoryFrameRepository(situations)


@pytest.fixture
def traces() -> InMemoryTraceRepository:
    return InMemoryTraceRepository()


@pytest.fixture
def projects(situations: InMemorySituationRepository) -> InMemoryProjectRepository:
    return InMemoryProjectRepository(situations)


@pytest.fixture
def relationship_events() -> InMemoryRelationshipEventRepository:
    return InMemoryRelationshipEventRepository()


@pytest.fixture
def pulse() -> InMemoryPulseRepository:
    return InMemoryPulseRepository()
