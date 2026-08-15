"""Principal-scoped persistence for the R5 continuity surface (WP-06, WP-11).

Seven concrete repositories back the situation/frame/trace/project/relationship-
event/pulse/continuity ports declared in `contracts.ports` — the six WP-06
declared, and `SqlContinuityRepository`, which WP-11 adds for the commitments,
decisions and tasks R5 named and had no table for, together with the append-only
lifecycle record that carries their closures and their associations. They share
one discipline that is the whole point of both work packages:

**Every read filters by `principal_id` and every write stamps it.** WP-06's
acceptance criteria require that relationship records and timelines are
principal-scoped end to end, that a cross-principal read returns nothing rather
than another Principal's record, and that no shared-identity record is legible
across Principals. The partition is therefore not a policy layered on top — it
is a predicate on every `SELECT` and a value on every `INSERT` in this module.
A `situation_id` (or any other identifier) that belongs to another Principal is
indistinguishable here from one that does not exist: the lookup adds
`principal_id == <caller>` and finds nothing.

`PulseRepository.derive_pulse` carries the second criterion — "Today/Pulse read
only accepted records" — at the boundary that can enforce it: every one of its
four selects adds `evidence_state = 'accepted'` to the partition predicate, so a
proposal is excluded by the server rather than by the caller. It writes nothing;
`tests/architecture/test_derivation_proposes_and_never_promotes.py` holds that
structurally and `tests/database/test_continuity_isolation.py` measures it.
`SqlContinuityRepository.accept` is the one path to `accepted`, and it first
resolves a `capture_review_decisions` row in the caller's own partition whose
disposition accepted something — so a derivation cannot promote its own output.

`PulseRepository.generate_pulse` carries the same criterion over *stored* rows.
It reads only rows whose `accepted_only` is true (which
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

from sqlalchemy import Column, Table, and_, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Row

from my_pa.contracts.ports import (
    ContinuityRepository,
    FrameRepository,
    ProjectRepository,
    PulseRepository,
    RelationshipEventRepository,
    SituationRepository,
    TraceRepository,
    UnknownScopeError,
)
from my_pa.domain.capture.review import Disposition
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import utc_now
from my_pa.domain.relationship.event import RelationshipEvent, RelationshipEventType
from my_pa.domain.situation.continuity import (
    ClosureEvidenceKind,
    Commitment,
    CommitmentDirection,
    CommitmentState,
    ContinuityAcceptanceKind,
    ContinuityEvidenceState,
    ContinuityLifecycleEvent,
    ContinuityObjectKind,
    Decision,
    DecisionState,
    LifecycleTransition,
    Task,
    TaskState,
)
from my_pa.domain.situation.pulse_derivation import FramedObligation, derive_pulse
from my_pa.domain.situation.situation import (
    Frame,
    FrameState,
    Project,
    ProjectState,
    PulseItem,
    PulseItemType,
    PulseReasonCode,
    Situation,
    SituationState,
    Trace,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.tables import (
    capture_review_decisions,
    commitments,
    continuity_lifecycle_events,
    decisions,
    frames,
    project_situations,
    projects,
    pulse_items,
    relationship_events,
    situations,
    tasks,
    traces,
)

__all__ = [
    "SqlContinuityRepository",
    "SqlFrameRepository",
    "SqlProjectRepository",
    "SqlPulseRepository",
    "SqlRelationshipEventRepository",
    "SqlSituationRepository",
    "SqlTraceRepository",
]

#: The dispositions that accepted something. `accept` and `correct_and_accept`
#: and nothing else: a deferred, rejected, escalated or reprocessed decision
#: promoted no proposal, and admitting one here would make "passed Review" mean
#: "was looked at".
_ACCEPTING_DISPOSITIONS: tuple[str, ...] = (
    Disposition.ACCEPT.value,
    Disposition.CORRECT_AND_ACCEPT.value,
)


#: Which table each continuity object kind lives in, and its identity column.
#: A closed map rather than a name a caller could pass: nothing outside this
#: module can name a table, so `object_kind` is a vocabulary and not a lever.
_OBJECT_TABLE: dict[ContinuityObjectKind, tuple[Table, Column[str]]] = {
    ContinuityObjectKind.COMMITMENT: (commitments, commitments.c.commitment_id),
    ContinuityObjectKind.DECISION: (decisions, decisions.c.decision_id),
    ContinuityObjectKind.TASK: (tasks, tasks.c.task_id),
    ContinuityObjectKind.SITUATION: (situations, situations.c.situation_id),
    ContinuityObjectKind.PROJECT: (projects, projects.c.project_id),
}

#: The kinds that carry a project/situation association of their own. A
#: Situation's association to a Project is the `project_situations` link and is
#: made through `SqlProjectRepository.link_situation`; a Project belongs to
#: nothing above it.
_ASSOCIABLE: frozenset[ContinuityObjectKind] = frozenset(
    {ContinuityObjectKind.COMMITMENT, ContinuityObjectKind.DECISION, ContinuityObjectKind.TASK}
)


def _append_lifecycle_event(
    connection: Connection,
    *,
    principal_id: str,
    object_kind: ContinuityObjectKind,
    object_id: str,
    transition: LifecycleTransition,
    evidence_kind: ClosureEvidenceKind,
    evidence_ref: str | None,
    occurred_at: datetime,
    recorded_at: datetime,
) -> str:
    """Append one lifecycle row on the caller's connection, and return its id.

    **On the caller's connection**, which is the whole of the same-transaction
    guarantee: the state change and this row are written inside the unit of work
    the caller opened, so a closure whose evidence did not commit closed nothing.
    The server refuses a `closed` or `associated` row with a blank `evidence_ref`
    (`a_closed_transition_carries_evidence`, `an_association_carries_evidence`),
    so the guarantee does not rest on this function remembering to check.
    """
    event_id = issue_identifier(IdKind.LIFECYCLE_EVENT)
    connection.execute(
        insert(continuity_lifecycle_events).values(
            event_id=event_id,
            principal_id=principal_id,
            object_kind=object_kind.value,
            object_id=object_id,
            transition=transition.value,
            evidence_kind=evidence_kind.value,
            evidence_ref=evidence_ref,
            occurred_at=occurred_at,
            recorded_at=recorded_at,
        )
    )
    return event_id


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

    def close_situation(
        self,
        *,
        principal_id: str,
        situation_id: str,
        outcome: str,
        evidence_kind: ClosureEvidenceKind,
        evidence_ref: str,
    ) -> Situation:
        """Close one Situation and append the evidence that closed it, atomically.

        **The evidence is required (WP-11) and it is written on this connection.**
        Before this package a Situation closed by flipping `state` and recording
        an outcome sentence, which is a status field changing with no trace: a
        reader six months later had the word "resolved" and nothing to open. The
        `closed` row in `continuity_lifecycle_events` is written inside the
        caller's transaction, so a close whose evidence did not commit did not
        close anything, and the server refuses the row outright if the reference
        is blank.
        """
        if not evidence_ref.strip():
            raise ValueError("closing a situation records the evidence that closed it")
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
        _append_lifecycle_event(
            self._connection,
            principal_id=principal_id,
            object_kind=ContinuityObjectKind.SITUATION,
            object_id=situation_id,
            transition=LifecycleTransition.CLOSED,
            evidence_kind=evidence_kind,
            evidence_ref=evidence_ref,
            occurred_at=now,
            recorded_at=now,
        )
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

    def link_situation(
        self,
        *,
        principal_id: str,
        project_id: str,
        situation_id: str,
        evidence_kind: ClosureEvidenceKind,
        evidence_ref: str,
    ) -> None:
        """Bind a Situation into a Project, citing what justified the binding.

        **The evidence is required (WP-11).** A link row on its own says a
        Situation belongs to a Project and says nothing about why, so
        reconstructing the association meant inferring it. The reference is now
        stored on the link *and* appended as an `associated` row in
        `continuity_lifecycle_events`, in the caller's transaction, so the answer
        to "why does this belong here" is a row rather than an inference.
        """
        if not evidence_ref.strip():
            raise ValueError("linking a situation to a project records the evidence for it")
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
        now = utc_now()
        created = self._connection.execute(
            pg_insert(project_situations)
            .values(
                project_situation_id=issue_identifier(IdKind.PROJECT_SITUATION),
                project_id=project_id,
                situation_id=situation_id,
                principal_id=principal_id,
                linked_at=now,
                association_evidence_ref=evidence_ref,
            )
            .on_conflict_do_nothing(constraint="a_situation_links_to_a_project_once")
            .returning(project_situations.c.project_situation_id)
        ).one_or_none()
        if created is None:
            # The link already stood. Appending a second `associated` row would
            # claim a second act of association that did not happen.
            return
        _append_lifecycle_event(
            self._connection,
            principal_id=principal_id,
            object_kind=ContinuityObjectKind.SITUATION,
            object_id=situation_id,
            transition=LifecycleTransition.ASSOCIATED,
            evidence_kind=evidence_kind,
            evidence_ref=evidence_ref,
            occurred_at=now,
            recorded_at=now,
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

    def derive_pulse(self, principal_id: str, now: datetime) -> tuple[PulseItem, ...]:
        """Derive the Pulse from accepted continuity. **Reads only.**

        Four `SELECT`s and nothing else. Every one carries `principal_id` and,
        for the three object tables, `evidence_state = 'accepted'` — so the
        acceptance filter is a predicate the server applies rather than a
        condition the caller is trusted to have applied. The rows go to
        `domain.situation.pulse_derivation.derive_pulse`, which is a pure
        function over them.

        There is no `INSERT`, `UPDATE` or `DELETE` in this method and there must
        never be one: a derivation that wrote its own output back as accepted
        state would be automatic consequential promotion arriving through a
        listing, which is the failure `QC-AC-020` names and the one nobody looks
        for in a read path.
        """
        accepted = ContinuityEvidenceState.ACCEPTED.value
        commitment_rows = self._connection.execute(
            select(*commitments.c).where(
                and_(
                    commitments.c.principal_id == principal_id,
                    commitments.c.evidence_state == accepted,
                    commitments.c.state == CommitmentState.OPEN.value,
                )
            )
        ).all()
        task_rows = self._connection.execute(
            select(*tasks.c).where(
                and_(
                    tasks.c.principal_id == principal_id,
                    tasks.c.evidence_state == accepted,
                    tasks.c.state == TaskState.OPEN.value,
                )
            )
        ).all()
        decision_rows = self._connection.execute(
            select(*decisions.c).where(
                and_(
                    decisions.c.principal_id == principal_id,
                    decisions.c.evidence_state == accepted,
                    decisions.c.state == DecisionState.OPEN.value,
                )
            )
        ).all()
        # Obligations standing on the *current* frame of a Situation that is
        # still running. Both sides of the join carry the partition predicate, so
        # the join cannot be the place the partition is lost.
        obligation_rows = self._connection.execute(
            select(
                frames.c.situation_id,
                frames.c.frame_id,
                func.jsonb_array_length(frames.c.obligations).label("obligation_count"),
            )
            .select_from(
                frames.join(
                    situations,
                    and_(
                        situations.c.situation_id == frames.c.situation_id,
                        situations.c.principal_id == frames.c.principal_id,
                    ),
                )
            )
            .where(
                and_(
                    frames.c.principal_id == principal_id,
                    frames.c.state == FrameState.CURRENT.value,
                    situations.c.state.in_(
                        (SituationState.OPEN.value, SituationState.ACTIVE.value)
                    ),
                    func.jsonb_array_length(frames.c.obligations) > 0,
                )
            )
        ).all()
        dismissed = frozenset(
            self._connection.execute(
                select(pulse_items.c.pulse_id).where(
                    and_(
                        pulse_items.c.principal_id == principal_id,
                        pulse_items.c.dismissed_at.is_not(None),
                    )
                )
            ).scalars()
        )
        return derive_pulse(
            principal_id=principal_id,
            now=now,
            commitments=[SqlContinuityRepository._to_commitment(row) for row in commitment_rows],
            tasks=[SqlContinuityRepository._to_task(row) for row in task_rows],
            decisions=[SqlContinuityRepository._to_decision(row) for row in decision_rows],
            obligations=[
                FramedObligation(
                    situation_id=row._mapping["situation_id"],
                    frame_id=row._mapping["frame_id"],
                    obligation_count=row._mapping["obligation_count"],
                )
                for row in obligation_rows
            ],
            dismissed_pulse_ids=dismissed,
        )

    @staticmethod
    def _to_pulse_item(row: Row[Any]) -> PulseItem:
        mapping = row._mapping
        return PulseItem(
            pulse_id=mapping["pulse_id"],
            principal_id=mapping["principal_id"],
            item_type=PulseItemType(mapping["item_type"]),
            item_ref=mapping["item_ref"],
            reason=mapping["reason"],
            reason_code=PulseReasonCode(mapping["reason_code"]),
            basis_refs=_as_tuple(mapping["basis_refs"]),
            generated_at=mapping["generated_at"],
            consequence=mapping["consequence"],
            next_step=mapping["next_step"],
            priority=mapping["priority"],
            accepted_only=mapping["accepted_only"],
            dismissed_at=mapping["dismissed_at"],
        )


class SqlContinuityRepository(ContinuityRepository):
    """Commitments, Decisions, Tasks, and their append-only lifecycle record.

    Every statement in this class carries `principal_id`. A read for an object
    another Principal owns adds the predicate and finds nothing; a write against
    one matches no row and raises `UnknownScopeError`, which is the port
    vocabulary's `not_found` — a cross-principal reference is answered exactly the
    way a genuinely absent one is, so this class cannot be used to discover that
    somebody else's commitment exists.

    **`propose_*` cannot produce accepted continuity.** The three insert
    `evidence_state = 'proposed'` as a literal and take no parameter that could
    change it. `accept` is the only path to `'accepted'`, and it first resolves a
    `capture_review_decisions` row in the caller's own partition whose disposition
    accepted something — so promotion requires a review that happened, and a
    derivation holding this repository cannot promote its own output.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    # --- proposing -------------------------------------------------------

    def propose_commitment(
        self,
        *,
        principal_id: str,
        counterparty_person_id: str,
        direction: CommitmentDirection,
        summary: str,
        origin_evidence_ref: str,
        origin_evidence_kind: ClosureEvidenceKind,
        due_at: datetime | None = None,
        project_id: str | None = None,
        situation_id: str | None = None,
    ) -> Commitment:
        commitment_id = issue_identifier(IdKind.COMMITMENT)
        now = utc_now()
        self._connection.execute(
            insert(commitments).values(
                commitment_id=commitment_id,
                principal_id=principal_id,
                counterparty_person_id=counterparty_person_id,
                direction=direction.value,
                summary=summary,
                state=CommitmentState.OPEN.value,
                # A literal, not a parameter. There is no argument a caller can
                # pass that makes this row accepted.
                evidence_state=ContinuityEvidenceState.PROPOSED.value,
                origin_evidence_ref=origin_evidence_ref,
                project_id=project_id,
                situation_id=situation_id,
                due_at=due_at,
                opened_at=now,
                closed_at=None,
                closure_evidence_ref=None,
                accepted_by_review_decision_id=None,
                created_at=now,
                updated_at=now,
            )
        )
        _append_lifecycle_event(
            self._connection,
            principal_id=principal_id,
            object_kind=ContinuityObjectKind.COMMITMENT,
            object_id=commitment_id,
            transition=LifecycleTransition.OPENED,
            evidence_kind=origin_evidence_kind,
            evidence_ref=origin_evidence_ref,
            occurred_at=now,
            recorded_at=now,
        )
        self._record_associations(
            principal_id=principal_id,
            object_kind=ContinuityObjectKind.COMMITMENT,
            object_id=commitment_id,
            project_id=project_id,
            situation_id=situation_id,
            evidence_kind=origin_evidence_kind,
            evidence_ref=origin_evidence_ref,
            at=now,
        )
        return Commitment(
            commitment_id=commitment_id,
            principal_id=principal_id,
            counterparty_person_id=counterparty_person_id,
            direction=direction,
            summary=summary,
            state=CommitmentState.OPEN,
            evidence_state=ContinuityEvidenceState.PROPOSED,
            origin_evidence_ref=origin_evidence_ref,
            opened_at=now,
            created_at=now,
            updated_at=now,
            due_at=due_at,
            project_id=project_id,
            situation_id=situation_id,
        )

    def propose_decision(
        self,
        *,
        principal_id: str,
        question: str,
        origin_evidence_ref: str,
        origin_evidence_kind: ClosureEvidenceKind,
        awaiting_authority_ref: str | None = None,
        project_id: str | None = None,
        situation_id: str | None = None,
    ) -> Decision:
        decision_id = issue_identifier(IdKind.CONTINUITY_DECISION)
        now = utc_now()
        self._connection.execute(
            insert(decisions).values(
                decision_id=decision_id,
                principal_id=principal_id,
                question=question,
                state=DecisionState.OPEN.value,
                evidence_state=ContinuityEvidenceState.PROPOSED.value,
                origin_evidence_ref=origin_evidence_ref,
                awaiting_authority_ref=awaiting_authority_ref,
                project_id=project_id,
                situation_id=situation_id,
                opened_at=now,
                closed_at=None,
                closure_evidence_ref=None,
                accepted_by_review_decision_id=None,
                outcome=None,
                created_at=now,
                updated_at=now,
            )
        )
        _append_lifecycle_event(
            self._connection,
            principal_id=principal_id,
            object_kind=ContinuityObjectKind.DECISION,
            object_id=decision_id,
            transition=LifecycleTransition.OPENED,
            evidence_kind=origin_evidence_kind,
            evidence_ref=origin_evidence_ref,
            occurred_at=now,
            recorded_at=now,
        )
        self._record_associations(
            principal_id=principal_id,
            object_kind=ContinuityObjectKind.DECISION,
            object_id=decision_id,
            project_id=project_id,
            situation_id=situation_id,
            evidence_kind=origin_evidence_kind,
            evidence_ref=origin_evidence_ref,
            at=now,
        )
        return Decision(
            decision_id=decision_id,
            principal_id=principal_id,
            question=question,
            state=DecisionState.OPEN,
            evidence_state=ContinuityEvidenceState.PROPOSED,
            origin_evidence_ref=origin_evidence_ref,
            opened_at=now,
            created_at=now,
            updated_at=now,
            awaiting_authority_ref=awaiting_authority_ref,
            project_id=project_id,
            situation_id=situation_id,
        )

    def propose_task(
        self,
        *,
        principal_id: str,
        title: str,
        origin_evidence_ref: str,
        origin_evidence_kind: ClosureEvidenceKind,
        due_at: datetime | None = None,
        project_id: str | None = None,
        situation_id: str | None = None,
    ) -> Task:
        task_id = issue_identifier(IdKind.TASK)
        now = utc_now()
        self._connection.execute(
            insert(tasks).values(
                task_id=task_id,
                principal_id=principal_id,
                title=title,
                state=TaskState.OPEN.value,
                evidence_state=ContinuityEvidenceState.PROPOSED.value,
                origin_evidence_ref=origin_evidence_ref,
                project_id=project_id,
                situation_id=situation_id,
                due_at=due_at,
                opened_at=now,
                closed_at=None,
                closure_evidence_ref=None,
                accepted_by_review_decision_id=None,
                created_at=now,
                updated_at=now,
            )
        )
        _append_lifecycle_event(
            self._connection,
            principal_id=principal_id,
            object_kind=ContinuityObjectKind.TASK,
            object_id=task_id,
            transition=LifecycleTransition.OPENED,
            evidence_kind=origin_evidence_kind,
            evidence_ref=origin_evidence_ref,
            occurred_at=now,
            recorded_at=now,
        )
        self._record_associations(
            principal_id=principal_id,
            object_kind=ContinuityObjectKind.TASK,
            object_id=task_id,
            project_id=project_id,
            situation_id=situation_id,
            evidence_kind=origin_evidence_kind,
            evidence_ref=origin_evidence_ref,
            at=now,
        )
        return Task(
            task_id=task_id,
            principal_id=principal_id,
            title=title,
            state=TaskState.OPEN,
            evidence_state=ContinuityEvidenceState.PROPOSED,
            origin_evidence_ref=origin_evidence_ref,
            opened_at=now,
            created_at=now,
            updated_at=now,
            due_at=due_at,
            project_id=project_id,
            situation_id=situation_id,
        )

    # --- the acceptance gate ---------------------------------------------

    def accept(
        self,
        *,
        principal_id: str,
        object_kind: ContinuityObjectKind,
        object_id: str,
        review_decision_id: str,
    ) -> None:
        """Promote one proposal, and only on a review decision that accepted.

        Two partitioned reads and one partitioned write. The review decision must
        exist **in this Principal's partition** and must have accepted something;
        a rejection, a deferral, another Principal's decision, and a well-formed
        identifier naming nothing are all answered identically, as
        `UnknownScopeError`, and the object stays a proposal.
        """
        table, id_column = _OBJECT_TABLE[object_kind]
        decided = self._connection.execute(
            select(capture_review_decisions.c.decision_id).where(
                and_(
                    capture_review_decisions.c.decision_id == review_decision_id,
                    capture_review_decisions.c.principal_id == principal_id,
                    capture_review_decisions.c.disposition.in_(_ACCEPTING_DISPOSITIONS),
                )
            )
        ).one_or_none()
        if decided is None:
            raise UnknownScopeError
        promoted = self._connection.execute(
            update(table)
            .where(
                and_(
                    id_column == object_id,
                    table.c.principal_id == principal_id,
                    table.c.evidence_state == ContinuityEvidenceState.PROPOSED.value,
                )
            )
            .values(
                evidence_state=ContinuityEvidenceState.ACCEPTED.value,
                accepted_by_review_decision_id=review_decision_id,
                updated_at=utc_now(),
                **(
                    {"acceptance_kind": ContinuityAcceptanceKind.REVIEW.value}
                    if "acceptance_kind" in table.c
                    else {}
                ),
            )
            .returning(id_column)
        ).one_or_none()
        if promoted is None:
            raise UnknownScopeError

    # --- closure with evidence -------------------------------------------

    def close(
        self,
        *,
        principal_id: str,
        object_kind: ContinuityObjectKind,
        object_id: str,
        evidence_kind: ClosureEvidenceKind,
        evidence_ref: str,
        occurred_at: datetime,
    ) -> None:
        if not evidence_ref.strip():
            raise ValueError("closing a continuity object records the evidence that closed it")
        table, id_column = _OBJECT_TABLE[object_kind]
        now = utc_now()
        values: dict[str, Any] = {"state": "closed", "closed_at": now, "updated_at": now}
        if "closure_evidence_ref" in table.c:
            values["closure_evidence_ref"] = evidence_ref
        closed = self._connection.execute(
            update(table)
            .where(
                and_(
                    id_column == object_id,
                    table.c.principal_id == principal_id,
                    table.c.state != "closed",
                )
            )
            .values(**values)
            .returning(id_column)
        ).one_or_none()
        if closed is None:
            raise UnknownScopeError
        _append_lifecycle_event(
            self._connection,
            principal_id=principal_id,
            object_kind=object_kind,
            object_id=object_id,
            transition=LifecycleTransition.CLOSED,
            evidence_kind=evidence_kind,
            evidence_ref=evidence_ref,
            occurred_at=occurred_at,
            recorded_at=now,
        )

    # --- associations -----------------------------------------------------

    def associate(
        self,
        *,
        principal_id: str,
        object_kind: ContinuityObjectKind,
        object_id: str,
        project_id: str | None,
        situation_id: str | None,
        evidence_kind: ClosureEvidenceKind,
        evidence_ref: str,
    ) -> None:
        if not evidence_ref.strip():
            raise ValueError("an association records the evidence that justifies it")
        if project_id is None and situation_id is None:
            raise ValueError("an association names a project, a situation, or both")
        if object_kind not in _ASSOCIABLE:
            raise ValueError("only a commitment, decision or task carries an association here")
        table, id_column = _OBJECT_TABLE[object_kind]
        self._require_owned_context(principal_id, project_id, situation_id)
        values: dict[str, Any] = {"updated_at": utc_now()}
        if project_id is not None:
            values["project_id"] = project_id
        if situation_id is not None:
            values["situation_id"] = situation_id
        bound = self._connection.execute(
            update(table)
            .where(and_(id_column == object_id, table.c.principal_id == principal_id))
            .values(**values)
            .returning(id_column)
        ).one_or_none()
        if bound is None:
            raise UnknownScopeError
        self._record_associations(
            principal_id=principal_id,
            object_kind=object_kind,
            object_id=object_id,
            project_id=project_id,
            situation_id=situation_id,
            evidence_kind=evidence_kind,
            evidence_ref=evidence_ref,
            at=utc_now(),
        )

    def _require_owned_context(
        self, principal_id: str, project_id: str | None, situation_id: str | None
    ) -> None:
        """Both ends of an association live in the caller's partition, or neither does."""
        if project_id is not None:
            owned = self._connection.execute(
                select(projects.c.project_id).where(
                    and_(
                        projects.c.project_id == project_id,
                        projects.c.principal_id == principal_id,
                    )
                )
            ).one_or_none()
            if owned is None:
                raise UnknownScopeError
        if situation_id is not None:
            owned_situation = self._connection.execute(
                select(situations.c.situation_id).where(
                    and_(
                        situations.c.situation_id == situation_id,
                        situations.c.principal_id == principal_id,
                    )
                )
            ).one_or_none()
            if owned_situation is None:
                raise UnknownScopeError

    def _record_associations(
        self,
        *,
        principal_id: str,
        object_kind: ContinuityObjectKind,
        object_id: str,
        project_id: str | None,
        situation_id: str | None,
        evidence_kind: ClosureEvidenceKind,
        evidence_ref: str,
        at: datetime,
    ) -> None:
        """One `associated` row per context the object was bound to, with evidence.

        **`evidence_ref` carries the context and the justification together**, as
        `<context_id>|<evidence_ref>`, and that is a deliberate shape rather than
        an encoding accident. `continuity_lifecycle_events` has no `context_id`
        column and gains none here: adding one would make the table's meaning
        depend on the transition — populated for `associated`, meaningless for
        `opened` and `closed` — and a column that means nothing in two of three
        cases is a column a reader has to guess about. The pair is what an
        association *is*: this object, bound to that context, because of this.
        A reader recovers both halves by splitting on the one separator, which no
        opaque identifier can contain.
        """
        for context in (project_id, situation_id):
            if context is None:
                continue
            _append_lifecycle_event(
                self._connection,
                principal_id=principal_id,
                object_kind=object_kind,
                object_id=object_id,
                transition=LifecycleTransition.ASSOCIATED,
                evidence_kind=evidence_kind,
                evidence_ref=f"{context}|{evidence_ref}",
                occurred_at=at,
                recorded_at=at,
            )

    def association_evidence(
        self, principal_id: str, object_id: str
    ) -> tuple[ContinuityLifecycleEvent, ...]:
        return tuple(
            event
            for event in self.lifecycle_events(principal_id, object_id)
            if event.transition is LifecycleTransition.ASSOCIATED
        )

    def lifecycle_events(
        self, principal_id: str, object_id: str
    ) -> tuple[ContinuityLifecycleEvent, ...]:
        rows = self._connection.execute(
            select(*continuity_lifecycle_events.c)
            .where(
                and_(
                    continuity_lifecycle_events.c.principal_id == principal_id,
                    continuity_lifecycle_events.c.object_id == object_id,
                )
            )
            .order_by(
                continuity_lifecycle_events.c.recorded_at.asc(),
                continuity_lifecycle_events.c.event_id.asc(),
            )
        ).all()
        return tuple(self._to_lifecycle_event(row) for row in rows)

    # --- reads -------------------------------------------------------------

    def get_commitment(self, principal_id: str, commitment_id: str) -> Commitment | None:
        row = self._connection.execute(
            select(*commitments.c).where(
                and_(
                    commitments.c.commitment_id == commitment_id,
                    commitments.c.principal_id == principal_id,
                )
            )
        ).one_or_none()
        return None if row is None else self._to_commitment(row)

    def get_decision(self, principal_id: str, decision_id: str) -> Decision | None:
        row = self._connection.execute(
            select(*decisions.c).where(
                and_(
                    decisions.c.decision_id == decision_id,
                    decisions.c.principal_id == principal_id,
                )
            )
        ).one_or_none()
        return None if row is None else self._to_decision(row)

    def get_task(self, principal_id: str, task_id: str) -> Task | None:
        row = self._connection.execute(
            select(*tasks.c).where(
                and_(tasks.c.task_id == task_id, tasks.c.principal_id == principal_id)
            )
        ).one_or_none()
        return None if row is None else self._to_task(row)

    def list_commitments(
        self, principal_id: str, evidence_state: ContinuityEvidenceState | None = None
    ) -> tuple[Commitment, ...]:
        criteria = [commitments.c.principal_id == principal_id]
        if evidence_state is not None:
            criteria.append(commitments.c.evidence_state == evidence_state.value)
        rows = self._connection.execute(
            select(*commitments.c).where(and_(*criteria)).order_by(commitments.c.commitment_id)
        ).all()
        return tuple(self._to_commitment(row) for row in rows)

    def list_decisions(
        self, principal_id: str, evidence_state: ContinuityEvidenceState | None = None
    ) -> tuple[Decision, ...]:
        criteria = [decisions.c.principal_id == principal_id]
        if evidence_state is not None:
            criteria.append(decisions.c.evidence_state == evidence_state.value)
        rows = self._connection.execute(
            select(*decisions.c).where(and_(*criteria)).order_by(decisions.c.decision_id)
        ).all()
        return tuple(self._to_decision(row) for row in rows)

    def list_tasks(
        self, principal_id: str, evidence_state: ContinuityEvidenceState | None = None
    ) -> tuple[Task, ...]:
        criteria = [tasks.c.principal_id == principal_id]
        if evidence_state is not None:
            criteria.append(tasks.c.evidence_state == evidence_state.value)
        rows = self._connection.execute(
            select(*tasks.c).where(and_(*criteria)).order_by(tasks.c.task_id)
        ).all()
        return tuple(self._to_task(row) for row in rows)

    # --- row mapping -------------------------------------------------------

    @staticmethod
    def _to_commitment(row: Row[Any]) -> Commitment:
        mapping = row._mapping
        return Commitment(
            commitment_id=mapping["commitment_id"],
            principal_id=mapping["principal_id"],
            counterparty_person_id=mapping["counterparty_person_id"],
            direction=CommitmentDirection(mapping["direction"]),
            summary=mapping["summary"],
            state=CommitmentState(mapping["state"]),
            evidence_state=ContinuityEvidenceState(mapping["evidence_state"]),
            origin_evidence_ref=mapping["origin_evidence_ref"],
            opened_at=mapping["opened_at"],
            created_at=mapping["created_at"],
            updated_at=mapping["updated_at"],
            due_at=mapping["due_at"],
            project_id=mapping["project_id"],
            situation_id=mapping["situation_id"],
            closed_at=mapping["closed_at"],
            closure_evidence_ref=mapping["closure_evidence_ref"],
            accepted_by_review_decision_id=mapping["accepted_by_review_decision_id"],
        )

    @staticmethod
    def _to_decision(row: Row[Any]) -> Decision:
        mapping = row._mapping
        return Decision(
            decision_id=mapping["decision_id"],
            principal_id=mapping["principal_id"],
            question=mapping["question"],
            state=DecisionState(mapping["state"]),
            evidence_state=ContinuityEvidenceState(mapping["evidence_state"]),
            origin_evidence_ref=mapping["origin_evidence_ref"],
            opened_at=mapping["opened_at"],
            created_at=mapping["created_at"],
            updated_at=mapping["updated_at"],
            awaiting_authority_ref=mapping["awaiting_authority_ref"],
            project_id=mapping["project_id"],
            situation_id=mapping["situation_id"],
            closed_at=mapping["closed_at"],
            closure_evidence_ref=mapping["closure_evidence_ref"],
            outcome=mapping["outcome"],
            accepted_by_review_decision_id=mapping["accepted_by_review_decision_id"],
        )

    @staticmethod
    def _to_task(row: Row[Any]) -> Task:
        mapping = row._mapping
        return Task(
            task_id=mapping["task_id"],
            principal_id=mapping["principal_id"],
            title=mapping["title"],
            state=TaskState(mapping["state"]),
            evidence_state=ContinuityEvidenceState(mapping["evidence_state"]),
            origin_evidence_ref=mapping["origin_evidence_ref"],
            opened_at=mapping["opened_at"],
            created_at=mapping["created_at"],
            updated_at=mapping["updated_at"],
            due_at=mapping["due_at"],
            project_id=mapping["project_id"],
            situation_id=mapping["situation_id"],
            closed_at=mapping["closed_at"],
            closure_evidence_ref=mapping["closure_evidence_ref"],
            accepted_by_review_decision_id=mapping["accepted_by_review_decision_id"],
            acceptance_kind=(
                ContinuityAcceptanceKind(mapping["acceptance_kind"])
                if mapping.get("acceptance_kind") is not None
                else None
            ),
        )

    @staticmethod
    def _to_lifecycle_event(row: Row[Any]) -> ContinuityLifecycleEvent:
        mapping = row._mapping
        return ContinuityLifecycleEvent(
            event_id=mapping["event_id"],
            principal_id=mapping["principal_id"],
            object_kind=ContinuityObjectKind(mapping["object_kind"]),
            object_id=mapping["object_id"],
            transition=LifecycleTransition(mapping["transition"]),
            evidence_kind=ClosureEvidenceKind(mapping["evidence_kind"]),
            occurred_at=mapping["occurred_at"],
            recorded_at=mapping["recorded_at"],
            evidence_ref=mapping["evidence_ref"],
        )
