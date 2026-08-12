"""Principal-scoped persistence for the WP-06 (R5) continuity surface.

Six concrete repositories back the situation/frame/trace/project/relationship-
event/pulse ports declared in `contracts.ports`. They share one discipline that
is the whole point of the work package:

**Every read filters by `principal_id` and every write stamps it.** WP-06's
acceptance criteria require that relationship records and timelines are
principal-scoped end to end, that a cross-principal read returns nothing rather
than another Principal's record, and that no shared-identity record is legible
across Principals. The partition is therefore not a policy layered on top — it
is a predicate on every `SELECT` and a value on every `INSERT` in this module.
A `situation_id` (or any other identifier) that belongs to another Principal is
indistinguishable here from one that does not exist: the lookup adds
`principal_id == <caller>` and finds nothing.

`PulseRepository.generate_pulse` carries the second criterion — "Today/Pulse read
only accepted records". It reads only rows whose `accepted_only` is true (which
the migration CHECK `pulse_reads_only_accepted_records` pins), and excludes
dismissed items. `RelationshipEventRepository.list_accepted_events` is the
relationship-timeline half of the same rule: it returns only events whose
`accepted` gate is set, so a proposed event never surfaces as an accepted fact
(invariant 5).

Each repository takes a `Connection` and issues opaque identifiers through
`domain.source.registry.issue_identifier`, matching `SqlRelationshipRepository`.
A refusal to act on a record outside the caller's partition is reported as
`UnknownScopeError` — the port vocabulary's `not_found`, chosen so a
cross-principal reference is answered the same way a genuinely absent one is.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Row

from my_pa.contracts.ports import (
    FrameRepository,
    ProjectRepository,
    PulseRepository,
    RelationshipEventRepository,
    SituationRepository,
    TraceRepository,
    UnknownScopeError,
)
from my_pa.domain.common.identifiers import IdKind
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
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.tables import (
    frames,
    project_situations,
    projects,
    pulse_items,
    relationship_events,
    situations,
    traces,
)

__all__ = [
    "SqlFrameRepository",
    "SqlProjectRepository",
    "SqlPulseRepository",
    "SqlRelationshipEventRepository",
    "SqlSituationRepository",
    "SqlTraceRepository",
]


def _as_tuple(value: object) -> tuple[str, ...]:
    """Read a JSONB array column back as the domain's immutable tuple of strings."""
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    raise ValueError("a stored reference list is a JSON array")


def _as_dict_tuple(value: object) -> tuple[dict[str, object], ...]:
    """Read a JSONB array of objects back as a tuple of dicts (Trace events/gaps)."""
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(dict(item) for item in value)
    raise ValueError("a stored trace list is a JSON array of objects")


class SqlSituationRepository(SituationRepository):
    """Situations, every operation confined to one Principal's partition."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def open_situation(
        self,
        *,
        principal_id: str,
        title: str,
        description: str | None,
        object_refs: tuple[str, ...],
    ) -> Situation:
        situation_id = issue_identifier(IdKind.SITUATION)
        now = utc_now()
        self._connection.execute(
            insert(situations).values(
                situation_id=situation_id,
                principal_id=principal_id,
                title=title,
                description=description,
                state=SituationState.OPEN.value,
                object_refs=list(object_refs),
                opened_at=now,
                closed_at=None,
                outcome=None,
                created_at=now,
                updated_at=now,
            )
        )
        return Situation(
            situation_id=situation_id,
            principal_id=principal_id,
            title=title,
            state=SituationState.OPEN,
            opened_at=now,
            created_at=now,
            updated_at=now,
            description=description,
            object_refs=tuple(object_refs),
        )

    def close_situation(self, *, principal_id: str, situation_id: str, outcome: str) -> Situation:
        now = utc_now()
        # The WHERE clause carries `principal_id`, so an UPDATE against another
        # Principal's Situation matches no row and is reported as not-found.
        result = self._connection.execute(
            update(situations)
            .where(
                and_(
                    situations.c.situation_id == situation_id,
                    situations.c.principal_id == principal_id,
                )
            )
            .values(
                state=SituationState.CLOSED.value,
                closed_at=now,
                outcome=outcome,
                updated_at=now,
            )
            .returning(*situations.c)
        ).one_or_none()
        if result is None:
            raise UnknownScopeError
        return self._to_situation(result)

    def get_situation(self, principal_id: str, situation_id: str) -> Situation | None:
        row = self._connection.execute(
            select(*situations.c).where(
                and_(
                    situations.c.situation_id == situation_id,
                    situations.c.principal_id == principal_id,
                )
            )
        ).one_or_none()
        return None if row is None else self._to_situation(row)

    def list_situations(
        self, principal_id: str, state_filter: SituationState | None = None
    ) -> tuple[Situation, ...]:
        criteria = [situations.c.principal_id == principal_id]
        if state_filter is not None:
            criteria.append(situations.c.state == state_filter.value)
        rows = self._connection.execute(
            select(*situations.c).where(and_(*criteria)).order_by(situations.c.created_at.desc())
        ).all()
        return tuple(self._to_situation(row) for row in rows)

    @staticmethod
    def _to_situation(row: Row[Any]) -> Situation:
        mapping = row._mapping
        return Situation(
            situation_id=mapping["situation_id"],
            principal_id=mapping["principal_id"],
            title=mapping["title"],
            state=SituationState(mapping["state"]),
            opened_at=mapping["opened_at"],
            created_at=mapping["created_at"],
            updated_at=mapping["updated_at"],
            description=mapping["description"],
            object_refs=_as_tuple(mapping["object_refs"]),
            closed_at=mapping["closed_at"],
            outcome=mapping["outcome"],
        )


class SqlFrameRepository(FrameRepository):
    """Frames within Situations, all confined to one Principal's partition."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

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
        # ownership check is a partition-scoped read, not a bare existence read.
        owner = self._connection.execute(
            select(situations.c.situation_id).where(
                and_(
                    situations.c.situation_id == situation_id,
                    situations.c.principal_id == principal_id,
                )
            )
        ).one_or_none()
        if owner is None:
            raise UnknownScopeError
        frame_id = issue_identifier(IdKind.FRAME)
        now = utc_now()
        self._connection.execute(
            insert(frames).values(
                frame_id=frame_id,
                situation_id=situation_id,
                principal_id=principal_id,
                label=label,
                evidence_refs=list(evidence_refs),
                alternatives=list(alternatives),
                obligations=list(obligations),
                uncertainty=uncertainty,
                next_authority=next_authority,
                state=FrameState.CURRENT.value,
                created_at=now,
                updated_at=now,
            )
        )
        return Frame(
            frame_id=frame_id,
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

    def get_frames(self, principal_id: str, situation_id: str) -> tuple[Frame, ...]:
        rows = self._connection.execute(
            select(*frames.c)
            .where(
                and_(
                    frames.c.principal_id == principal_id,
                    frames.c.situation_id == situation_id,
                )
            )
            .order_by(frames.c.created_at.desc())
        ).all()
        return tuple(self._to_frame(row) for row in rows)

    @staticmethod
    def _to_frame(row: Row[Any]) -> Frame:
        mapping = row._mapping
        return Frame(
            frame_id=mapping["frame_id"],
            situation_id=mapping["situation_id"],
            principal_id=mapping["principal_id"],
            label=mapping["label"],
            state=FrameState(mapping["state"]),
            created_at=mapping["created_at"],
            updated_at=mapping["updated_at"],
            evidence_refs=_as_tuple(mapping["evidence_refs"]),
            alternatives=_as_tuple(mapping["alternatives"]),
            obligations=_as_tuple(mapping["obligations"]),
            uncertainty=mapping["uncertainty"],
            next_authority=mapping["next_authority"],
        )


class SqlTraceRepository(TraceRepository):
    """Traces: derived reconstructions, principal-scoped like everything else."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def record_trace(
        self,
        *,
        principal_id: str,
        object_id: str,
        object_type: str,
        time_range_start: datetime | None,
        time_range_end: datetime | None,
    ) -> Trace:
        trace_id = issue_identifier(IdKind.TRACE)
        now = utc_now()
        self._connection.execute(
            insert(traces).values(
                trace_id=trace_id,
                principal_id=principal_id,
                object_id=object_id,
                object_type=object_type,
                time_range_start=time_range_start,
                time_range_end=time_range_end,
                source_events=[],
                gaps=[],
                created_at=now,
            )
        )
        return Trace(
            trace_id=trace_id,
            principal_id=principal_id,
            object_id=object_id,
            object_type=object_type,
            created_at=now,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
        )

    def get_trace(self, principal_id: str, trace_id: str) -> Trace | None:
        row = self._connection.execute(
            select(*traces.c).where(
                and_(
                    traces.c.trace_id == trace_id,
                    traces.c.principal_id == principal_id,
                )
            )
        ).one_or_none()
        return None if row is None else self._to_trace(row)

    @staticmethod
    def _to_trace(row: Row[Any]) -> Trace:
        mapping = row._mapping
        return Trace(
            trace_id=mapping["trace_id"],
            principal_id=mapping["principal_id"],
            object_id=mapping["object_id"],
            object_type=mapping["object_type"],
            created_at=mapping["created_at"],
            time_range_start=mapping["time_range_start"],
            time_range_end=mapping["time_range_end"],
            source_events=_as_dict_tuple(mapping["source_events"]),
            gaps=_as_dict_tuple(mapping["gaps"]),
        )


class SqlProjectRepository(ProjectRepository):
    """Projects and the Project↔Situation link, principal-scoped throughout."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def add_project(
        self,
        *,
        principal_id: str,
        name: str,
        description: str | None,
        participants: tuple[str, ...],
    ) -> Project:
        project_id = issue_identifier(IdKind.PROJECT)
        now = utc_now()
        self._connection.execute(
            insert(projects).values(
                project_id=project_id,
                principal_id=principal_id,
                name=name,
                description=description,
                state=ProjectState.ACTIVE.value,
                participants=list(participants),
                opened_at=now,
                closed_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        return Project(
            project_id=project_id,
            principal_id=principal_id,
            name=name,
            state=ProjectState.ACTIVE,
            opened_at=now,
            created_at=now,
            updated_at=now,
            description=description,
            participants=tuple(participants),
        )

    def get_project(self, principal_id: str, project_id: str) -> Project | None:
        row = self._connection.execute(
            select(*projects.c).where(
                and_(
                    projects.c.project_id == project_id,
                    projects.c.principal_id == principal_id,
                )
            )
        ).one_or_none()
        return None if row is None else self._to_project(row)

    def list_projects(
        self, principal_id: str, state_filter: ProjectState | None = None
    ) -> tuple[Project, ...]:
        criteria = [projects.c.principal_id == principal_id]
        if state_filter is not None:
            criteria.append(projects.c.state == state_filter.value)
        rows = self._connection.execute(
            select(*projects.c).where(and_(*criteria)).order_by(projects.c.created_at.desc())
        ).all()
        return tuple(self._to_project(row) for row in rows)

    def link_situation(self, *, principal_id: str, project_id: str, situation_id: str) -> None:
        # Both the Project and the Situation must be in this Principal's
        # partition; a link may never bridge two Principals, and may never be
        # forged from a record the caller cannot see.
        owned_project = self._connection.execute(
            select(projects.c.project_id).where(
                and_(
                    projects.c.project_id == project_id,
                    projects.c.principal_id == principal_id,
                )
            )
        ).one_or_none()
        owned_situation = self._connection.execute(
            select(situations.c.situation_id).where(
                and_(
                    situations.c.situation_id == situation_id,
                    situations.c.principal_id == principal_id,
                )
            )
        ).one_or_none()
        if owned_project is None or owned_situation is None:
            raise UnknownScopeError
        # Idempotent per (project, situation): a repeated link is a no-op, which
        # is what `a_situation_links_to_a_project_once` expresses in the schema.
        self._connection.execute(
            pg_insert(project_situations)
            .values(
                project_situation_id=issue_identifier(IdKind.PROJECT_SITUATION),
                project_id=project_id,
                situation_id=situation_id,
                principal_id=principal_id,
                linked_at=utc_now(),
            )
            .on_conflict_do_nothing(constraint="a_situation_links_to_a_project_once")
        )

    @staticmethod
    def _to_project(row: Row[Any]) -> Project:
        mapping = row._mapping
        return Project(
            project_id=mapping["project_id"],
            principal_id=mapping["principal_id"],
            name=mapping["name"],
            state=ProjectState(mapping["state"]),
            opened_at=mapping["opened_at"],
            created_at=mapping["created_at"],
            updated_at=mapping["updated_at"],
            description=mapping["description"],
            participants=_as_tuple(mapping["participants"]),
            closed_at=mapping["closed_at"],
        )


class SqlRelationshipEventRepository(RelationshipEventRepository):
    """Relationship-timeline events; acceptance gates what Today/Pulse may read."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

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
        event_id = issue_identifier(IdKind.RELATIONSHIP_EVENT)
        now = utc_now()
        self._connection.execute(
            insert(relationship_events).values(
                event_id=event_id,
                principal_id=principal_id,
                person_id=person_id,
                event_type=event_type.value,
                occurred_at=occurred_at,
                context=context,
                accepted=accepted,
                source_ref=source_ref,
                created_at=now,
            )
        )
        return RelationshipEvent(
            event_id=event_id,
            principal_id=principal_id,
            person_id=person_id,
            event_type=event_type,
            occurred_at=occurred_at,
            created_at=now,
            context=context,
            accepted=accepted,
            source_ref=source_ref,
        )

    def list_events(self, principal_id: str, person_id: str) -> tuple[RelationshipEvent, ...]:
        rows = self._connection.execute(
            select(*relationship_events.c)
            .where(
                and_(
                    relationship_events.c.principal_id == principal_id,
                    relationship_events.c.person_id == person_id,
                )
            )
            .order_by(relationship_events.c.occurred_at.desc())
        ).all()
        return tuple(self._to_event(row) for row in rows)

    def list_accepted_events(self, principal_id: str) -> tuple[RelationshipEvent, ...]:
        # The accepted-timeline read: `accepted` true is added to the partition
        # predicate, so a proposed event is structurally excluded here.
        rows = self._connection.execute(
            select(*relationship_events.c)
            .where(
                and_(
                    relationship_events.c.principal_id == principal_id,
                    relationship_events.c.accepted.is_(True),
                )
            )
            .order_by(relationship_events.c.occurred_at.desc())
        ).all()
        return tuple(self._to_event(row) for row in rows)

    @staticmethod
    def _to_event(row: Row[Any]) -> RelationshipEvent:
        mapping = row._mapping
        return RelationshipEvent(
            event_id=mapping["event_id"],
            principal_id=mapping["principal_id"],
            person_id=mapping["person_id"],
            event_type=RelationshipEventType(mapping["event_type"]),
            occurred_at=mapping["occurred_at"],
            created_at=mapping["created_at"],
            context=mapping["context"],
            accepted=mapping["accepted"],
            source_ref=mapping["source_ref"],
        )


class SqlPulseRepository(PulseRepository):
    """Pulse: derived attention recommendations, read only from accepted state."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def generate_pulse(self, principal_id: str) -> tuple[PulseItem, ...]:
        # The three predicates are the WP-06 read contract: this Principal's
        # partition, `accepted_only` true (Today/Pulse read only accepted
        # records), and not dismissed. Highest priority (largest rank) first,
        # ties broken by most recently generated.
        rows = self._connection.execute(
            select(*pulse_items.c)
            .where(
                and_(
                    pulse_items.c.principal_id == principal_id,
                    pulse_items.c.accepted_only.is_(True),
                    pulse_items.c.dismissed_at.is_(None),
                )
            )
            .order_by(
                pulse_items.c.priority.desc(),
                pulse_items.c.generated_at.desc(),
            )
        ).all()
        return tuple(self._to_pulse_item(row) for row in rows)

    def dismiss_pulse_item(self, principal_id: str, pulse_id: str) -> None:
        result = self._connection.execute(
            update(pulse_items)
            .where(
                and_(
                    pulse_items.c.pulse_id == pulse_id,
                    pulse_items.c.principal_id == principal_id,
                )
            )
            .values(dismissed_at=utc_now())
            .returning(pulse_items.c.pulse_id)
        ).one_or_none()
        if result is None:
            raise UnknownScopeError

    @staticmethod
    def _to_pulse_item(row: Row[Any]) -> PulseItem:
        mapping = row._mapping
        return PulseItem(
            pulse_id=mapping["pulse_id"],
            principal_id=mapping["principal_id"],
            item_type=PulseItemType(mapping["item_type"]),
            item_ref=mapping["item_ref"],
            reason=mapping["reason"],
            generated_at=mapping["generated_at"],
            consequence=mapping["consequence"],
            next_step=mapping["next_step"],
            priority=mapping["priority"],
            accepted_only=mapping["accepted_only"],
            dismissed_at=mapping["dismissed_at"],
        )
