"""The Program metric catalogue and its reportability (record lineage S4 sections 3.2, 3.3).

Pure: per-Project facts in, per-Project values, Program and portfolio totals,
their reasons and their denominator out. Nothing here reads a database.

**Totals are distinct counts over a scope's Project set** (one Project, one
Program, or the portfolio). The additive grains name one `project_id` per row,
so the total of a set of Projects is the sum of their disjoint per-Project
counts; the `issue` grain is a set of `(project_id, situation_id)` pairs, so an
Issue that impacts 2 Projects of a scope counts once in it, and
`issue_outstanding` is flagged `nonadditive_across_projects`.

**OD-08: `NOT_REPORTABLE` on any material gap, and no zero is ever
substituted.** A total is `reported` (a verified zero included) only when no
reason applies; otherwise its value is `None` and every reason is named. An
invisible family is `restricted` (value `None`, no reason): never a count.

`commitment_acceptance_proof` is the one place a later Work decision on
verified Commitment acceptance changes the accepted totals (S4 D-04).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.program.vocabulary import (
    AcceptanceVerification,
    ConstraintSourceState,
    MetricGrain,
    MetricValueState,
    NotReportableReason,
    ProgramFamily,
)

__all__ = [
    "ACCEPTANCE_PROVING",
    "COMMITMENT_METRICS",
    "CONSTRAINT_METRICS",
    "CONSTRAINT_SOURCE_PRECEDENCE",
    "METRIC_CATALOGUE",
    "MetricDefinition",
    "MetricId",
    "MetricValue",
    "ProjectFacts",
    "ScopeDenominator",
    "SyncTarget",
    "commitment_acceptance_proof",
    "constraint_source_state",
    "project_metric",
    "scope_denominator",
    "scope_total",
    "target_state",
]


class MetricId(StrEnum):
    """Section 3.2: the 13 metrics of `PROGRAM_METRIC_SCHEMA_VERSION = 1`, in catalogue order."""

    COMMITMENT_OPEN_ACCEPTED = "commitment_open_accepted"
    COMMITMENT_OPEN_PROPOSED = "commitment_open_proposed"
    COMMITMENT_CLOSED_PROPOSED = "commitment_closed_proposed"
    COMMITMENT_OVERDUE_ACCEPTED = "commitment_overdue_accepted"
    COMMITMENT_OVERDUE_PROPOSED = "commitment_overdue_proposed"
    COMMITMENT_UNSCHEDULED_ACCEPTED = "commitment_unscheduled_accepted"
    COMMITMENT_UNSCHEDULED_PROPOSED = "commitment_unscheduled_proposed"
    ISSUE_OUTSTANDING = "issue_outstanding"
    CONSTRAINT_OPEN = "constraint_open"
    CONSTRAINT_OVERDUE = "constraint_overdue"
    CONSTRAINT_DUE_SOON = "constraint_due_soon"
    CONSTRAINT_IN_MY_COURT = "constraint_in_my_court"
    CONSTRAINT_DRAFT = "constraint_draft"


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """One catalogue row: its grain, the family it derives from, and how it adds."""

    metric_id: MetricId
    grain: MetricGrain
    family: ProgramFamily
    accepted: bool = False
    nonadditive_across_projects: bool = False


_COMMITMENT: Final = (MetricGrain.COMMITMENT, ProgramFamily.COMMITMENT)
_CONSTRAINT: Final = (MetricGrain.CONSTRAINT, ProgramFamily.CONSTRAINT)

#: Section 3.2, in catalogue order (`totals` and `metrics` follow it).
METRIC_CATALOGUE: Final[tuple[MetricDefinition, ...]] = (
    MetricDefinition(MetricId.COMMITMENT_OPEN_ACCEPTED, *_COMMITMENT, accepted=True),
    MetricDefinition(MetricId.COMMITMENT_OPEN_PROPOSED, *_COMMITMENT),
    MetricDefinition(MetricId.COMMITMENT_CLOSED_PROPOSED, *_COMMITMENT),
    MetricDefinition(MetricId.COMMITMENT_OVERDUE_ACCEPTED, *_COMMITMENT, accepted=True),
    MetricDefinition(MetricId.COMMITMENT_OVERDUE_PROPOSED, *_COMMITMENT),
    MetricDefinition(MetricId.COMMITMENT_UNSCHEDULED_ACCEPTED, *_COMMITMENT, accepted=True),
    MetricDefinition(MetricId.COMMITMENT_UNSCHEDULED_PROPOSED, *_COMMITMENT),
    MetricDefinition(
        MetricId.ISSUE_OUTSTANDING,
        MetricGrain.ISSUE,
        ProgramFamily.ISSUE,
        nonadditive_across_projects=True,
    ),
    MetricDefinition(MetricId.CONSTRAINT_OPEN, *_CONSTRAINT),
    MetricDefinition(MetricId.CONSTRAINT_OVERDUE, *_CONSTRAINT),
    MetricDefinition(MetricId.CONSTRAINT_DUE_SOON, *_CONSTRAINT),
    MetricDefinition(MetricId.CONSTRAINT_IN_MY_COURT, *_CONSTRAINT),
    MetricDefinition(MetricId.CONSTRAINT_DRAFT, *_CONSTRAINT),
)

#: The 7 Commitment metrics and the 5 Constraint metrics, in catalogue order.
COMMITMENT_METRICS: Final[tuple[MetricId, ...]] = tuple(
    row.metric_id for row in METRIC_CATALOGUE if row.grain is MetricGrain.COMMITMENT
)
CONSTRAINT_METRICS: Final[tuple[MetricId, ...]] = tuple(
    row.metric_id for row in METRIC_CATALOGUE if row.grain is MetricGrain.CONSTRAINT
)

#: Section 3.3: the verification states that prove a Commitment's acceptance.
#: Empty in S4 -- no capability-reachable route verifies one (S2 D-05/D-17,
#: S3 D-11) -- so every accepted Program total is `acceptance_unverified`.
ACCEPTANCE_PROVING: Final[frozenset[AcceptanceVerification]] = frozenset()

#: Section 3.3: a Project's source state is the worst of its targets' by this
#: order, and overall `calendar_unconfigured` > ... > `in_sync`.
CONSTRAINT_SOURCE_PRECEDENCE: Final[tuple[ConstraintSourceState, ...]] = (
    ConstraintSourceState.CALENDAR_UNCONFIGURED,
    ConstraintSourceState.CONFLICT,
    ConstraintSourceState.SYNC_DEGRADED,
    ConstraintSourceState.UNVERIFIED,
    ConstraintSourceState.NEVER_SYNCED,
    ConstraintSourceState.IN_SYNC,
)

#: Section 3.3: the reason a Constraint total names for a Project in each state.
_SOURCE_REASON: Final = {
    ConstraintSourceState.CALENDAR_UNCONFIGURED: NotReportableReason.CALENDAR_UNCONFIGURED,
    ConstraintSourceState.NEVER_SYNCED: NotReportableReason.NEVER_SYNCED,
    ConstraintSourceState.UNVERIFIED: NotReportableReason.SYNC_UNVERIFIED,
    ConstraintSourceState.SYNC_DEGRADED: NotReportableReason.SYNC_DEGRADED,
    ConstraintSourceState.CONFLICT: NotReportableReason.SYNC_CONFLICT,
}

#: The one persisted run outcome that is not a degraded last run.
_IN_SYNC_RUN: Final = "in_sync"
#: Native `evidence_state` of an accepted Commitment.
_ACCEPTED: Final = "accepted"


def commitment_acceptance_proof(evidence_state: str) -> AcceptanceVerification:
    """Section 3.3 (D-04): what a native Commitment's acceptance proves.

    A natively `accepted` Commitment carries an unverified review reference --
    never a proven acceptance in S4; anything else is not accepted.
    """
    if evidence_state == _ACCEPTED:
        return AcceptanceVerification.UNVERIFIED_REVIEW_REFERENCE
    return AcceptanceVerification.NOT_ACCEPTED


def _acceptance_proven() -> bool:
    """Whether a native accepted Commitment's acceptance is proven (never in S4)."""
    return commitment_acceptance_proof(_ACCEPTED) in ACCEPTANCE_PROVING


@dataclass(frozen=True, slots=True)
class SyncTarget:
    """One stored `constraint_sync_targets` row of a Project with its last run's outcome."""

    last_verified_at: datetime | None
    last_run_id: str | None
    last_run_sync_state: str | None


def target_state(target: SyncTarget, *, project_has_open_conflict: bool) -> ConstraintSourceState:
    """Section 3.3 (R4-F01): one target's state, its conditions checked in order."""
    if project_has_open_conflict:
        return ConstraintSourceState.CONFLICT
    if target.last_verified_at is None or target.last_run_id is None:
        return ConstraintSourceState.UNVERIFIED
    if target.last_run_sync_state != _IN_SYNC_RUN:
        return ConstraintSourceState.SYNC_DEGRADED
    return ConstraintSourceState.IN_SYNC


def constraint_source_state(
    *,
    calendar_configured: bool,
    targets: Sequence[SyncTarget],
    open_conflicts: int,
) -> ConstraintSourceState:
    """Section 3.3: a Project's Constraint source state from its stored sync data.

    `calendar_unconfigured` without a usable calendar; else `never_synced`
    with no target; else the worst of its targets' states (a Project with 2
    workbooks is `in_sync` only when both are).
    """
    if not calendar_configured:
        return ConstraintSourceState.CALENDAR_UNCONFIGURED
    if not targets:
        return ConstraintSourceState.NEVER_SYNCED
    states = {
        target_state(target, project_has_open_conflict=open_conflicts > 0) for target in targets
    }
    return next(state for state in CONSTRAINT_SOURCE_PRECEDENCE if state in states)


@dataclass(frozen=True, slots=True)
class ProjectFacts:
    """Everything one resolved Project contributes, read in the one snapshot.

    A family the reader does not see is `None` here (its facts were not read).
    `constraint_counts` is `None` also when the Project has no usable calendar
    (`calendar_configured` False): no defensible overdue boundary, no count.
    """

    project_id: str
    commitment_counts: Mapping[MetricId, int] | None
    issue_ids: frozenset[str] | None
    legacy_issue_links: int | None
    legacy_issue_links_closed: int | None
    constraint_source_state: ConstraintSourceState | None
    constraint_counts: Mapping[MetricId, int] | None
    #: Record lineage S3.1 (S3.1 contract section 7.8): the Project's Issue
    #: links whose latest event is `client_identified` (any state) of an Issue
    #: not closed. Like a legacy link, neither counted nor dropped: it makes the
    #: Issue metric `not_reportable` (`issue_link_unverified`).
    unreviewed_issue_links: int | None = 0


@dataclass(frozen=True, slots=True)
class MetricValue:
    """One metric at one scope: a count, or why there is none."""

    metric_id: MetricId
    grain: MetricGrain
    value: int | None
    value_state: MetricValueState
    reasons: tuple[NotReportableReason, ...]
    nonadditive_across_projects: bool
    acceptance: AcceptanceVerification | None


def _definition(metric_id: MetricId) -> MetricDefinition:
    return next(row for row in METRIC_CATALOGUE if row.metric_id is metric_id)


def _value(
    definition: MetricDefinition,
    value: int | None,
    reasons: Iterable[NotReportableReason],
    *,
    restricted: bool = False,
) -> MetricValue:
    acceptance = AcceptanceVerification.UNVERIFIED_REVIEW_REFERENCE if definition.accepted else None
    ordered: tuple[NotReportableReason, ...] = () if restricted else tuple(sorted(set(reasons)))
    if restricted:
        state, value = MetricValueState.RESTRICTED, None
    elif ordered:
        state, value = MetricValueState.NOT_REPORTABLE, None
    else:
        state = MetricValueState.REPORTED
    return MetricValue(
        metric_id=definition.metric_id,
        grain=definition.grain,
        value=value,
        value_state=state,
        reasons=ordered,
        nonadditive_across_projects=definition.nonadditive_across_projects,
        acceptance=acceptance,
    )


def _family_facts_missing(definition: MetricDefinition, facts: ProjectFacts) -> bool:
    if definition.family is ProgramFamily.COMMITMENT:
        return facts.commitment_counts is None
    if definition.family is ProgramFamily.ISSUE:
        return facts.issue_ids is None
    return facts.constraint_source_state is None


def _unverified_links(facts: ProjectFacts) -> bool:
    """Section 3.3 (R4-F02) and S3.1 section 7.8: an outstanding legacy or unreviewed link."""
    return (facts.legacy_issue_links or 0) > 0 or (facts.unreviewed_issue_links or 0) > 0


def project_metric(
    metric_id: MetricId, facts: ProjectFacts, *, visible: Collection[ProgramFamily]
) -> MetricValue:
    """Section 3.3: one metric of one Project.

    `reported` whenever it is computable; `not_reportable` for a Constraint
    metric of a Project without a calendar (`calendar_unconfigured`) and for
    the Issue metric of a Project with outstanding legacy links
    (`issue_link_unverified`); `restricted` when its family is invisible.
    """
    definition = _definition(metric_id)
    if definition.family not in visible or _family_facts_missing(definition, facts):
        return _value(definition, None, (), restricted=True)
    if definition.family is ProgramFamily.COMMITMENT:
        counts = facts.commitment_counts or {}
        return _value(definition, counts.get(metric_id, 0), ())
    if definition.family is ProgramFamily.ISSUE:
        reasons = (NotReportableReason.ISSUE_LINK_UNVERIFIED,) if _unverified_links(facts) else ()
        return _value(definition, len(facts.issue_ids or ()), reasons)
    if facts.constraint_counts is None:
        return _value(definition, None, (NotReportableReason.CALENDAR_UNCONFIGURED,))
    return _value(definition, facts.constraint_counts.get(metric_id, 0), ())


def scope_total(
    metric_id: MetricId,
    projects: Sequence[ProjectFacts],
    *,
    visible: Collection[ProgramFamily],
    membership_unresolved: bool,
    membership_truncated: bool,
    acceptance_proven: bool | None = None,
) -> MetricValue:
    """Section 3.3: one metric's total over a Program's or the portfolio's Projects.

    The value is the distinct count over the scope (the Issue grain over its
    `(project, issue)` pairs); it is `reported` -- a `0` then being a verified
    zero -- only when no reason applies. `acceptance_proven` defaults to what
    `commitment_acceptance_proof` says of native acceptance (never, in S4).
    """
    definition = _definition(metric_id)
    if definition.family not in visible or any(
        _family_facts_missing(definition, facts) for facts in projects
    ):
        return _value(definition, None, (), restricted=True)
    reasons: set[NotReportableReason] = set()
    if membership_unresolved:
        reasons.add(NotReportableReason.MEMBERSHIP_UNRESOLVED)
    if membership_truncated:
        reasons.add(NotReportableReason.MEMBERSHIP_TRUNCATED)
    proven = _acceptance_proven() if acceptance_proven is None else acceptance_proven
    if definition.accepted and not proven:
        reasons.add(NotReportableReason.ACCEPTANCE_UNVERIFIED)
    value: int | None
    if definition.family is ProgramFamily.COMMITMENT:
        value = sum((facts.commitment_counts or {}).get(metric_id, 0) for facts in projects)
    elif definition.family is ProgramFamily.ISSUE:
        if any(_unverified_links(facts) for facts in projects):
            reasons.add(NotReportableReason.ISSUE_LINK_UNVERIFIED)
        distinct: set[str] = set()
        for facts in projects:
            distinct |= facts.issue_ids or frozenset()
        value = len(distinct)
    else:
        for facts in projects:
            state = facts.constraint_source_state
            if state is not None and state in _SOURCE_REASON:
                reasons.add(_SOURCE_REASON[state])
        value = sum((facts.constraint_counts or {}).get(metric_id, 0) for facts in projects)
    return _value(definition, value, reasons)


@dataclass(frozen=True, slots=True)
class ScopeDenominator:
    """Section 3.3: what a scope's totals are taken over, never hidden.

    The legacy-link parts are `None` when the `issue` family is invisible, the
    source-state parts when the `constraint` family is.
    """

    member_projects: int
    unresolved_members: int
    legacy_issue_links: int | None
    legacy_issue_links_closed: int | None
    projects_by_constraint_source_state: Mapping[ConstraintSourceState, int] | None
    project_ids_by_constraint_source_state: Mapping[ConstraintSourceState, tuple[str, ...]] | None
    project_ids_with_legacy_issue_links: tuple[str, ...] | None
    #: S3.1 section 7.8: the unreviewed Issue links (`None` with the `issue`
    #: family invisible, as the legacy parts).
    unreviewed_issue_links: int | None = None
    project_ids_with_unreviewed_issue_links: tuple[str, ...] | None = None


def scope_denominator(
    projects: Sequence[ProjectFacts],
    *,
    unresolved_members: int,
    visible: Collection[ProgramFamily],
) -> ScopeDenominator:
    """The denominator of one scope over its Projects' facts (section 3.3)."""
    issue_seen = ProgramFamily.ISSUE in visible and all(
        facts.legacy_issue_links is not None for facts in projects
    )
    constraint_seen = ProgramFamily.CONSTRAINT in visible and all(
        facts.constraint_source_state is not None for facts in projects
    )
    by_state: dict[ConstraintSourceState, list[str]] | None = None
    if constraint_seen:
        by_state = {state: [] for state in ConstraintSourceState}
        for facts in projects:
            if facts.constraint_source_state is not None:
                by_state[facts.constraint_source_state].append(facts.project_id)
    return ScopeDenominator(
        member_projects=len(projects),
        unresolved_members=unresolved_members,
        legacy_issue_links=(
            sum(facts.legacy_issue_links or 0 for facts in projects) if issue_seen else None
        ),
        legacy_issue_links_closed=(
            sum(facts.legacy_issue_links_closed or 0 for facts in projects) if issue_seen else None
        ),
        projects_by_constraint_source_state=(
            None if by_state is None else {state: len(ids) for state, ids in by_state.items()}
        ),
        project_ids_by_constraint_source_state=(
            None
            if by_state is None
            else {state: tuple(sorted(ids)) for state, ids in by_state.items()}
        ),
        project_ids_with_legacy_issue_links=(
            tuple(sorted(facts.project_id for facts in projects if facts.legacy_issue_links))
            if issue_seen
            else None
        ),
        unreviewed_issue_links=(
            sum(facts.unreviewed_issue_links or 0 for facts in projects) if issue_seen else None
        ),
        project_ids_with_unreviewed_issue_links=(
            tuple(sorted(facts.project_id for facts in projects if facts.unreviewed_issue_links))
            if issue_seen
            else None
        ),
    )
