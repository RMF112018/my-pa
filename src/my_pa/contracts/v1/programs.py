"""The public shapes of the Program reads (record lineage S4 contract sections 7.1 and 7.2).

`ProgramMembershipView` is one `programs.members.resolve` answer: for each
requested Program, the exact Continuity Projects that are its members --
derived only from typed `member_of` edges and the Project-Entity bridge -- and
everything the rule could not prove, named. The overview part (section 7.2) is
added beside it by the overview package.

**What these models cannot carry is the point of them.** No name, alias or
display field of any Entity or Project, no `principal_id`, and no count that
is not a count of the caller's own rows. Every instant is the section 5.3
microsecond UTC token (`%Y-%m-%dT%H:%M:%S.%fZ`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from my_pa.contracts.v1.base import StrictModel
from my_pa.domain.lineage.cursor import instant_token
from my_pa.domain.program.membership import (
    MembershipResolution,
    ProgramMember,
    ProgramResolution,
    UnresolvedMember,
    UnverifiedMember,
)
from my_pa.domain.program.vocabulary import (
    MembershipMode,
    MemberUnresolvedReason,
    MemberUnverifiedReason,
    ProgramCompleteness,
)
from my_pa.domain.relationship.entity import EntityStatus
from my_pa.domain.situation.situation import ProjectState

__all__ = [
    "MembershipExclusionsView",
    "MembershipPortfolioView",
    "ProgramMemberView",
    "ProgramMembershipView",
    "ProgramOverlapView",
    "ResolvedProgramView",
    "UnresolvedMemberView",
    "UnverifiedMemberView",
    "program_instant",
]


def program_instant(value: datetime) -> str:
    """An aware instant as the section 5.3 token (`%Y-%m-%dT%H:%M:%S.%fZ`, UTC)."""
    token = instant_token(value)
    if token is None:  # pragma: no cover - `value` is an instant
        raise ValueError("a Program answer instant is required")
    return token


class ProgramMemberView(StrictModel):
    """One member Project of one Program, once, with every edge that reached it."""

    project_id: str
    project_entity_id: str
    member_entity_status: EntityStatus
    project_state: ProjectState
    relationship_ids: tuple[str, ...] = Field(min_length=1)

    @classmethod
    def of(cls, member: ProgramMember) -> ProgramMemberView:
        return cls(
            project_id=member.project_id,
            project_entity_id=member.project_entity_id,
            member_entity_status=EntityStatus(member.member_entity_status),
            project_state=ProjectState(member.project_state),
            relationship_ids=member.relationship_ids,
        )


class UnresolvedMemberView(StrictModel):
    """An in-window member edge that names no exact Project, and why."""

    relationship_id: str
    member_entity_id: str
    reason: MemberUnresolvedReason

    @classmethod
    def of(cls, member: UnresolvedMember) -> UnresolvedMemberView:
        return cls(
            relationship_id=member.relationship_id,
            member_entity_id=member.member_entity_id,
            reason=member.reason,
        )


class UnverifiedMemberView(StrictModel):
    """A historical edge whose recorded dates cannot prove membership at `valid_at`."""

    relationship_id: str
    member_entity_id: str
    project_id: str | None
    reason: MemberUnverifiedReason

    @classmethod
    def of(cls, member: UnverifiedMember) -> UnverifiedMemberView:
        return cls(
            relationship_id=member.relationship_id,
            member_entity_id=member.member_entity_id,
            project_id=member.project_id,
            reason=member.reason,
        )


class MembershipExclusionsView(StrictModel):
    """Edges of the caller's own that were read and are not Project members (counts)."""

    non_project_members: int = Field(ge=0)
    outside_window: int = Field(ge=0)


class ResolvedProgramView(StrictModel):
    """One requested Program's membership (section 7.1)."""

    program_entity_id: str
    resolved_program_entity_id: str
    redirected: bool
    program_status: EntityStatus
    members: tuple[ProgramMemberView, ...]
    unresolved_members: tuple[UnresolvedMemberView, ...]
    unverified_members: tuple[UnverifiedMemberView, ...]
    excluded: MembershipExclusionsView
    complete_state: ProgramCompleteness
    qualifiers: tuple[ProgramCompleteness, ...] = Field(min_length=1)

    @classmethod
    def of(cls, program: ProgramResolution) -> ResolvedProgramView:
        return cls(
            program_entity_id=program.program_entity_id,
            resolved_program_entity_id=program.resolved_program_entity_id,
            redirected=program.redirected,
            program_status=EntityStatus(program.program_status),
            members=tuple(ProgramMemberView.of(member) for member in program.members),
            unresolved_members=tuple(
                UnresolvedMemberView.of(member) for member in program.unresolved_members
            ),
            unverified_members=tuple(
                UnverifiedMemberView.of(member) for member in program.unverified_members
            ),
            excluded=MembershipExclusionsView(
                non_project_members=program.non_project_members,
                outside_window=program.outside_window,
            ),
            complete_state=program.complete_state,
            qualifiers=program.qualifiers,
        )


class ProgramOverlapView(StrictModel):
    """A Project that is a member of more than one resolved Program."""

    project_id: str
    program_entity_ids: tuple[str, ...] = Field(min_length=2)


class MembershipPortfolioView(StrictModel):
    """Every member Project of the request once (portfolio grain), and the overlaps."""

    project_ids: tuple[str, ...]
    overlaps: tuple[ProgramOverlapView, ...]


class ProgramMembershipView(StrictModel):
    """One `programs.members.resolve` answer (section 7.1).

    `valid_at` is the requested instant in historical mode and the snapshot's
    `source_cutoff_at` in current mode. `membership_record` says the recorded
    effective windows, redirects and bridges are read as they are recorded now
    (section 3.4, D-05).
    """

    mode: MembershipMode
    valid_at: str
    source_cutoff_at: str
    membership_record: Literal["current"]
    programs: tuple[ResolvedProgramView, ...] = Field(min_length=1)
    portfolio: MembershipPortfolioView
    complete_state: ProgramCompleteness
    qualifiers: tuple[ProgramCompleteness, ...] = Field(min_length=1)

    @classmethod
    def of(cls, resolution: MembershipResolution) -> ProgramMembershipView:
        return cls(
            mode=resolution.mode,
            valid_at=program_instant(resolution.valid_at),
            source_cutoff_at=program_instant(resolution.source_cutoff_at),
            membership_record="current",
            programs=tuple(ResolvedProgramView.of(program) for program in resolution.programs),
            portfolio=MembershipPortfolioView(
                project_ids=resolution.portfolio.project_ids,
                overlaps=tuple(
                    ProgramOverlapView(
                        project_id=overlap.project_id,
                        program_entity_ids=overlap.program_entity_ids,
                    )
                    for overlap in resolution.portfolio.overlaps
                ),
            ),
            complete_state=resolution.complete_state,
            qualifiers=resolution.qualifiers,
        )
