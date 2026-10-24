"""The public shapes of the Program reads (record lineage S4 contract sections 7.1 and 7.2).

`ProgramMembershipView` is one `programs.members.resolve` answer: for each
requested Program, the exact Continuity Projects that are its members --
derived only from typed `member_of` edges and the Project-Entity bridge -- and
everything the rule could not prove, named. `ProgramOverviewView` is one
`programs.overview` answer (section 7.2): the 13 section 3.2 metrics per
Project, per Program and per portfolio from one snapshot, each total
`reported` only when complete enough (OD-08) and otherwise naming why, with
the denominator in view, and its section 5.1 digest. A field derived from a
family the reader may not see is `null` (a metric `restricted`).

**What these models cannot carry is the point of them.** No name, alias or
display field of any Entity or Project, no `principal_id`, and no count that
is not a count of the caller's own rows. Every instant is the section 5.3
microsecond UTC token (`%Y-%m-%dT%H:%M:%S.%fZ`).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
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
from my_pa.domain.program.reportability import MetricId, MetricValue, ScopeDenominator
from my_pa.domain.program.vocabulary import (
    AcceptanceVerification,
    ConstraintSourceState,
    MembershipMode,
    MemberUnresolvedReason,
    MemberUnverifiedReason,
    MetricGrain,
    MetricValueState,
    NotReportableReason,
    ProgramCompleteness,
)
from my_pa.domain.project_controls.read_models import (
    ConstraintSyncHealthView,
    ConstraintSyncStateView,
)
from my_pa.domain.relationship.entity import EntityStatus
from my_pa.domain.situation.situation import ProjectState

__all__ = [
    "ConstraintSourceStateCountsView",
    "ConstraintSourceStateProjectsView",
    "ConstraintSyncView",
    "MembershipExclusionsView",
    "MembershipPortfolioView",
    "MetricView",
    "OverviewDenominatorView",
    "OverviewPortfolioView",
    "OverviewProgramView",
    "OverviewProjectView",
    "ProgramMemberView",
    "ProgramMembershipView",
    "ProgramOverlapView",
    "ProgramOverviewView",
    "ProjectCalendarView",
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


# --- programs.overview (section 7.2) -----------------------------------------


class MetricView(StrictModel):
    """One metric at one scope (section 7.2 `MetricView`).

    `value` is a count only when `value_state` is `reported` (a `0` then being a
    verified zero); `not_reportable` names every reason, `restricted` none.
    """

    metric_id: MetricId
    grain: MetricGrain
    value: int | None = Field(ge=0)
    value_state: MetricValueState
    reasons: tuple[NotReportableReason, ...]
    nonadditive_across_projects: bool
    acceptance: AcceptanceVerification | None

    @classmethod
    def of(cls, metric: MetricValue) -> MetricView:
        return cls(
            metric_id=metric.metric_id,
            grain=metric.grain,
            value=metric.value,
            value_state=metric.value_state,
            reasons=metric.reasons,
            nonadditive_across_projects=metric.nonadditive_across_projects,
            acceptance=metric.acceptance,
        )


class ConstraintSourceStateCountsView(StrictModel):
    """How many of a scope's Projects are in each Constraint source state."""

    in_sync: int = Field(ge=0)
    never_synced: int = Field(ge=0)
    unverified: int = Field(ge=0)
    sync_degraded: int = Field(ge=0)
    conflict: int = Field(ge=0)
    calendar_unconfigured: int = Field(ge=0)

    @classmethod
    def of(cls, counts: Mapping[ConstraintSourceState, int]) -> ConstraintSourceStateCountsView:
        return cls(**{state.value: counts.get(state, 0) for state in ConstraintSourceState})


class ConstraintSourceStateProjectsView(StrictModel):
    """Which of a scope's Projects (the caller's own ids, sorted) are in each source state."""

    in_sync: tuple[str, ...]
    never_synced: tuple[str, ...]
    unverified: tuple[str, ...]
    sync_degraded: tuple[str, ...]
    conflict: tuple[str, ...]
    calendar_unconfigured: tuple[str, ...]

    @classmethod
    def of(
        cls, ids: Mapping[ConstraintSourceState, tuple[str, ...]]
    ) -> ConstraintSourceStateProjectsView:
        return cls(**{state.value: ids.get(state, ()) for state in ConstraintSourceState})


class OverviewDenominatorView(StrictModel):
    """Section 3.3: what a scope's totals are taken over (never hidden)."""

    member_projects: int = Field(ge=0)
    unresolved_members: int = Field(ge=0)
    legacy_issue_links: int | None = Field(ge=0)
    legacy_issue_links_closed: int | None = Field(ge=0)
    projects_by_constraint_source_state: ConstraintSourceStateCountsView | None

    @classmethod
    def of(cls, denominator: ScopeDenominator) -> OverviewDenominatorView:
        counts = denominator.projects_by_constraint_source_state
        return cls(
            member_projects=denominator.member_projects,
            unresolved_members=denominator.unresolved_members,
            legacy_issue_links=denominator.legacy_issue_links,
            legacy_issue_links_closed=denominator.legacy_issue_links_closed,
            projects_by_constraint_source_state=(
                None if counts is None else ConstraintSourceStateCountsView.of(counts)
            ),
        )


def _projects_by_state(
    denominator: ScopeDenominator,
) -> ConstraintSourceStateProjectsView | None:
    ids = denominator.project_ids_by_constraint_source_state
    return None if ids is None else ConstraintSourceStateProjectsView.of(ids)


class OverviewProgramView(StrictModel):
    """One requested Program's scope of the overview."""

    program_entity_id: str
    resolved_program_entity_id: str
    membership_state: ProgramCompleteness
    project_ids: tuple[str, ...]
    unresolved_members: tuple[UnresolvedMemberView, ...]
    denominator: OverviewDenominatorView
    project_ids_by_constraint_source_state: ConstraintSourceStateProjectsView | None
    project_ids_with_legacy_issue_links: tuple[str, ...] | None
    totals: tuple[MetricView, ...]

    @classmethod
    def of(
        cls,
        program: ProgramResolution,
        *,
        denominator: ScopeDenominator,
        totals: tuple[MetricValue, ...],
    ) -> OverviewProgramView:
        return cls(
            program_entity_id=program.program_entity_id,
            resolved_program_entity_id=program.resolved_program_entity_id,
            membership_state=program.complete_state,
            project_ids=tuple(member.project_id for member in program.members),
            unresolved_members=tuple(
                UnresolvedMemberView.of(member) for member in program.unresolved_members
            ),
            denominator=OverviewDenominatorView.of(denominator),
            project_ids_by_constraint_source_state=_projects_by_state(denominator),
            project_ids_with_legacy_issue_links=denominator.project_ids_with_legacy_issue_links,
            totals=tuple(MetricView.of(metric) for metric in totals),
        )


class OverviewPortfolioView(StrictModel):
    """Every resolved Project of the request once (portfolio grain), and its totals."""

    project_ids: tuple[str, ...]
    overlaps: tuple[ProgramOverlapView, ...]
    denominator: OverviewDenominatorView
    project_ids_by_constraint_source_state: ConstraintSourceStateProjectsView | None
    project_ids_with_legacy_issue_links: tuple[str, ...] | None
    totals: tuple[MetricView, ...]

    @classmethod
    def of(
        cls,
        resolution: MembershipResolution,
        *,
        denominator: ScopeDenominator,
        totals: tuple[MetricValue, ...],
    ) -> OverviewPortfolioView:
        return cls(
            project_ids=resolution.portfolio.project_ids,
            overlaps=tuple(
                ProgramOverlapView(
                    project_id=overlap.project_id, program_entity_ids=overlap.program_entity_ids
                )
                for overlap in resolution.portfolio.overlaps
            ),
            denominator=OverviewDenominatorView.of(denominator),
            project_ids_by_constraint_source_state=_projects_by_state(denominator),
            project_ids_with_legacy_issue_links=denominator.project_ids_with_legacy_issue_links,
            totals=tuple(MetricView.of(metric) for metric in totals),
        )


class ProjectCalendarView(StrictModel):
    """A Project's own Constraint calendar: both `null` when it has no usable one."""

    timezone_name: str | None
    project_today: str | None

    @classmethod
    def of(cls, timezone_name: str | None, today: date | None) -> ProjectCalendarView:
        return cls(
            timezone_name=timezone_name, project_today=None if today is None else today.isoformat()
        )


class ConstraintSyncView(StrictModel):
    """The existing `ConstraintSyncHealthView`, shown for continuity; it decides nothing."""

    state: ConstraintSyncStateView
    open_conflict_count: int = Field(ge=0)
    last_verified_at: str | None

    @classmethod
    def of(cls, health: ConstraintSyncHealthView) -> ConstraintSyncView:
        verified = health.last_verified_at
        return cls(
            state=health.state,
            open_conflict_count=health.open_conflict_count,
            last_verified_at=None if verified is None else program_instant(verified),
        )


class OverviewProjectView(StrictModel):
    """One resolved Project of the overview, once (section 7.2 `per_project`)."""

    project_id: str
    project_state: ProjectState
    calendar: ProjectCalendarView | None
    constraint_source_state: ConstraintSourceState | None
    constraint_last_run_sync_states: tuple[str, ...] | None
    constraint_sync: ConstraintSyncView | None
    legacy_issue_links: int | None = Field(ge=0)
    legacy_issue_links_closed: int | None = Field(ge=0)
    metrics: tuple[MetricView, ...]


class ProgramOverviewView(StrictModel):
    """One `programs.overview` answer (section 7.2).

    `source_cutoff_at` is the snapshot instant every figure is read at;
    `lineage_known_at` the committed lineage horizon of the Issue links read
    (`null` without the `issue` family, or without a lineage fact).
    `overview_sha256` is section 5.1's digest of this answer without its 3
    read-time stamps.
    """

    source_cutoff_at: str
    lineage_known_at: str | None
    metric_schema_version: Literal[1]
    calculation_version: Literal["program-overview-v1"]
    programs: tuple[OverviewProgramView, ...] = Field(min_length=1)
    portfolio: OverviewPortfolioView
    per_project: tuple[OverviewProjectView, ...]
    complete_state: ProgramCompleteness
    qualifiers: tuple[ProgramCompleteness, ...] = Field(min_length=1)
    overview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
