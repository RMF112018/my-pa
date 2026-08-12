"""The R5 continuity use cases: Situation, Frame, Trace, Project, Pulse (WP-06).

`SituationService` is a standalone application service in the same shape as the
fixture-only `RelationshipService`: each method takes the repository it operates
through and one continuity command, unpacks the command, and calls the port with
plain arguments. It is deliberately *not* wired behind `ApplicationService.invoke`
— the continuity commands carry their Principal explicitly (see the WP-06 section
of `application.commands`), and every port stamps and filters by that Principal,
so the partition is enforced at the persistence boundary rather than by a shared
authorization gate.

The service holds no state and issues no identifiers: identity is minted
server-side by the concrete repository, and the Principal travels in the command
as a resolved partition, never as a caller-supplied identity. The whole of the
principal-scoping guarantee therefore lives in the repository — this layer only
routes a command to the one port that answers it.

`link_situation_to_project` is the one method that touches two ports. It resolves
the link through the `ProjectRepository`, which owns the `project_situations`
link table; the `SituationRepository` is passed so a caller cannot link a
Situation it does not hold a reference to, and both the Project and the Situation
must live in the command's Principal partition for the link to be created.
"""

from __future__ import annotations

from my_pa.application.commands import (
    AddProjectCommand,
    CloseSituationCommand,
    EnterFrameCommand,
    LinkSituationToProjectCommand,
    OpenSituationCommand,
    RecordRelationshipEventCommand,
    TraceObjectCommand,
)
from my_pa.contracts.ports import (
    FrameRepository,
    ProjectRepository,
    PulseRepository,
    RelationshipEventRepository,
    SituationRepository,
    TraceRepository,
)
from my_pa.domain.relationship.event import RelationshipEvent
from my_pa.domain.situation.situation import Frame, Project, PulseItem, Situation, Trace

__all__ = ["SituationService"]


class SituationService:
    """Route each continuity command to the port that answers it, principal-scoped."""

    def open_situation(self, repo: SituationRepository, cmd: OpenSituationCommand) -> Situation:
        """Open one purposeful operational context for the command's Principal."""
        return repo.open_situation(
            principal_id=cmd.principal_id,
            title=cmd.title,
            description=cmd.description,
            object_refs=cmd.object_refs,
        )

    def close_situation(self, repo: SituationRepository, cmd: CloseSituationCommand) -> Situation:
        """Close one Situation the Principal owns, recording its outcome."""
        return repo.close_situation(
            principal_id=cmd.principal_id,
            situation_id=cmd.situation_id,
            outcome=cmd.outcome,
            evidence_kind=cmd.evidence_kind,
            evidence_ref=cmd.evidence_ref,
        )

    def enter_frame(self, repo: FrameRepository, cmd: EnterFrameCommand) -> Frame:
        """Enter the current view within a Situation the Principal owns."""
        return repo.enter_frame(
            principal_id=cmd.principal_id,
            situation_id=cmd.situation_id,
            label=cmd.label,
            evidence_refs=cmd.evidence_refs,
            alternatives=cmd.alternatives,
            obligations=cmd.obligations,
            uncertainty=cmd.uncertainty,
            next_authority=cmd.next_authority,
        )

    def add_project(self, repo: ProjectRepository, cmd: AddProjectCommand) -> Project:
        """Create one durable work context for the command's Principal."""
        return repo.add_project(
            principal_id=cmd.principal_id,
            name=cmd.name,
            description=cmd.description,
            participants=cmd.participants,
        )

    def link_situation_to_project(
        self,
        situation_repo: SituationRepository,
        project_repo: ProjectRepository,
        cmd: LinkSituationToProjectCommand,
    ) -> None:
        """Bind a Situation into a Project, both owned by the command's Principal.

        The Situation is resolved through `situation_repo` first so the link
        cannot name a Situation outside the Principal's partition; the
        `project_repo` then creates the binding, which is also refused unless the
        Project is in that same partition.
        """
        if situation_repo.get_situation(cmd.principal_id, cmd.situation_id) is None:
            raise ValueError("cannot link a situation the principal does not own")
        project_repo.link_situation(
            principal_id=cmd.principal_id,
            project_id=cmd.project_id,
            situation_id=cmd.situation_id,
            evidence_kind=cmd.evidence_kind,
            evidence_ref=cmd.evidence_ref,
        )

    def record_relationship_event(
        self, repo: RelationshipEventRepository, cmd: RecordRelationshipEventCommand
    ) -> RelationshipEvent:
        """Record one event on a Person's relationship timeline for the Principal."""
        return repo.record_event(
            principal_id=cmd.principal_id,
            person_id=cmd.person_id,
            event_type=cmd.event_type,
            occurred_at=cmd.occurred_at,
            context=cmd.context,
            accepted=cmd.accepted,
            source_ref=cmd.source_ref,
        )

    def trace_object(self, repo: TraceRepository, cmd: TraceObjectCommand) -> Trace:
        """Reconstruct one object over a time range for the command's Principal."""
        return repo.record_trace(
            principal_id=cmd.principal_id,
            object_id=cmd.object_id,
            object_type=cmd.object_type,
            time_range_start=cmd.time_range_start,
            time_range_end=cmd.time_range_end,
        )

    def get_pulse(self, repo: PulseRepository, principal_id: str) -> tuple[PulseItem, ...]:
        """The Principal's active Pulse, generated only from accepted records."""
        return repo.generate_pulse(principal_id)
